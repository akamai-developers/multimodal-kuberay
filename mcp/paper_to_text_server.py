"""
Paper-to-Text MCP Server
==========================
requirements: fastmcp>=3.0.0, httpx>=0.27.0, pypdfium2>=4.30.0, openai>=1.40.0, Pillow>=10.0.0, uvicorn>=0.30.0

OCR academic papers: download PDF → render pages to PNG → OCR with Nemotron Parse.
Pages are sent to OCR in batches of PAGE_BATCH_SIZE (default 5) to avoid
overwhelming the Nemotron Parse endpoint.

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
import os

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse, JSONResponse


# ── Configuration ────────────────────────────────────────────────────────────

NEMOTRON_API_URL = os.environ.get(
    "NEMOTRON_PARSE_API_URL",
    "http://nemotron-parse-svc.default.svc.cluster.local:8000/v1",
)
PAGE_BATCH_SIZE = int(os.environ.get("PAGE_BATCH_SIZE", "5"))
MAX_PAGES_DEFAULT = int(os.environ.get("MAX_PAGES_PER_PAPER", "6"))


# ── Auth middleware ───────────────────────────────────────────────────────────

class _BearerAuthMiddleware:
    """ASGI middleware that validates Bearer token on all requests except /health."""

    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path != "/health":
                headers = dict(scope.get("headers", []))
                auth = headers.get(b"authorization", b"").decode()
                if auth != f"Bearer {self.token}":
                    response = JSONResponse(
                        {"error": "Unauthorized"}, status_code=401,
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


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
    them through Nemotron Parse v1.2 for OCR.  Pages are processed in batches
    of 5 at a time to avoid overloading the OCR service.  Returns the full
    extracted markdown text for every paper.

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

    results: list[str] = []
    for paper in papers:
        title = paper.get("title", "Unknown")
        pdf_url = paper.get("pdf_url", "")
        max_pages = min(int(paper.get("max_pages", MAX_PAGES_DEFAULT)), 30)

        if not pdf_url:
            results.append(f"## {title}\n\n[Error: No PDF URL provided]\n")
            continue

        try:
            text = await _process_single_paper(title, pdf_url, max_pages)
            results.append(f"## {title}\n\n{text}\n")
        except Exception as exc:
            results.append(f"## {title}\n\n[Error: {exc}]\n")

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
        return f"[Error processing '{title}': {exc}]"


# ── Core PDF → image → OCR logic ─────────────────────────────────────────────

async def _process_single_paper(
    title: str,
    pdf_url: str,
    max_pages: int,
) -> str:
    import httpx
    import openai

    # 1. Download PDF
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as http:
        resp = await http.get(pdf_url)
        resp.raise_for_status()
        pdf_bytes = resp.content

    # 2. Render pages to PNG (sync — run in executor)
    loop = asyncio.get_event_loop()
    page_images = await loop.run_in_executor(
        None, _render_pdf_pages, pdf_bytes, max_pages,
    )

    if not page_images:
        return f"[Error: No pages rendered from '{title}']"

    # 3. OCR each page with Nemotron Parse — batched PAGE_BATCH_SIZE pages at a time
    parse_client = openai.AsyncOpenAI(
        base_url=NEMOTRON_API_URL,
        api_key="placeholder",
    )

    async def ocr_page(b64_img: str) -> str:
        ocr_resp = await parse_client.chat.completions.create(
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
        return ocr_resp.choices[0].message.content or ""

    # Process pages in explicit batches of PAGE_BATCH_SIZE
    page_texts: list[str] = [""] * len(page_images)
    for batch_start in range(0, len(page_images), PAGE_BATCH_SIZE):
        batch_end = min(batch_start + PAGE_BATCH_SIZE, len(page_images))
        batch = page_images[batch_start:batch_end]

        tasks = [asyncio.ensure_future(ocr_page(img)) for img in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, r in enumerate(results):
            idx = batch_start + i
            if isinstance(r, Exception):
                page_texts[idx] = f"[OCR failed on page {idx + 1}: {r}]"
            else:
                page_texts[idx] = r

    full_text = "\n\n---\n\n".join(page_texts)
    return f"Full text of '{title}' ({len(page_images)} pages):\n\n{full_text}"


def _render_pdf_pages(pdf_bytes: bytes, max_pages: int) -> list[str]:
    """Render PDF pages to base64-encoded PNG images (sync)."""
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
        app = _BearerAuthMiddleware(app, token)
        print("[paper-to-text] Bearer token auth enabled")
    else:
        print("[paper-to-text] WARNING: No MCP_AUTH_TOKEN — running without auth")

    print(f"[paper-to-text] Starting on :{port}  (endpoint /mcp)")
    uvicorn.run(app, host="0.0.0.0", port=port)
