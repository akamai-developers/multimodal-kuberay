#!/usr/bin/env python3
"""Simple staged concurrency benchmark for the MiniMax OpenAI-compatible API."""

from __future__ import annotations

import argparse
import json
import subprocess
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any

DEFAULT_MODEL = "minimax-m2.5"
TABLE_COLUMNS = [
    ("conc", "concurrency"),
    ("max_tok", "max_tokens"),
    ("ok", None),
    ("prompt_tok", "avg_prompt_tokens"),
    ("out_tok", "avg_completion_tokens"),
    ("wall_s", "wall_time_s"),
    ("ttft_avg_s", "avg_ttft_s"),
    ("lat_avg_s", "avg_latency_s"),
    ("lat_p50_s", "p50_latency_s"),
    ("lat_max_s", "max_latency_s"),
    ("req_tps", "avg_request_tokens_per_s"),
    ("rps", "request_throughput_rps"),
]
PROMPT_VOCABULARY = [
    "alpha",
    "bravo",
    "charlie",
    "delta",
    "echo",
    "foxtrot",
    "golf",
    "hotel",
    "india",
    "juliet",
    "kilo",
    "lima",
    "mango",
    "nectar",
    "olive",
    "piper",
    "quartz",
    "river",
    "sierra",
    "tango",
]


def format_cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def print_table(summaries: list[dict[str, Any]]) -> None:
    rows: list[list[str]] = []
    for summary in summaries:
        row: list[str] = []
        for _, key in TABLE_COLUMNS:
            if key is None:
                row.append(f"{summary['successes']}/{summary['requests']}")
            else:
                row.append(format_cell(summary.get(key)))
        rows.append(row)

    widths = []
    for index, (header, _) in enumerate(TABLE_COLUMNS):
        widths.append(max(len(header), *(len(row[index]) for row in rows)))

    header_line = "  ".join(
        header.ljust(widths[index]) for index, (header, _) in enumerate(TABLE_COLUMNS)
    )
    divider_line = "  ".join("-" * widths[index] for index in range(len(TABLE_COLUMNS)))
    print(header_line)
    print(divider_line)
    for row in rows:
        print("  ".join(row[index].ljust(widths[index]) for index in range(len(TABLE_COLUMNS))))


def build_large_prompt(target_words: int, target_output_lines: int) -> str:
    """Create a large prompt and explicitly ask for a long structured completion."""
    # Cycle through a fixed vocabulary so prompt size scales predictably without
    # introducing randomness that would make benchmark runs harder to compare.
    words = [PROMPT_VOCABULARY[index % len(PROMPT_VOCABULARY)] for index in range(target_words)]
    prompt_body = " ".join(words)
    return (
        "You are participating in a throughput benchmark. Read the full payload and "
        "identify the final word in the payload.\n\n"
        f"Then produce exactly {target_output_lines} lines.\n"
        "Each line must use this exact format:\n"
        "line NNNN: final word is <word>\n"
        "Use zero-padded numbering starting at 0001.\n"
        "Do not use bullet points.\n"
        "Do not stop early.\n"
        "Do not include analysis, reasoning tags, or any text before or after the lines.\n\n"
        f"{prompt_body}"
    )


@dataclass
class RequestResult:
    ok: bool
    latency_s: float
    status_code: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    ttft_s: float | None = None
    error: str | None = None


