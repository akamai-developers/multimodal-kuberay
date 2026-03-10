"""
Deep Research Agent Pipeline — OpenWebUI
==========================================
requirements: httpx>=0.27.0, openai>=1.40.0

Two-phase deep-research pipeline:
  Phase 1 — Search & Select (arXiv tools only, fast)
  Phase 2 — Read & Synthesize (OCR tools only, then write report)

MCP Servers:
  - ArXiv Search:    search_arxiv, get_paper_info
  - Paper to Text:   read_papers, read_single_paper
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import threading
import time
from typing import AsyncGenerator, Iterator, Optional

from pydantic import BaseModel

requirements = [
    "httpx>=0.27.0",
    "openai>=1.40.0",
]


# ── Lightweight MCP Client (JSON-RPC 2.0 over streamable HTTP) ───────────────

class _MCPClient:
    """Minimal MCP client for streamable HTTP transport."""

    def __init__(self, name: str, base_url: str, auth_token: str = ""):
        self.name = name
        self.url = base_url.rstrip("/")
        self.auth_token = auth_token
        self._session_id: str | None = None
        self._req_id = 0
        self._tools: list[dict] = []
        self._tool_names: set[str] = set()

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _headers(self) -> dict:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.auth_token:
            h["Authorization"] = f"Bearer {self.auth_token}"
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    async def _rpc(self, http, method: str, params: dict | None = None) -> dict:
        body: dict = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
        }
        if params is not None:
            body["params"] = params

        resp = await http.post(self.url, json=body, headers=self._headers())
        resp.raise_for_status()

        sid = resp.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid

        ct = resp.headers.get("content-type", "")
        if "text/event-stream" in ct:
            return self._parse_sse(resp.text)

        text = resp.text.strip()
        if not text:
            return {}
        return resp.json()

    async def _notify(self, http, method: str, params: dict | None = None) -> None:
        body: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        try:
            await http.post(self.url, json=body, headers=self._headers())
        except Exception:
            pass

    @staticmethod
    def _parse_sse(text: str) -> dict:
        last: dict = {}
        for line in text.splitlines():
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    if isinstance(data, dict) and "jsonrpc" in data:
                        last = data
                except json.JSONDecodeError:
                    continue
        return last

    async def initialize(self, http) -> None:
        await self._rpc(http, "initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "mcp-research-pipeline", "version": "1.0.0"},
        })
        await self._notify(http, "notifications/initialized")

    async def list_tools(self, http) -> list[dict]:
        result = await self._rpc(http, "tools/list")
        self._tools = result.get("result", {}).get("tools", [])
        self._tool_names = {t["name"] for t in self._tools}
        return self._tools

    async def call_tool(self, http, name: str, arguments: dict) -> str:
        result = await self._rpc(http, "tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if "error" in result:
            err = result["error"]
            return f"[MCP Error: {err.get('message', 'unknown')}]"
        content = result.get("result", {}).get("content", [])
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts) if texts else str(content)


# ── MCP → OpenAI tool schema conversion ──────────────────────────────────────

def _mcp_tools_to_openai(mcp_tools: list[dict]) -> list[dict]:
    openai_tools = []
    for tool in mcp_tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get(
                    "inputSchema",
                    {"type": "object", "properties": {}},
                ),
            },
        })
    return openai_tools


# ── System prompts ───────────────────────────────────────────────────────────

PHASE1_PROMPT = """\
You are a research agent in PHASE 1: SEARCH & SELECT.

You have access to arXiv search tools ONLY. Your goal is to find the most \
relevant papers for the user's topic and select 6-8 key papers for deep reading. \
Every selected paper will be fully OCR'd (all pages), so be selective.

## Instructions

1. Issue 2-3 focused search queries (max_results=20 each) covering the most \
   important angles of the topic.
2. Review the returned titles, abstracts, authors, and years.
3. Once you have identified the best 6-8 papers, produce your SELECTION as \
   your final text response (no more tool calls). Use EXACTLY this format:

## Selected Papers

1. **Paper Title** — arXiv ID: XXXX.XXXXX — PDF: https://arxiv.org/pdf/...
   Relevance: (one sentence explaining why this paper matters for the topic)

