# Benchmarking the Gateway API

Use `scripts/minimax_parallel_benchmark.py` to measure latency and throughput against the public MiniMax Gateway endpoint.

The script is useful when you want to answer questions like:

- how does latency change as concurrency rises?
- how much throughput do we get at different prompt sizes?
- how does streaming feel compared with full-response timing?

## Before You Run It

The Gateway is protected by bearer-token auth, so the benchmark needs the same token your normal API clients use.

Load the values you need:

```bash
set -a
source .env
set +a

export GATEWAY_IP=$(kubectl get gateway llm-gateway -o jsonpath='{.status.addresses[0].value}')
export BENCHMARK_TOKEN="${OPENAI_API_KEY}"
export BENCHMARK_ENDPOINT="http://${GATEWAY_IP}/v1/chat/completions"
```

If you skip `--bearer-token`, you should expect auth failures rather than meaningful benchmark results.

## Quick Start

Use cluster discovery when you want the script to resolve the live Gateway endpoint for you:

```bash
python3 scripts/minimax_parallel_benchmark.py \
  --discover-endpoint-from-cluster \
  --bearer-token "${BENCHMARK_TOKEN}" \
  --prompt-words 12000
```

Use an explicit endpoint when you already know the Gateway address:

```bash
python3 scripts/minimax_parallel_benchmark.py \
  --endpoint "${BENCHMARK_ENDPOINT}" \
  --bearer-token "${BENCHMARK_TOKEN}" \
  --prompt-words 12000
```

## Common Runs

Sweep concurrency:

```bash
python3 scripts/minimax_parallel_benchmark.py \
  --endpoint "${BENCHMARK_ENDPOINT}" \
  --bearer-token "${BENCHMARK_TOKEN}" \
  --concurrency 1,2,4,8,16 \
  --prompt-words 8000 \
  --max-tokens 256
```

Sweep concurrency and output size together:

```bash
python3 scripts/minimax_parallel_benchmark.py \
  --endpoint "${BENCHMARK_ENDPOINT}" \
  --bearer-token "${BENCHMARK_TOKEN}" \
  --concurrency 1,2,4,8 \
  --prompt-words 12000 \
  --output-tokens 64,128,256
```

Compare small and large prompts:

```bash
python3 scripts/minimax_parallel_benchmark.py \
  --endpoint "${BENCHMARK_ENDPOINT}" \
  --bearer-token "${BENCHMARK_TOKEN}" \
  --concurrency 1,4,8 \
  --prompt-words 2000 \
  --max-tokens 128
```

```bash
python3 scripts/minimax_parallel_benchmark.py \
  --endpoint "${BENCHMARK_ENDPOINT}" \
  --bearer-token "${BENCHMARK_TOKEN}" \
  --concurrency 1,4,8 \
  --prompt-words 20000 \
  --max-tokens 128
```

Measure streaming responsiveness and emit JSON:

```bash
python3 scripts/minimax_parallel_benchmark.py \
  --endpoint "${BENCHMARK_ENDPOINT}" \
  --bearer-token "${BENCHMARK_TOKEN}" \
  --prompt-words 12000 \
  --stream \
  --json
```

## How to Think About the Main Flags

- `--endpoint` uses an explicit `/v1/chat/completions` URL.
- `--discover-endpoint-from-cluster` asks the script to resolve the live Gateway address from Kubernetes.
- `--bearer-token` sends `Authorization: Bearer ...` on every request.
- `--concurrency` controls how many requests run in parallel at each stage.
- `--prompt-words` increases or decreases prompt size.
- `--max-tokens` sets one output budget for the run.
- `--output-tokens` runs the same benchmark repeatedly across multiple output budgets.
- `--stream` measures time to first token in addition to full latency.
- `--json` emits machine-readable output instead of the human-readable table.

The main distinction to remember:

- use `--max-tokens` for one output-size run
- use `--output-tokens` for a sweep across several output sizes

## Reading the Results

Each output row represents one benchmark stage for a specific concurrency and output setting.

- `conc`: requests sent in parallel for that stage
- `max_tok`: requested `max_tokens` per request
- `ok`: successful requests out of total requests
- `prompt_tok`: average prompt tokens per successful request
- `out_tok`: average completion tokens per successful request
- `wall_s`: total wall-clock time for the stage
- `ttft_avg_s`: average time to first token for streaming runs
- `lat_avg_s`: average full request latency
- `lat_p50_s`: median latency
- `lat_max_s`: slowest request latency in the stage
- `req_tps`: average per-request token throughput
- `rps`: request throughput for the full stage

In practice:

- rising `rps` with stable latency usually means you still have headroom
- rising latency at higher concurrency usually means queueing or backend contention
- falling `ok` usually means the system is no longer handling that load cleanly
- `ttft_avg_s` is the most useful metric when you care about streamed responsiveness

## Notes

- The benchmark targets the public Gateway API, not an internal service URL.
- Reuse the same `OPENAI_API_KEY` from `.env` so benchmark traffic matches real client traffic.
- Start with small concurrency values and work up; it is easier to spot saturation that way.