def parse_int_list(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def run_kubectl_json(args: list[str], kubeconfig: str | None) -> Any:
    cmd = ["kubectl"]
    if kubeconfig:
        cmd.extend(["--kubeconfig", kubeconfig])
    cmd.extend(args)
    completed = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def discover_endpoint_from_cluster(kubeconfig: str | None) -> str:
    # Discover the public chat-completions endpoint from Gateway API resources
    # so the benchmark can follow the active cluster address instead of a fixed IP.
    gateways = run_kubectl_json(["get", "gateway", "-A", "-o", "json"], kubeconfig)
    routes = run_kubectl_json(["get", "httproute", "-A", "-o", "json"], kubeconfig)

    route = next(
        (
            item
            for item in routes.get("items", [])
            if item.get("metadata", {}).get("name") == "llm-route"
        ),
        None,
    )
    if route is None:
        raise ValueError("Could not find HTTPRoute named 'llm-route'.")

    parent_ref = next(iter(route.get("spec", {}).get("parentRefs", [])), None)
    if parent_ref is None:
        raise ValueError("HTTPRoute 'llm-route' does not define a parent gateway.")

    route_namespace = route.get("metadata", {}).get("namespace", "default")
    gateway_namespace = parent_ref.get("namespace", route_namespace)
    gateway_name = parent_ref.get("name")
    gateway = next(
        (
            item
            for item in gateways.get("items", [])
            if item.get("metadata", {}).get("name") == gateway_name
            and item.get("metadata", {}).get("namespace") == gateway_namespace
        ),
        None,
    )
    if gateway is None:
        raise ValueError(
            f"Could not find Gateway '{gateway_namespace}/{gateway_name}' referenced by llm-route."
        )

    addresses = gateway.get("status", {}).get("addresses", [])
    address = next((entry.get("value") for entry in addresses if entry.get("value")), None)
    if not address:
        raise ValueError(f"Gateway '{gateway_namespace}/{gateway_name}' has no assigned address.")

    path_prefix = "/v1/"
    for rule in route.get("spec", {}).get("rules", []):
        for match in rule.get("matches", []):
            path = match.get("path", {})
            if path.get("type") == "PathPrefix" and path.get("value"):
                path_prefix = path["value"]
                break
        if path_prefix != "/v1/":
            break

    normalized_prefix = path_prefix.rstrip("/")
    return f"http://{address}{normalized_prefix}/chat/completions"


def resolve_endpoint(args: argparse.Namespace) -> str:
    if args.endpoint:
        return args.endpoint
    if args.discover_endpoint_from_cluster:
        try:
            return discover_endpoint_from_cluster(args.kubeconfig)
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else str(exc)
            raise SystemExit(f"Failed to discover endpoint with kubectl: {stderr}") from exc
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    raise SystemExit(
        "No endpoint configured. Pass --endpoint or use --discover-endpoint-from-cluster "
        "[--kubeconfig PATH]."
    )


def build_request_payload(model: str, prompt: str, max_tokens: int, stream: bool) -> bytes:
    # Keep the request shape close to a normal chat completion call so this
    # benchmark exercises the same model-serving path as real clients.
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Process the input carefully and respond tersely.",
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    if stream:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
    return json.dumps(payload).encode("utf-8")


def build_headers(request_id: int, bearer_token: str | None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "X-Benchmark-Request-Id": str(request_id),
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    return headers


def read_streaming_usage(resp: Any, started: float) -> tuple[dict[str, Any], float | None, float]:
    usage: dict[str, Any] = {}
    ttft_s: float | None = None
    for raw_line in resp:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line or not line.startswith("data: "):
            continue
        data = line[6:]
        if data == "[DONE]":
            break
        if ttft_s is None:
            ttft_s = time.perf_counter() - started
        parsed_event = json.loads(data)
        if parsed_event.get("usage"):
            usage = parsed_event["usage"]
    return usage, ttft_s, time.perf_counter() - started


def read_non_streaming_usage(resp: Any, started: float) -> tuple[dict[str, Any], float]:
    response_body = resp.read()
    latency_s = time.perf_counter() - started
    body_text = response_body.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(body_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON response: {exc}: {body_text[:240]}") from exc
    return parsed.get("usage", {}), latency_s


def build_failure_result(
    started: float,
    *,
    status_code: int | None,
    error: str,
) -> RequestResult:
    return RequestResult(
        ok=False,
        latency_s=time.perf_counter() - started,
        status_code=status_code,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        error=error,
    )


def format_error_message(status_code: int | None, error: str) -> str:
    detail = error.strip() or "request failed without an error body"
    if status_code is None:
        return detail[:400]
    return f"HTTP {status_code}: {detail}"[:400]


def emit_stage_progress(event: str, concurrency: int, max_tokens: int, **fields: Any) -> None:
    details = " ".join(f"{name}={value}" for name, value in fields.items())
    print(
        f"[stage {event}] concurrency={concurrency} max_tokens={max_tokens} {details}",
        flush=True,
    )


def summarize_stage(
    *,
    concurrency: int,
    max_tokens: int,
    wall_time_s: float,
    results: list[RequestResult],
) -> dict[str, Any]:
    # Aggregate both user-visible latency metrics and throughput metrics from the
    # per-request results so each stage can be compared as a single snapshot.
    successes = [result for result in results if result.ok]
    failures = [result for result in results if not result.ok]
    prompt_tokens = sum(result.prompt_tokens or 0 for result in successes)
    completion_tokens = sum(result.completion_tokens or 0 for result in successes)
    total_tokens = sum(result.total_tokens or 0 for result in successes)
    latencies = [result.latency_s for result in results]
    ttfts = [result.ttft_s for result in successes if result.ttft_s is not None]
    per_request_tps = [
        (result.total_tokens or 0) / result.latency_s
        for result in successes
        if result.latency_s > 0 and result.total_tokens is not None
    ]

    return {
        "concurrency": concurrency,
        "max_tokens": max_tokens,
        "requests": len(results),
        "successes": len(successes),
        "failures": len(failures),
        "wall_time_s": round(wall_time_s, 3),
        "avg_latency_s": round(statistics.mean(latencies), 3),
        "p50_latency_s": round(statistics.median(latencies), 3),
        "max_latency_s": round(max(latencies), 3),
        "avg_ttft_s": round(statistics.mean(ttfts), 3) if ttfts else None,
        "p50_ttft_s": round(statistics.median(ttfts), 3) if ttfts else None,
        "avg_prompt_tokens": round(prompt_tokens / len(successes), 1) if successes else None,
        "avg_completion_tokens": round(completion_tokens / len(successes), 1) if successes else None,
        "avg_request_tokens_per_s": round(statistics.mean(per_request_tps), 3) if per_request_tps else None,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "request_throughput_rps": round(len(results) / wall_time_s, 3),
        "token_throughput_tps": round(total_tokens / wall_time_s, 3) if wall_time_s else 0,
        "sample_error": failures[0].error[:400] if failures else None,
    }


def send_request(
    endpoint: str,
    model: str,
    prompt: str,
    max_tokens: int,
    timeout_s: int,
    request_id: int,
    bearer_token: str | None,
    stream: bool,
) -> RequestResult:
    req = urllib.request.Request(
        endpoint,
        data=build_request_payload(model, prompt, max_tokens, stream),
        headers=build_headers(request_id, bearer_token),
        method="POST",
    )

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            if stream:
                try:
                    usage, ttft_s, latency_s = read_streaming_usage(resp, started)
                except json.JSONDecodeError as exc:
                    return build_failure_result(
                        started,
                        status_code=resp.getcode(),
                        error=f"Invalid streaming JSON event: {exc}",
                    )
            else:
                try:
                    usage, latency_s = read_non_streaming_usage(resp, started)
                except ValueError as exc:
                    return build_failure_result(started, status_code=resp.getcode(), error=str(exc))
                ttft_s = None
            return RequestResult(
                ok=True,
                latency_s=latency_s,
                status_code=resp.getcode(),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
                ttft_s=ttft_s,
            )
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        return build_failure_result(
            started,
            status_code=exc.code,
            error=format_error_message(exc.code, error_body or str(exc.reason)),
        )
    except urllib.error.URLError as exc:
        return build_failure_result(
            started,
            status_code=None,
            error=f"URL error: {exc.reason}",
        )
    except Exception as exc:  # noqa: BLE001
        return build_failure_result(
            started,
            status_code=None,
            error=str(exc),
        )


def run_stage(
    concurrency: int,
    endpoint: str,
    model: str,
    prompt: str,
    max_tokens: int,
    timeout_s: int,
    bearer_token: str | None,
    progress: bool,
    stream: bool,
) -> dict[str, Any]:
    stage_started = time.perf_counter()
    results: list[RequestResult] = []

    if progress:
        emit_stage_progress("start", concurrency, max_tokens, requests=concurrency)

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                send_request,
                endpoint,
                model,
                prompt,
                max_tokens,
                timeout_s,
                request_id,
                bearer_token,
                stream,
            )
            for request_id in range(concurrency)
        ]
        if progress:
            emit_stage_progress(
                "submitted",
                concurrency,
                max_tokens,
                submitted=len(futures),
                in_flight=len(futures),
            )
        completed = 0
        pending = set(futures)
        last_heartbeat_s = 0.0
        while pending:
            done, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
            if not done:
                if progress:
                    elapsed_s = time.perf_counter() - stage_started
                    if elapsed_s - last_heartbeat_s >= 1.0:
                        emit_stage_progress(
                            "heartbeat",
                            concurrency,
                            max_tokens,
                            elapsed=f"{elapsed_s:.1f}s",
                            completed=f"{completed}/{concurrency}",
                            in_flight=len(pending),
                        )
                        last_heartbeat_s = elapsed_s
                continue

            for future in done:
                results.append(future.result())
                completed += 1
                if progress:
                    emit_stage_progress(
                        "progress",
                        concurrency,
                        max_tokens,
                        completed=f"{completed}/{concurrency}",
                        in_flight=len(pending),
                    )

    wall_time_s = time.perf_counter() - stage_started
    return summarize_stage(
        concurrency=concurrency,
        max_tokens=max_tokens,
        wall_time_s=wall_time_s,
        results=results,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run staged parallel requests against the MiniMax chat completions API."
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="Chat completions endpoint URL. If omitted, use --discover-endpoint-from-cluster.",
    )
    parser.add_argument(
        "--discover-endpoint-from-cluster",
        action="store_true",
        help="Resolve the public /v1/chat/completions endpoint from Gateway API resources via kubectl.",
    )
    parser.add_argument(
        "--kubeconfig",
        default=None,
        help="Optional kubeconfig path to use with --discover-endpoint-from-cluster.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--concurrency",
        default="5,10,15,20",
        help="Comma-separated concurrency stages to run.",
    )
    parser.add_argument(
        "--output-tokens",
        default=None,
        help="Optional comma-separated max_tokens stages. If set, runs the full matrix.",
    )
    parser.add_argument(
        "--prompt-words",
        type=int,
        default=12000,
        help="Approximate number of whitespace-delimited words in the prompt body.",
    )
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--timeout", type=int, default=600, help="Per-request timeout in seconds.")
    parser.add_argument("--bearer-token", default=None, help="Optional bearer token for gateway auth.")
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Use streaming responses and measure time to first token.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a table.",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable live stage progress messages.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    endpoint = resolve_endpoint(args)
    stages = parse_int_list(args.concurrency)
    output_token_stages = (
        parse_int_list(args.output_tokens)
        if args.output_tokens
        else [args.max_tokens]
    )
    summaries: list[dict[str, Any]] = []
    for max_tokens in output_token_stages:
        # Tie requested output size to the response budget so each stage puts
        # roughly comparable pressure on generation relative to max_tokens.
        target_output_lines = max(24, max_tokens // 6)
        prompt = build_large_prompt(args.prompt_words, target_output_lines)
        for concurrency in stages:
            summary = run_stage(
                concurrency=concurrency,
                endpoint=endpoint,
                model=args.model,
                prompt=prompt,
                max_tokens=max_tokens,
                timeout_s=args.timeout,
                bearer_token=args.bearer_token,
                progress=not args.no_progress and not args.json,
                stream=args.stream,
            )
            summaries.append(summary)
            if not args.json:
                print(
                    f"stage={summary['concurrency']:>3} "
                    f"max_tokens={summary['max_tokens']:>4} "
                    f"ok={summary['successes']}/{summary['requests']} "
                    f"wall={summary['wall_time_s']:>8}s "
                    f"ttft_avg={format_cell(summary['avg_ttft_s']):>8}s "
                    f"avg={summary['avg_latency_s']:>8}s "
                    f"p50={summary['p50_latency_s']:>8}s "
                    f"max={summary['max_latency_s']:>8}s "
                    f"req_tps={format_cell(summary['avg_request_tokens_per_s']):>10} "
                    f"rps={format_cell(summary['request_throughput_rps']):>8} "
                )
                if summary["sample_error"]:
                    print(f"  error: {summary['sample_error']}")
                sys.stdout.flush()

    if args.json:
        print(json.dumps(summaries, indent=2))
    else:
        print()
        print_table(summaries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