2. **Paper Title** — arXiv ID: XXXX.XXXXX — PDF: https://arxiv.org/pdf/...
   Relevance: (one sentence)

...

## Rules
- ALWAYS respond in English.
- Do NOT call any OCR or paper-reading tools — they are not available yet.
- Do NOT call get_paper_info — the search results already contain abstracts.
- Select exactly 6-8 papers. Focus on the most relevant and influential ones.
- Use max_results=20 for each query to get broad coverage.
- After your search queries, output your selection IMMEDIATELY — do NOT call \
  more tools. You have a STRICT limit of 6 tool calls total.
- NEVER output tool calls as XML text. Use the function calling interface.
"""

PHASE2_PROMPT = """\
You are a research agent in PHASE 2: READ & SYNTHESIZE.

You have already selected papers in Phase 1. Now you have access to OCR tools \
to read those papers, plus the search results context from Phase 1.

## Instructions

1. Call `read_papers` ONCE with ALL the selected papers to batch-read them.
   Include every paper from the Phase 1 selection — do not skip any.
2. After receiving the extracted text, write a comprehensive research synthesis.

## Report format

Write in Markdown with these sections:
- **Background** — Context and motivation
- **Key Findings** — Main results across papers, with inline citations [1], [2]
- **Methodology** — How key studies were conducted
- **Open Questions** — Gaps and future directions
- **Conclusion** — Summary of the state of the field
- **References** — Numbered list: [N] Author et al. (Year). *Title*. URL

## Rules
- ALWAYS respond in English — never switch languages.
- Use inline citations [N] for every factual claim.
- Be precise, be thorough, highlight disagreements across papers.
- Call `read_papers` ONCE with ALL papers in a single batch.
- Do NOT use read_single_paper — always batch with read_papers.
- The returned text may be condensed per paper — work with what you receive.
  Do NOT re-read papers individually if the text was condensed.
