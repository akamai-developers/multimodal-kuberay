"""
ArXiv Search MCP Server
========================
requirements: fastmcp>=3.0.0, httpx>=0.27.0, arxiv>=2.1.0, uvicorn>=0.30.0

Exposes arXiv paper search as MCP tools for LLM-driven research workflows.

Tools:
  - search_arxiv:    Search arXiv for academic papers matching a query
  - get_paper_info:  Get detailed metadata for a specific arXiv paper

Transport: Streamable HTTP (port 8000, endpoint /mcp)
Auth:      Bearer token via MCP_AUTH_TOKEN env var
"""

from __future__ import annotations

import asyncio
import os
import time

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse, JSONResponse


# ── Rate limiter ─────────────────────────────────────────────────────────────
# arXiv API allows ~1 request per 3 seconds.  We enforce a minimum gap.

ARXIV_MIN_INTERVAL = float(os.environ.get("ARXIV_MIN_INTERVAL", "3.0"))
ARXIV_MAX_RETRIES = int(os.environ.get("ARXIV_MAX_RETRIES", "4"))
ARXIV_RETRY_BACKOFF = float(os.environ.get("ARXIV_RETRY_BACKOFF", "5.0"))

_last_request: float = 0.0
_rate_lock: asyncio.Lock | None = None


async def _get_rate_lock() -> asyncio.Lock:
    global _rate_lock
    if _rate_lock is None:
        _rate_lock = asyncio.Lock()
    return _rate_lock


async def _rate_limited_arxiv_call(fn):
    """Run a synchronous arxiv call with rate limiting and retries."""
    global _last_request
    lock = await _get_rate_lock()
    loop = asyncio.get_event_loop()
    last_exc = None

    for attempt in range(ARXIV_MAX_RETRIES + 1):
        async with lock:
            now = time.monotonic()
            wait = ARXIV_MIN_INTERVAL - (now - _last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            _last_request = time.monotonic()

        try:
            return await loop.run_in_executor(None, fn)
        except Exception as exc:
            last_exc = exc
            # Check if it's a 429
            if "429" in str(exc):
                backoff = ARXIV_RETRY_BACKOFF * (2 ** attempt)
                await asyncio.sleep(backoff)
                continue
            raise

    raise last_exc or RuntimeError("arXiv request failed after retries")


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
    name="ArXiv Search",
    instructions=(
        "Search arXiv for academic papers. Use search_arxiv with specific, "
        "academic queries to find relevant papers. Use get_paper_info to get "
        "detailed metadata for a specific paper by its arXiv ID."
    ),
)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


# ── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool
async def search_arxiv(query: str, max_results: int = 10) -> str:
    """Search arXiv for academic papers matching a query.

    Returns metadata for each hit: title, authors, abstract, year, PDF URL,
    and arXiv categories.  Use specific, academic queries for best results.
    Issue multiple diverse queries to explore different angles of a topic.

    Args:
        query: Search query — be specific and academic.
        max_results: Maximum number of papers to return (1-50, default 10).
    """
    import arxiv

    max_results = min(max(max_results, 1), 50)

    client = arxiv.Client(page_size=max_results, delay_seconds=1.5, num_retries=3)
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )

    results = await _rate_limited_arxiv_call(lambda: list(client.results(search)))

    if not results:
        return "No papers found for this query."

    lines = [f"Found {len(results)} papers:\n"]
    for i, paper in enumerate(results, 1):
        authors = ", ".join(str(a) for a in paper.authors[:3])
        if len(paper.authors) > 3:
            authors += " et al."
        year = paper.published.year if paper.published else "?"
        abstract = (paper.summary or "No abstract.").replace("\n", " ")
        categories = ", ".join(paper.categories[:3]) if paper.categories else "N/A"

        lines.append(
            f"{i}. **{paper.title}**\n"
            f"   arXiv ID: {paper.entry_id}\n"
            f"   Authors: {authors} ({year})\n"
            f"   Categories: {categories}\n"
            f"   PDF: {paper.pdf_url}\n"
            f"   Abstract: {abstract}\n"
        )

    return "\n".join(lines)


@mcp.tool
async def get_paper_info(arxiv_id: str) -> str:
    """Get detailed metadata for a specific arXiv paper by its ID.

    Useful for getting the full abstract and metadata of a paper you found
    via search or citation.

    Args:
        arxiv_id: arXiv paper ID (e.g. '2301.00001') or full arXiv URL.
    """
    import arxiv

    # Extract ID from URL if needed
    if "arxiv.org" in arxiv_id:
        arxiv_id = arxiv_id.rstrip("/").split("/")[-1]

    search = arxiv.Search(id_list=[arxiv_id])
    client = arxiv.Client(page_size=5, delay_seconds=3.0, num_retries=3)

    results = await _rate_limited_arxiv_call(lambda: list(client.results(search)))

    if not results:
        return f"No paper found with ID: {arxiv_id}"

    paper = results[0]
    authors = ", ".join(str(a) for a in paper.authors)
    categories = ", ".join(paper.categories) if paper.categories else "N/A"

    return (
        f"**{paper.title}**\n\n"
        f"Authors: {authors}\n"
        f"Published: {paper.published}\n"
        f"Updated: {paper.updated}\n"
        f"Categories: {categories}\n"
        f"PDF: {paper.pdf_url}\n"
        f"arXiv URL: {paper.entry_id}\n\n"
        f"Abstract:\n{paper.summary}\n"
    )


# ── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    token = os.environ.get("MCP_AUTH_TOKEN", "")
    port = int(os.environ.get("MCP_PORT", "8000"))

    app = mcp.http_app()

    if token:
        app = _BearerAuthMiddleware(app, token)
        print("[arxiv-search] Bearer token auth enabled")
    else:
        print("[arxiv-search] WARNING: No MCP_AUTH_TOKEN — running without auth")

    print(f"[arxiv-search] Starting on :{port}  (endpoint /mcp)")
    uvicorn.run(app, host="0.0.0.0", port=port)
