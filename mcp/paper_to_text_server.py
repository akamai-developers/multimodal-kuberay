"""
Paper-to-Text MCP Server
==========================
requirements: fastmcp>=3.0.0, httpx>=0.27.0, pypdfium2>=4.30.0, openai>=1.40.0, Pillow>=10.0.0, uvicorn>=0.30.0

OCR academic papers: download PDF → render pages to PNG → OCR with Nemotron Parse.
All papers render in parallel (ProcessPoolExecutor) and all pages fire OCR
concurrently across 16 Nemotron Parse replicas (MIG-partitioned GPUs).

Tools:
  - read_papers:       Batch-process multiple papers (PDF → images → OCR)
  - read_single_paper: Process one paper

Transport: Streamable HTTP (port 8000, endpoint /mcp)
Auth:      Bearer token via MCP_AUTH_TOKEN env var
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from common import BearerAuthMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [paper-to-text] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("paper-to-text")


# ── Configuration ────────────────────────────────────────────────────────────

NEMOTRON_API_URL = os.environ.get(
    "NEMOTRON_PARSE_API_URL",
    "http://nemotron-parse-svc.default.svc.cluster.local:8000/v1",
)
MAX_PAGES_DEFAULT = int(os.environ.get("MAX_PAGES_PER_PAPER", "30"))

# Shared OpenAI client — single connection pool for ALL papers and pages.
# Avoids per-paper client creation overhead and enables connection reuse
# across concurrent OCR requests, maximising burst throughput.
# httpx default pool is 100 connections; bump to 256 so 240 concurrent
# OCR pages (8 papers × 30 pages) never block on connection acquisition.
import openai as _openai_mod
import httpx as _httpx_mod

_parse_client = _openai_mod.AsyncOpenAI(
    base_url=NEMOTRON_API_URL,
    api_key="placeholder",
    max_retries=2,
    timeout=300.0,
    http_client=_httpx_mod.AsyncClient(
        limits=_httpx_mod.Limits(
            max_connections=256,
            max_keepalive_connections=64,
        ),
    ),
)


# ── MCP Server ───────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="Paper to Text",
    instructions=(
        "Convert academic paper PDFs to full text via OCR. "
        "Use read_papers for batch processing or read_single_paper for one paper. "
        "Provide the direct PDF URL and paper title. Pages are OCR'd in batches "
        "of 5 to avoid overloading the service. "
        "This is an EXPENSIVE operation — only use it for highly relevant papers."
    ),
)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


# ── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool
async def read_papers(papers: list[dict]) -> str:
    """Download, render, and OCR a batch of academic papers with Nemotron Parse.

    For each paper, downloads the PDF, renders pages to PNG images, and sends
    them through Nemotron Parse v1.2 for OCR.  All papers and their pages are
    processed concurrently to maximise throughput — Ray Serve autoscaling
    detects the burst and spins up additional replicas.

    This is an expensive (slow) operation — only call it for papers that are
    highly relevant to the research topic.

    Args:
        papers: List of paper objects.  Each must have:
                  - title   (str): Paper title (for tracking).
                  - pdf_url (str): Direct URL to the PDF file.
                Optionally:
                  - max_pages (int): Pages to OCR per paper (1–30, default all).
    """
    if not papers:
        return "[Error: No papers provided.]"

    async def _process_or_error(paper: dict) -> str:
        title = paper.get("title", "Unknown")
        pdf_url = paper.get("pdf_url", "")
        max_pages = min(int(paper.get("max_pages", MAX_PAGES_DEFAULT)), 30)
        if not pdf_url:
            log.warning("[%s] No PDF URL provided", title)
            return f"## {title}\n\n[Error: No PDF URL provided]\n"
        try:
            text = await _process_single_paper(title, pdf_url, max_pages)
            return f"## {title}\n\n{text}\n"
        except Exception as exc:
            log.error("[%s] Failed: %s", title, exc, exc_info=True)
            return f"## {title}\n\n[Error: {exc}]\n"

    log.info("read_papers called with %d papers", len(papers))
    results = await asyncio.gather(*[_process_or_error(p) for p in papers])
    return "\n\n---\n\n".join(results)


@mcp.tool
async def read_single_paper(
    title: str,
    pdf_url: str,
    max_pages: int = 30,
) -> str:
    """Download, render, and OCR a single academic paper with Nemotron Parse.

    Downloads the PDF, renders pages to PNG images, and sends them through
    Nemotron Parse v1.2 for OCR.  Returns the full extracted markdown text.

    Args:
        title:     Paper title (for tracking/display).
        pdf_url:   Direct URL to the PDF file.
        max_pages: Maximum pages to OCR (1–30, default all).
    """
    max_pages = min(max(max_pages, 1), 30)

    if not pdf_url:
        return "[Error: No PDF URL provided]"

    try:
        return await _process_single_paper(title, pdf_url, max_pages)
    except Exception as exc:
        log.error("[%s] read_single_paper failed: %s", title, exc, exc_info=True)
        return f"[Error processing '{title}': {exc}]"


# ── Core PDF → image → OCR logic ─────────────────────────────────────────────

async def _process_single_paper(
    title: str,
    pdf_url: str,
    max_pages: int,
) -> str:
    import httpx

    # 1. Download PDF
    log.info("[%s] Downloading PDF from %s", title, pdf_url)
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as http:
        resp = await http.get(pdf_url)
        resp.raise_for_status()
        pdf_bytes = resp.content
    dl_time = time.monotonic() - t0
    content_type = resp.headers.get("content-type", "unknown")
    log.info(
        "[%s] Downloaded %d bytes in %.1fs (status=%d, content-type=%s)",
        title, len(pdf_bytes), dl_time, resp.status_code, content_type,
    )
    # Detect HTML responses (arXiv rate-limit pages)
    if b"<!DOCTYPE" in pdf_bytes[:200] or b"<html" in pdf_bytes[:200]:
        snippet = pdf_bytes[:500].decode("utf-8", errors="replace")
        log.error(
            "[%s] Received HTML instead of PDF — likely rate-limited. First 500 bytes: %s",
            title, snippet,
        )
        raise ValueError(
            f"Received HTML instead of PDF from {pdf_url} "
            f"(status={resp.status_code}, content-type={content_type}). "
            f"The server may be rate-limiting requests."
        )

    # 2. Render pages to PNG (sync — run in executor)
    log.info("[%s] Rendering PDF pages (max_pages=%d)", title, max_pages)
    t1 = time.monotonic()
    loop = asyncio.get_event_loop()
    page_images = await loop.run_in_executor(
        _pdfium_executor, _render_pdf_pages, pdf_bytes, max_pages,
    )
    render_time = time.monotonic() - t1
    log.info("[%s] Rendered %d pages in %.1fs", title, len(page_images) if page_images else 0, render_time)

    if not page_images:
        return f"[Error: No pages rendered from '{title}']"

    # 3. OCR all pages concurrently across 16 Nemotron Parse replicas

    async def ocr_page(page_idx: int, b64_img: str) -> str:
        log.info("[%s] OCR page %d (%d KB)", title, page_idx + 1, len(b64_img) // 1024)
        t_ocr = time.monotonic()
        ocr_resp = await _parse_client.chat.completions.create(
            model="nvidia/NVIDIA-Nemotron-Parse-v1.2",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "</s><s><predict_bbox><predict_classes>"
                            "<output_markdown><predict_no_text_in_pic>"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64_img}",
                        },
                    },
                ],
            }],
            max_tokens=8000,
            temperature=0.0,
            extra_body={
                "repetition_penalty": 1.1,
                "top_k": 1,
                "skip_special_tokens": False,
            },
        )
        text = ocr_resp.choices[0].message.content or ""
        log.info("[%s] OCR page %d done in %.1fs (%d chars)", title, page_idx + 1, time.monotonic() - t_ocr, len(text))
        return text

    # Fire all pages concurrently — no batching, maximum burst
    log.info("[%s] Starting OCR on %d pages", title, len(page_images))
    t2 = time.monotonic()
    tasks = [asyncio.ensure_future(ocr_page(i, img)) for i, img in enumerate(page_images)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    page_texts: list[str] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            log.error("[%s] OCR page %d failed: %s", title, i + 1, r)
            page_texts.append(f"[OCR failed on page {i + 1}: {r}]")
        else:
            page_texts.append(r)

    total_chars = sum(len(t) for t in page_texts)
    log.info(
        "[%s] OCR complete: %d pages, %d total chars, %.1fs",
        title, len(page_images), total_chars, time.monotonic() - t2,
    )

    full_text = "\n\n---\n\n".join(page_texts)
    return f"Full text of '{title}' ({len(page_images)} pages):\n\n{full_text}"


# PDFium is NOT thread-safe — concurrent PdfDocument() calls from multiple
# threads corrupt the C library's internal state.  Use a ProcessPoolExecutor
# so each worker gets its own process (and therefore its own copy of the C
# library), enabling TRUE parallel rendering without thread-safety issues.
_pdfium_executor = ProcessPoolExecutor(max_workers=4, max_tasks_per_child=50)


def _render_pdf_pages(pdf_bytes: bytes, max_pages: int) -> list[str]:
    """Render PDF pages to base64-encoded PNG images (sync).

    Runs in a separate *process* via ProcessPoolExecutor, so each call has
    its own copy of the PDFium C library — no thread-safety concerns.
    """
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf_bytes)
    n_pages = min(len(doc), max_pages)
    images: list[str] = []

    for page_idx in range(n_pages):
        page = doc[page_idx]
        bitmap = page.render(scale=2.0)
        pil_img = bitmap.to_pil()
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        images.append(base64.b64encode(buf.getvalue()).decode())

    return images


# ── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    token = os.environ.get("MCP_AUTH_TOKEN", "")
    port = int(os.environ.get("MCP_PORT", "8000"))

    app = mcp.http_app()

    if token:
        app = BearerAuthMiddleware(app, token)
        print("[paper-to-text] Bearer token auth enabled")
    else:
        print("[paper-to-text] WARNING: No MCP_AUTH_TOKEN — running without auth")

    print(f"[paper-to-text] Starting on :{port}  (endpoint /mcp)")
    uvicorn.run(app, host="0.0.0.0", port=port)