- After reading, write the report immediately — no more tool calls.
"""


# ── Pipeline ─────────────────────────────────────────────────────────────────

class Pipeline:
    """Two-phase deep research pipeline backed by MCP tool servers.

    Phase 1 — Search & Select (arXiv tools only, max 6 turns)
    Phase 2 — Read & Synthesize (OCR tools only, max 3 turns)
    """

    class Valves(BaseModel):
        MINIMAX_API_URL: str = (
            "http://minimax-llm-svc.default.svc.cluster.local:8000/v1"
        )
        MINIMAX_API_KEY: str = os.getenv("OPENAI_API_KEY", "placeholder")
        ARXIV_MCP_URL: str = os.getenv(
            "ARXIV_MCP_URL",
            "http://mcp-arxiv-search-svc.default.svc.cluster.local:8000/mcp",
        )
        PAPER_MCP_URL: str = os.getenv(
            "PAPER_MCP_URL",
            "http://mcp-paper-to-text-svc.default.svc.cluster.local:8000/mcp",
        )
        MCP_AUTH_TOKEN: str = os.getenv("MCP_AUTH_TOKEN", "")

        MAX_SEARCH_TURNS: int = 6       # Phase 1 cap (2-3 queries)
        MAX_READ_TURNS: int = 3         # Phase 2 cap
        MCP_TIMEOUT: float = 900.0      # HTTP timeout for MCP calls
        OCR_RESULT_MAX_CHARS: int = 120000  # Max chars for OCR tool results (~30K tokens)
        SEARCH_RESULT_MAX_CHARS: int = 12000  # Max chars for search tool results

    def __init__(self) -> None:
        self.name = "Deep Research Agent"
        self.valves = self.Valves()

    async def on_startup(self) -> None:
        print("[mcp_research_pipeline] Loaded — Deep Research Agent ready.")

    async def on_shutdown(self) -> None:
        pass

    # ── Inlet filter — force streaming so UI updates in real-time ────────

    async def inlet(self, body: dict, __user__: dict | None = None) -> dict:
        old = body.get("stream", "MISSING")
        body["stream"] = True
        if old is not True:
            print(f"[mcp_research_pipeline] inlet: stream {old} -> True "
                  f"(user={(__user__ or {}).get('name', 'unknown')})")
        return body

    # ── OpenWebUI entry-point ────────────────────────────────────────────

    def pipe(
        self, body: dict, __user__: Optional[dict] = None, **kwargs,
    ) -> Iterator[str]:
        stream_flag = body.get("stream", "MISSING")
        print(
            f"[mcp_research_pipeline] pipe called, "
            f"stream={stream_flag}, "
            f"user={(__user__ or {}).get('name', 'unknown')}"
        )
        messages = body.get("messages", [])
        topic = next(
            (
                m["content"]
                for m in reversed(messages)
                if m.get("role") == "user"
                and isinstance(m.get("content"), str)
                and len(m["content"]) < 2000
            ),
            None,
        )
        if not topic:
            yield "Error: no user message found."
            return

        # Queue-based async bridge: the event loop runs continuously in a
        # background thread so incoming LLM/MCP data is processed in
        # real-time instead of being paused between yields.
        q: queue.Queue[str | None] = queue.Queue()

        def _run() -> None:
            async def _produce() -> None:
                try:
                    async for chunk in self._agent_loop(topic):
                        q.put(chunk)
                except Exception as exc:
                    q.put(f"\n\n> ⚠ Pipeline error: {exc}\n")
                finally:
                    q.put(None)  # sentinel

            asyncio.run(_produce())

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        while True:
            item = q.get()
            if item is None:
                break
            yield item

        thread.join()

    # ── Core two-phase agentic loop ──────────────────────────────────────

    async def _agent_loop(self, topic: str) -> AsyncGenerator[str, None]:
        import httpx
        import openai

        v = self.valves
        t0 = time.time()

        yield f"## Deep Research: {topic}\n\n"
        yield "_Connecting to MCP tool servers..._\n\n"

        arxiv_mcp = _MCPClient("arxiv-search", v.ARXIV_MCP_URL, v.MCP_AUTH_TOKEN)
        paper_mcp = _MCPClient("paper-to-text", v.PAPER_MCP_URL, v.MCP_AUTH_TOKEN)

        arxiv_router: dict[str, _MCPClient] = {}
        arxiv_tools: list[dict] = []
        paper_router: dict[str, _MCPClient] = {}
        paper_tools: list[dict] = []

        async with httpx.AsyncClient(timeout=v.MCP_TIMEOUT) as http:
            # ── Discover tools ───────────────────────────────────────
            for label, client, router, tool_list in [
                ("ArXiv Search", arxiv_mcp, arxiv_router, arxiv_tools),
                ("Paper to Text", paper_mcp, paper_router, paper_tools),
            ]:
                try:
                    await client.initialize(http)
                    tools = await client.list_tools(http)
                    for t in tools:
                        router[t["name"]] = client
                    tool_list.extend(_mcp_tools_to_openai(tools))
                    names = ", ".join(t["name"] for t in tools)
                    yield f"✓ **{label}**: {names}\n"
                except Exception as exc:
                    yield f"⚠ **{label}** unavailable: {exc}\n"

            if not arxiv_tools:
                yield "\n**Error: ArXiv tools unavailable. Cannot proceed.**\n"
                return

            total = len(arxiv_tools) + len(paper_tools)
            yield f"\n_Discovered {total} tools across 2 servers._\n\n"

            minimax = openai.AsyncOpenAI(
                base_url=v.MINIMAX_API_URL,
                api_key=v.MINIMAX_API_KEY,
            )

            # ═════════════════════════════════════════════════════════
            # PHASE 1: SEARCH & SELECT
            # ═════════════════════════════════════════════════════════
            yield "## Phase 1: Search & Select\n\n"
            yield "_Searching for relevant papers (arXiv tools only)..._\n\n---\n\n"

            p1_msgs: list[dict] = [
                {"role": "system", "content": PHASE1_PROMPT},
                {"role": "user", "content": (
                    f"Research this topic and select the best papers: {topic}"
                )},
            ]

            phase1_output = ""
            phase1_streamed = False
            for turn in range(v.MAX_SEARCH_TURNS):
                result = _TurnResult()
                async for chunk in _run_turn(
                    minimax, p1_msgs, arxiv_tools, arxiv_router,
                    http, turn, "Phase 1",
                    max_tokens=4096,  # Fast: just tool calls + selection
                    valves=v,
                ):
                    if chunk.text:
                        yield chunk.text
                    if chunk.result:
                        result = chunk.result

                if not result.had_tool_calls:
                    phase1_output = result.content
                    phase1_streamed = result.streamed
                    break
            else:
                yield "_Phase 1 turn limit reached. Requesting selection..._\n\n"
                p1_msgs.append({
                    "role": "user",
                    "content": (
                        "STOP. Tools are no longer available. Do NOT output any "
                        "tool calls, XML, or invoke tags. Output ONLY your "
                        "selected papers list in Markdown NOW."
                    ),
                })
                async for delta in _stream_response(minimax, p1_msgs):
                    phase1_output += delta
                    yield delta
                phase1_output = _strip_xml_tool_calls(phase1_output)
                phase1_streamed = True

            elapsed_p1 = time.time() - t0
            yield f"\n**Phase 1 complete ({elapsed_p1:.0f}s)**\n\n"
            if phase1_output and not phase1_streamed:
                yield phase1_output + "\n\n"

            # ── Parse selected papers ────────────────────────────────
            selected = _parse_selected_papers(phase1_output)

            if not selected or not paper_tools:
                if not selected:
                    yield "⚠ _Could not parse paper selections._\n\n"
                else:
                    yield "⚠ _OCR tools unavailable._\n\n"
                yield "_Writing synthesis from abstracts only..._\n\n"
                synth = ""
                async for delta in _stream_response(minimax, [
                    {"role": "system", "content": PHASE2_PROMPT},
                    {"role": "user", "content": (
                        f"Topic: {topic}\n\n"
                        f"You only have abstracts (no full text). "
                        f"Write the best synthesis you can:\n\n{phase1_output}"
                    )},
                ]):
                    synth += delta
                    yield delta
                elapsed = time.time() - t0
                yield (
                    f"\n\n---\n\n_Research completed in {elapsed:.0f}s_"
                    f"\n\n---\n\n"
                )
                if not synth:
                    yield "_No output._\n"
                return

            # ═════════════════════════════════════════════════════════
            # PHASE 2: READ & SYNTHESIZE
            # ═════════════════════════════════════════════════════════
            yield "---\n\n## Phase 2: Read & Synthesize\n\n"
            paper_list = ", ".join(
                p["title"][:50] for p in selected[:5]
            )
            yield (
                f"_Reading {len(selected)} papers via OCR: "
                f"{paper_list}_\n\n---\n\n"
            )

            p2_msgs: list[dict] = [
                {"role": "system", "content": PHASE2_PROMPT},
                {"role": "user", "content": (
                    f"Topic: {topic}\n\n"
                    f"## Papers selected in Phase 1:\n\n{phase1_output}\n\n"
                    "Now call `read_papers` with these papers, then write "
                    "the synthesis."
                )},
            ]

            phase2_output = ""
            phase2_streamed = False
            for turn in range(v.MAX_READ_TURNS):
                result = _TurnResult()
                async for chunk in _run_turn(
                    minimax, p2_msgs, paper_tools, paper_router,
                    http, turn, "Phase 2",
                    valves=v,
                ):
                    if chunk.text:
                        yield chunk.text
                    if chunk.result:
                        result = chunk.result

                if not result.had_tool_calls:
                    phase2_output = result.content
                    phase2_streamed = result.streamed
                    break
            else:
                yield (
                    "_Phase 2 turn limit reached. "
                    "Requesting synthesis..._\n\n"
                )
                p2_msgs.append({
                    "role": "user",
                    "content": (
                        "STOP. Tools are no longer available. Do NOT output any "
                        "tool calls, XML, or invoke tags. Write the final "
                        "research synthesis in Markdown NOW."
                    ),
                })
                async for delta in _stream_response(minimax, p2_msgs):
                    phase2_output += delta
                    yield delta
                phase2_streamed = True

            elapsed = time.time() - t0
            yield (
                f"\n\n---\n\n_Research completed in {elapsed:.0f}s_"
                f"\n\n---\n\n"
            )
            if not phase2_streamed:
                yield (
                    phase2_output
                    if phase2_output
                    else "_No synthesis output._\n"
                )


# ── Turn infrastructure ──────────────────────────────────────────────────────

class _TurnResult:
    """Result of a single agentic turn."""

    def __init__(
        self, content: str = "", had_tool_calls: bool = False,
        streamed: bool = False,
    ):
        self.content = content
        self.had_tool_calls = had_tool_calls
        self.streamed = streamed  # True if content was already yielded to UI


class _TurnChunk:
    """A UI text chunk and/or a turn result."""

    def __init__(
        self,
        text: str | None = None,
        result: _TurnResult | None = None,
    ):
        self.text = text
        self.result = result


async def _run_turn(
    minimax, messages, tools, tool_router, http, turn, phase_label,
    max_tokens: int = 16384,
    valves=None,
) -> AsyncGenerator[_TurnChunk, None]:
    """Execute one agentic turn.  Yields UI text chunks and a final result."""

    yield _TurnChunk(
        text=f"_⏳ {phase_label} — thinking (turn {turn + 1})..._\n\n",
    )

    collected_content = ""
    collected_tool_calls: list[dict] = []
    finish_reason = None
    saw_any_tool_call = False
    streamed_partial = False  # True if content was yielded before tool calls
    think_filter = _ThinkFilter()
    rep_detector = _RepetitionDetector()

    try:
        stream = await minimax.chat.completions.create(
            model="minimax-m2.5",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.4,
            frequency_penalty=0.3,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            finish_reason = (
                chunk.choices[0].finish_reason or finish_reason
            )

            if delta.content:
                collected_content += delta.content
                rep_detector.feed(delta.content)
                if rep_detector.is_degenerate():
                    print(f"[mcp_research_pipeline] Repetition detected in {phase_label}, aborting generation")
                    yield _TurnChunk(text="\n\n_[Generation stopped — repetition detected]_\n\n")
                    break
                # Stream content to UI immediately once we know
                # this isn't a tool-calling turn
                if not saw_any_tool_call:
                    clean = think_filter.feed(delta.content)
                    if clean:
                        yield _TurnChunk(text=clean)
                    streamed_partial = True

            if delta.tool_calls:
                saw_any_tool_call = True
                for tc in delta.tool_calls:
                    idx = tc.index
                    while idx >= len(collected_tool_calls):
                        collected_tool_calls.append({
                            "id": "",
                            "name": "",
                            "arguments": "",
                        })
                    if tc.id:
                        collected_tool_calls[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            collected_tool_calls[idx]["name"] += (
                                tc.function.name
                            )
                        if tc.function.arguments:
                            collected_tool_calls[idx]["arguments"] += (
                                tc.function.arguments
                            )

    except Exception as exc:
        yield _TurnChunk(text=f"\n\n> ⚠ Agent error: {exc}\n\n")
        yield _TurnChunk(result=_TurnResult("", False))
        return

    has_tool_calls = (
        bool(collected_tool_calls) and finish_reason == "tool_calls"
    )

    # Detect XML tool calls emitted as text (MiniMax quirk)
    # e.g. <invoke name="search_arxiv"><parameter name="query">...</parameter></invoke>
    if not has_tool_calls and collected_content:
        xml_pattern = re.search(
            r'<invoke\s+name="(\w+)">(.*?)</invoke>',
            collected_content,
            re.DOTALL,
        )
        if xml_pattern:
            fn_name = xml_pattern.group(1)
            # Parse <parameter name="key">value</parameter> pairs
            params = dict(re.findall(
                r'<parameter\s+name="(\w+)">(.*?)</parameter>',
                xml_pattern.group(2),
                re.DOTALL,
            ))
            # Convert numeric strings
            for k, v in params.items():
                try:
                    params[k] = int(v)
                except (ValueError, TypeError):
                    pass

            # Check if this tool exists in our router
            if fn_name in tool_router:
                yield _TurnChunk(
                    text=(
                        f"> _Detected XML tool call in text — "
                        f"executing {fn_name} manually_\n\n"
                    ),
                )

                # Append the text as assistant message
                messages.append({
                    "role": "assistant",
                    "content": collected_content,
                })

                # Execute the tool call
                arg_preview = _format_tool_args(fn_name, params)
                yield _TurnChunk(
                    text=f"### {phase_label} — Turn {turn + 1}\n\n",
                )
                yield _TurnChunk(
                    text=f"🔧 **{fn_name}**({arg_preview})\n",
                )

                mcp_client = tool_router[fn_name]
                task = asyncio.ensure_future(
                    mcp_client.call_tool(http, fn_name, params)
                )
                call_start = time.time()
                while True:
                    done, _ = await asyncio.wait(
                        {task}, timeout=5.0,
                    )
                    if done:
                        break
                    call_elapsed = time.time() - call_start
                    yield _TurnChunk(
                        text=f"_⏳ ...{call_elapsed:.0f}s_\n",
                    )
                try:
                    result_str = task.result()
                except Exception as exc:
                    result_str = f"[Error: {fn_name} failed — {exc}]"

                summary = _summarize_result(fn_name, result_str)
                yield _TurnChunk(text=f"  → _{summary}_\n\n")

                # Feed result back as a user message (no tool_call_id)
                limit = _tool_result_limit(fn_name, valves)
                truncated = _truncate_tool_result(fn_name, result_str, limit)
                messages.append({
                    "role": "user",
                    "content": (
                        f"Tool result for {fn_name}:\n\n"
                        f"{truncated}\n\n"
                        "Continue with your task. Use the function calling "
                        "interface for tool calls — do NOT output XML."
                    ),
                })

                yield _TurnChunk(text="---\n\n")
                yield _TurnChunk(
                    result=_TurnResult(collected_content, True),
                )
                return

    # No tool calls → final text response (already streamed to UI)
    if not has_tool_calls:
        yield _TurnChunk(
            result=_TurnResult(
                _strip_think_tags(collected_content), False, streamed=True,
            ),
        )
        return

    # Show reasoning if any (skip if already streamed to UI)
    if collected_content and collected_content.strip() and not streamed_partial:
        clean_reasoning = _strip_think_tags(collected_content).strip()
        if clean_reasoning:
            yield _TurnChunk(text=f"> {clean_reasoning}\n\n")

    # Build assistant message with tool calls
    tc_raw = [
        {
            "id": tc["id"],
            "type": "function",
            "function": {
                "name": tc["name"],
                "arguments": tc["arguments"],
            },
        }
        for tc in collected_tool_calls
    ]
    messages.append({
        "role": "assistant",
        "content": collected_content or None,
        "tool_calls": tc_raw,
    })

    # Execute tool calls via MCP
    yield _TurnChunk(
        text=f"### {phase_label} — Turn {turn + 1}\n\n",
    )

    for tc in collected_tool_calls:
        fn_name = tc["name"]
        try:
            args = json.loads(tc["arguments"])
        except json.JSONDecodeError:
            args = {}

        arg_preview = _format_tool_args(fn_name, args)
        yield _TurnChunk(text=f"🔧 **{fn_name}**({arg_preview})\n")

        mcp_client = tool_router.get(fn_name)
        if not mcp_client:
            result_str = f"[Error: Unknown tool '{fn_name}']"
        else:
            task = asyncio.ensure_future(
                mcp_client.call_tool(http, fn_name, args)
            )
            call_start = time.time()
            while True:
                done, _ = await asyncio.wait(
                    {task}, timeout=5.0,
                )
                if done:
                    break
                call_elapsed = time.time() - call_start
                yield _TurnChunk(
                    text=f"_⏳ ...{call_elapsed:.0f}s_\n",
                )
            try:
                result_str = task.result()
            except Exception as exc:
                result_str = f"[Error: {fn_name} failed — {exc}]"

        summary = _summarize_result(fn_name, result_str)
        yield _TurnChunk(text=f"  → _{summary}_\n\n")

        limit = _tool_result_limit(fn_name, valves)
        messages.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": _truncate_tool_result(fn_name, result_str, limit),
        })

    yield _TurnChunk(text="---\n\n")
    yield _TurnChunk(result=_TurnResult(collected_content, True))


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _stream_response(minimax, messages, max_tokens=16384):
    """Streaming non-tool-calling text response from the LLM.

    Yields individual string deltas as they arrive.
    """
    try:
        stream = await minimax.chat.completions.create(
            model="minimax-m2.5",
            messages=messages,
            temperature=0.7,
            frequency_penalty=0.3,
            max_tokens=max_tokens,
            stream=True,
        )
        tf = _ThinkFilter()
        rep_detector = _RepetitionDetector()
        async for chunk in stream:
            if chunk.choices:
                d = chunk.choices[0].delta.content
                if d:
                    rep_detector.feed(d)
                    if rep_detector.is_degenerate():
                        print("[mcp_research_pipeline] Repetition detected in synthesis, aborting")
                        yield "\n\n_[Generation stopped — repetition detected]_\n\n"
                        break
                    clean = tf.feed(d)
                    if clean:
                        yield clean
    except Exception as exc:
        yield f"\n\n> ⚠ Synthesis failed: {exc}\n"


def _parse_selected_papers(text: str) -> list[dict]:
    """Extract paper titles and PDF URLs from Phase 1 selection output."""
    papers = []
    lines = text.split("\n")
    current_title = ""
    for line in lines:
        title_match = re.search(r"\*\*(.+?)\*\*", line)
        if title_match:
            current_title = title_match.group(1)
        pdf_match = re.search(r"PDF:\s*(https?://\S+)", line)
        if pdf_match and current_title:
            papers.append({
                "title": current_title,
                "pdf_url": pdf_match.group(1).rstrip(").,"),
            })
            current_title = ""
    return papers


def _format_tool_args(fn_name: str, args: dict) -> str:
    """Human-readable preview of tool arguments."""
    if fn_name == "search_arxiv":
        return f'"{args.get("query", "?")}"'
    if fn_name == "get_paper_info":
        return f'"{args.get("arxiv_id", "?")}"'
    if fn_name == "read_single_paper":
        return f'"{args.get("title", "?")}"'
    if fn_name == "read_papers":
        papers = args.get("papers", [])
        if papers:
            titles = [p.get("title", "?")[:40] for p in papers[:3]]
            extra = (
                f" +{len(papers) - 3} more"
                if len(papers) > 3
                else ""
            )
            return (
                f'{len(papers)} papers: {", ".join(titles)}{extra}'
            )
        return "?"
    first_val = next(iter(args.values()), "?") if args else "?"
    return f'"{str(first_val)[:50]}"'


def _summarize_result(fn_name: str, result: str) -> str:
    """One-line UI summary of a tool result."""
    if result.startswith("[Error") or result.startswith("[MCP Error"):
        return result[:120]
    chars = len(result)
    if fn_name == "search_arxiv":
        papers = len(
            re.findall(r"^\d+\.\s+\*\*", result, re.MULTILINE)
        )
        return f"{papers} papers found" if papers else f"{chars:,} chars"
    if fn_name == "get_paper_info":
        return f"paper metadata ({chars:,} chars)"
    if fn_name in ("read_papers", "read_single_paper"):
        page_counts = re.findall(r"\((\d+)\s+pages?\)", result)
        total_pages = sum(int(p) for p in page_counts) if page_counts else 0
        if total_pages:
            return f"OCR complete — {total_pages} pages, ~{chars:,} chars extracted"
        return f"OCR complete — ~{chars:,} chars extracted"
    return f"{chars:,} chars"


def _strip_think_tags(text: str) -> str:
    """Remove <think>…</think> blocks and stray </think> tags from LLM output."""
    # Full blocks: <think>...</think>
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Orphan closing tags (model sometimes forgets opening tag)
    text = text.replace("</think>", "")
    # Orphan opening tags left over
    text = text.replace("<think>", "")
    return text


def _strip_xml_tool_calls(text: str) -> str:
    """Remove XML tool-call blocks that MiniMax sometimes emits as text."""
    # <invoke name="...">...</invoke> or minimax:tool_call blocks
    text = re.sub(
        r'(?:minimax:tool_call\s*)?<invoke\s+name="[^"]*">.*?</invoke>\s*(?:minimax:tool_call)?',
        '', text, flags=re.DOTALL,
    )
    return text.strip()


class _ThinkFilter:
    """Stateful streaming filter that strips <think>…</think> blocks.

    Handles tags split across multiple chunks. Buffers text while inside
    a think block or while a partial tag is being assembled.
    """

    def __init__(self):
        self._inside = False   # currently inside <think>…</think>
        self._buf = ""         # partial-tag buffer

    def feed(self, text: str) -> str:
        """Feed a chunk, return the clean text to yield (may be empty)."""
        out = []
        self._buf += text

        while self._buf:
            if self._inside:
                # Look for closing </think>
                close = self._buf.find("</think>")
                if close != -1:
                    self._buf = self._buf[close + 8:]  # skip past tag
                    self._inside = False
                    continue
                # Check for partial closing tag at end
                for i in range(1, min(len("</think>"), len(self._buf) + 1)):
                    if "</think>"[:i] == self._buf[-i:]:
                        # Might be start of closing tag — keep buffered
                        return "".join(out)
                # No sign of closing tag — discard everything (inside block)
                self._buf = ""
                return "".join(out)
            else:
                # Look for opening <think>
                open_idx = self._buf.find("<think>")
                if open_idx != -1:
                    # Emit everything before the tag
                    out.append(self._buf[:open_idx])
                    self._buf = self._buf[open_idx + 7:]  # skip tag
                    self._inside = True
                    continue
                # Check for stray </think> (orphan closing tag)
                close_idx = self._buf.find("</think>")
                if close_idx != -1:
                    out.append(self._buf[:close_idx])
                    self._buf = self._buf[close_idx + 8:]
                    continue
                # Check for partial opening tag at end
                for i in range(1, min(len("<think>"), len(self._buf) + 1)):
                    if "<think>"[:i] == self._buf[-i:]:
                        out.append(self._buf[:-i])
                        self._buf = self._buf[-i:]
                        return "".join(out)
                # Also check partial </think> at end
                for i in range(1, min(len("</think>"), len(self._buf) + 1)):
                    if "</think>"[:i] == self._buf[-i:]:
                        out.append(self._buf[:-i])
                        self._buf = self._buf[-i:]
                        return "".join(out)
                # No tags at all — emit everything
                out.append(self._buf)
                self._buf = ""

        return "".join(out)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return (
        text[:max_chars]
        + f"\n\n[...truncated, {len(text) - max_chars} chars omitted]"
    )


def _tool_result_limit(fn_name: str, valves) -> int:
    """Return the appropriate char limit based on tool type."""
    if fn_name in ("read_papers", "read_single_paper"):
        return getattr(valves, "OCR_RESULT_MAX_CHARS", 120000)
    return getattr(valves, "SEARCH_RESULT_MAX_CHARS", 12000)


def _truncate_tool_result(fn_name: str, text: str, max_chars: int) -> str:
    """Smart truncation that distributes budget across papers for OCR results."""
    if len(text) <= max_chars:
        return text
    if fn_name != "read_papers":
        return _truncate(text, max_chars)

    # For read_papers: split by paper separator and give each paper
    # an equal share of the budget so ALL papers are represented.
    separator = "\n\n---\n\n"
    papers = text.split(separator)
    if len(papers) <= 1:
        return _truncate(text, max_chars)

    # Reserve space for separators and per-paper truncation notices
    overhead = len(separator) * (len(papers) - 1) + len(papers) * 80
    per_paper = max((max_chars - overhead) // len(papers), 500)

    truncated_papers = []
    for paper in papers:
        if len(paper) <= per_paper:
            truncated_papers.append(paper)
        else:
            truncated_papers.append(
                paper[:per_paper]
                + f"\n[...paper truncated, {len(paper) - per_paper} chars omitted]"
            )

    return separator.join(truncated_papers)


class _RepetitionDetector:
    """Detects degenerate repetition loops in streaming LLM output.

    Keeps a sliding window of recent tokens.  When a short phrase repeats
    more than `threshold` times in the window, `is_degenerate()` returns
    True so the caller can abort generation.
    """

    def __init__(self, window: int = 200, threshold: int = 8):
        self._window: list[str] = []
        self._max = window
        self._threshold = threshold

    def feed(self, text: str) -> None:
        self._window.append(text)
        if len(self._window) > self._max:
            self._window = self._window[-self._max:]

    def is_degenerate(self) -> bool:
        recent = "".join(self._window[-self._max:])
        if len(recent) < 40:
            return False
        # Check the last 20 chars as a candidate repeat pattern
        tail = recent[-20:].strip()
        if len(tail) < 3:
            return False
        count = recent.count(tail)
        return count >= self._threshold
