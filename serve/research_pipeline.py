"""
Deep Research Agent Pipeline — OpenWebUI
=========================================
requirements: arxiv>=2.1.3, pypdfium2>=4.30.0, openai>=1.40.0, httpx>=0.27.0, Pillow>=10.0.0

Accepts a research topic, finds relevant arXiv papers, uses Nemotron Parse to OCR
each paper's pages in parallel, then synthesises a comprehensive summary with inline
citations using MiniMax M2.5.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
from typing import AsyncGenerator, Iterator, Optional

from pydantic import BaseModel

# Auto-installed by the pipelines server
requirements = [
    "arxiv>=2.1.3",
    "pypdfium2>=4.30.0",
    "openai>=1.40.0",
    "httpx>=0.27.0",
    "Pillow>=10.0.0",
]


class Pipeline:
    """Deep research pipeline: arXiv search → Nemotron Parse OCR → MiniMax synthesis."""

    class Valves(BaseModel):
        # MiniMax M2.5 — direct intra-cluster access (bypasses gateway)
        MINIMAX_API_URL: str = (
            "http://minimax-llm-svc.default.svc.cluster.local:8000/v1"
        )
        MINIMAX_API_KEY: str = os.getenv("OPENAI_API_KEY", "placeholder")

        # Nemotron Parse OCR — load-balanced across 4 replicas
        NEMOTRON_PARSE_API_URL: str = (
            "http://nemotron-parse-svc.default.svc.cluster.local:8000/v1"
        )

        # Tuning
        MAX_PAPERS: int = 15         # Max papers to process per query
        MAX_PAGES_PER_PAPER: int = 6  # Pages to OCR per paper (intro→conclusion)
        ARXIV_POOL: int = 30         # arXiv results to consider before picking top N

    def __init__(self) -> None:
        self.name = "Deep Research Agent"
        # NOTE: Do NOT set self.type = "pipe" — the pipelines server's
        # get_all_pipelines() only handles "manifold" and "filter" types;
        # "pipe" falls through without being registered.  Omitting the
        # attribute lets it land in the catch-all else clause which
        # registers it correctly (and defaults type to "pipe").
        self.valves = self.Valves()

    async def on_startup(self) -> None:
        print("[research_pipeline] Loaded — Deep Research Agent ready.")

    async def on_shutdown(self) -> None:
        pass

    # ── OpenWebUI entry-point ────────────────────────────────────────────────

    def pipe(self, body: dict, __user__: Optional[dict] = None, **kwargs) -> Iterator[str]:
        """Synchronous iterator that drives the async pipeline."""
        messages = body.get("messages", [])
        topic = next(
            (
                m["content"]
                for m in reversed(messages)
                if m.get("role") == "user"
                and isinstance(m.get("content"), str)
                and len(m["content"]) < 2000  # skip injected prompts
                and "follow-up" not in m["content"].lower()[:80]
            ),
            None,
        )
        if not topic:
            yield "Error: no user message found."
            return

        loop = asyncio.new_event_loop()
        async_gen = self._research(topic)
        try:
            while True:
                chunk = loop.run_until_complete(async_gen.__anext__())
                yield chunk
        except StopAsyncIteration:
            pass
        finally:
            loop.close()

    # ── Core async pipeline ──────────────────────────────────────────────────

    async def _research(self, topic: str) -> AsyncGenerator[str, None]:
        import arxiv
        import httpx
        import openai
        import pypdfium2 as pdfium

        v = self.valves

        # ── 1. arXiv search ─────────────────────────────────────────────────
        yield f"## Deep Research: {topic}\n\n"
        yield "**Step 1/3 — Searching arXiv...**\n\n"

        arxiv_client = arxiv.Client()
        search = arxiv.Search(
            query=topic,
            max_results=v.ARXIV_POOL,
            sort_by=arxiv.SortCriterion.Relevance,
        )
        papers = list(arxiv_client.results(search))[: v.MAX_PAPERS]

        if not papers:
            yield f"> No papers found on arXiv for: *{topic}*\n"
            return

        yield f"Found **{len(papers)} papers** (selecting top {v.MAX_PAPERS}):\n\n"
        for i, p in enumerate(papers, 1):
            authors = ", ".join(a.name for a in p.authors[:3])
            if len(p.authors) > 3:
                authors += " et al."
            yield f"{i}. **[{p.title}]({p.entry_id})** — {authors} ({p.published.year})\n"
        yield "\n"

        # ── 2. Sliding-window OCR with Nemotron Parse ────────────────────────
        # Up to OCR_CONCURRENCY requests fly at once.  As the queue builds,
        # Ray Serve autoscaling spins up new replicas — making scaling
        # visibly observable during a demo.
        OCR_CONCURRENCY = 5
        yield "---\n\n**Step 2/3 — Parsing papers with Nemotron Parse OCR...**\n\n"

        parse_client = openai.AsyncOpenAI(
            base_url=v.NEMOTRON_PARSE_API_URL,
            api_key="placeholder",  # vLLM requires a non-empty value
        )

        # Phase 2a: Download all PDFs and render pages to base64 images
        async def download_and_render(paper: arxiv.Result, idx: int) -> dict:
            """Download PDF and render pages to base64 PNG images."""
            try:
                async with httpx.AsyncClient(
                    timeout=120.0, follow_redirects=True
                ) as http:
                    pdf_resp = await http.get(paper.pdf_url)
                    pdf_resp.raise_for_status()
                    pdf_bytes = pdf_resp.content

                doc = pdfium.PdfDocument(pdf_bytes)
                n_pages = min(len(doc), v.MAX_PAGES_PER_PAPER)
                page_images: list[str] = []

                for page_idx in range(n_pages):
                    page = doc[page_idx]
                    bitmap = page.render(scale=2.0)
                    pil_img = bitmap.to_pil()
                    buf = io.BytesIO()
                    pil_img.save(buf, format="PNG")
                    page_images.append(base64.b64encode(buf.getvalue()).decode())

                return {"paper": paper, "idx": idx, "pages": page_images, "error": None}
            except Exception as exc:
                return {"paper": paper, "idx": idx, "pages": [], "error": str(exc)}

        yield "Downloading & rendering PDFs...\n\n"

        download_tasks = [
            asyncio.ensure_future(download_and_render(p, i))
            for i, p in enumerate(papers, 1)
        ]
        rendered: list[dict] = []
        for coro in asyncio.as_completed(download_tasks):
            result = await coro
            rendered.append(result)
            if result["error"]:
                yield f"  ⚠ Paper [{result['idx']}] — download failed: {result['error']}\n"
            else:
                yield f"  📄 Paper [{result['idx']}] — {len(result['pages'])} pages rendered\n"
        rendered.sort(key=lambda r: r["idx"])

        total_pages = sum(len(r["pages"]) for r in rendered)
        yield f"\nDownloaded & rendered **{total_pages}** pages across {len(papers)} papers.\n\n"
        yield f"Sending pages to Nemotron Parse ({OCR_CONCURRENCY} at a time)...\n\n"

        # Phase 2b: OCR helper
        async def ocr_page(b64_img: str) -> str:
            """OCR a single page image via Nemotron Parse."""
            ocr_prompt = (
                "</s><s><predict_bbox><predict_classes>"
                "<output_markdown><predict_no_text_in_pic>"
            )
            resp = await parse_client.chat.completions.create(
                model="nvidia/NVIDIA-Nemotron-Parse-v1.2",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": ocr_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{b64_img}"
                                },
                            },
                        ],
                    }
                ],
                max_tokens=8000,
                temperature=0.0,
                extra_body={
                    "repetition_penalty": 1.1,
                    "top_k": 1,
                    "skip_special_tokens": False,
                },
            )
            return resp.choices[0].message.content or ""

        # ── Sliding-window OCR: up to OCR_CONCURRENCY at a time ─────────
        sem = asyncio.Semaphore(OCR_CONCURRENCY)
        paper_page_texts: dict[int, list[tuple[int, str]]] = {}
        succeeded = 0
        completed = 0

        # Build flat list of (paper_idx, page_idx, base64_img)
        flat_pages: list[tuple[int, int, str]] = []
        for r in rendered:
            for page_idx, b64_img in enumerate(r["pages"]):
                flat_pages.append((r["idx"], page_idx, b64_img))

        async def bounded_ocr(paper_idx: int, page_idx: int, b64_img: str) -> tuple[int, int, str]:
            async with sem:
                try:
                    text = await ocr_page(b64_img)
                except Exception as exc:
                    text = f"[OCR error: {exc}]"
                return (paper_idx, page_idx, text)

        # Stream progress as tasks complete
        tasks = [
            asyncio.ensure_future(bounded_ocr(pi, pg, img))
            for pi, pg, img in flat_pages
        ]
        for coro in asyncio.as_completed(tasks):
            paper_idx, page_idx, text = await coro
            completed += 1
            if not text.startswith("[OCR error"):
                succeeded += 1
            paper_page_texts.setdefault(paper_idx, []).append((page_idx, text))
            yield f"  ✓ Page {completed}/{total_pages} (paper {paper_idx}, p{page_idx + 1})\n"

        # Sort pages within each paper and build final records
        parsed: list[dict] = []
        for r in rendered:
            page_entries = paper_page_texts.get(r["idx"], [])
            page_entries.sort(key=lambda x: x[0])
            if r["error"] and not page_entries:
                full_text = f"[Download failed: {r['error']}. Using abstract.]\n\n{r['paper'].summary}"
            else:
                full_text = "\n\n".join(text for _, text in page_entries)
            parsed.append(_paper_record(r["paper"], full_text, r["idx"]))

        yield f"\nOCR complete — **{succeeded}/{total_pages}** pages parsed successfully.\n\n"

        # ── 3. Synthesis with MiniMax M2.5 ───────────────────────────────────
        yield "---\n\n**Step 3/3 — Synthesising with MiniMax M2.5...**\n\n---\n\n"

        papers_ctx = _build_context(parsed)

        system_prompt = (
            "You are a world-class research assistant. "
            "IMPORTANT: You MUST write your ENTIRE response exclusively in English — "
            "including all internal reasoning, analysis, and thinking. "
            "Never switch to Chinese, Japanese, or any other non-English language.\n\n"
            "Given a research topic and excerpts from parsed academic papers, "
            "write a deep, well-structured research synthesis. Follow these rules:\n"
            "1. Use inline citation numbers, e.g. [1], [2], after every factual claim.\n"
            "2. Organise the summary with clear Markdown headers: "
            "Background, Key Findings, Methodology, Open Questions, Conclusion.\n"
            "3. End with a '## References' section listing each paper as:\n"
            "   [N] Author et al. (Year). *Title*. <URL>\n"
            "4. Be precise, insightful, and avoid padding.\n"
            "5. Highlight points of agreement and disagreement across papers."
        )

        user_prompt = (
            f"**Research topic:** {topic}\n\n"
            f"**Parsed papers (OCR-extracted text):**\n\n{papers_ctx}\n\n"
            "Please write the synthesis now."
        )

        minimax_client = openai.AsyncOpenAI(
            base_url=v.MINIMAX_API_URL,
            api_key=v.MINIMAX_API_KEY,
        )

        stream = await minimax_client.chat.completions.create(
            model="minimax-m2.5",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            top_p=0.95,
            stream=True,
        )

        async for chunk in stream:
            delta = (
                chunk.choices[0].delta.content if chunk.choices else None
            )
            if delta:
                yield delta


# ── Helpers ──────────────────────────────────────────────────────────────────


def _paper_record(paper, text: str, idx: int) -> dict:
    authors = [a.name for a in paper.authors]
    short_authors = ", ".join(authors[:3])
    if len(authors) > 3:
        short_authors += " et al."
    return {
        "idx": idx,
        "title": paper.title,
        "url": paper.entry_id,
        "authors": short_authors,
        "year": paper.published.year,
        "text": text,
    }


def _build_context(parsed: list[dict], chars_per_paper: int = 8_000) -> str:
    parts: list[str] = []
    for r in parsed:
        parts.append(
            f"=== Paper [{r['idx']}] ===\n"
            f"Title: {r['title']}\n"
            f"Authors: {r['authors']}\n"
            f"Year: {r['year']}\n"
            f"URL: {r['url']}\n\n"
            f"{r['text'][:chars_per_paper]}"
        )
    return "\n\n".join(parts)
