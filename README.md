# vllm-test

Load-testing Qwen3-0.6B on a single RTX 4060 (8GB, WSL2):

1. Transformers + FastAPI vs vLLM
2. vLLM vs vLLM behind a Redis response cache

## Setup

| Item | Value |
|---|---|
| GPU | RTX 4060 8GB, WSL2 Ubuntu |
| Model | Qwen/Qwen3-0.6B (bf16, thinking off) |
| Versions | vLLM 0.31.0, transformers 5.17.0, torch 2.13.0, k6 0.54.0 |
| Servers | Run on the WSL host, one at a time |
| Load generator | k6 in a pod on a kind (k8s) cluster |
| Request | `/v1/chat/completions`, `max_tokens=128`, `temperature=0`, non-streaming |
| Run length | 60s per case; VUS = concurrent users |

All settings (model, ports, VUS, etc.) live in `.env`; caches are stored in `.cache/`.

## Files

- `hf_server.py`: Transformers + FastAPI baseline (requests serialized by a lock, no batching)
- `proxy.py`: FastAPI proxy that caches vLLM responses in Redis, keyed by the SHA-256 of the request body
- `k6/bench.js`: load script
- `prep_sessions.py`, `k6/system_prompt.txt`, `k6/chat.js`: chatbot workload (experiment 3)
- `Makefile`: `hf`, `vllm`, `redis`, `proxy`, `bench`, `sessions`, `chat`

## Run

```bash
kind create cluster
make vllm                                  # or: make hf
make bench PORT=8000 NAME=vllm VUS=8       # output: results/vllm.txt

make redis && make proxy                   # cache experiment
make bench PORT=8002 NAME=vllm-redis PROMPTS=50 VUS=32
```

The k6 pod reaches the host via `host.docker.internal` (Docker Desktop).
vLLM runs with `VLLM_USE_FLASHINFER_SAMPLER=0` because nvcc is not installed.

## Results

### 1. Transformers vs vLLM

| VUS | Server | tok/s | req/s | Avg latency | p95 latency |
|---:|---|---:|---:|---:|---:|
| 1 | Transformers | 27 | 0.21 | 4.73s | 6.51s |
| 1 | **vLLM** | **139** | 1.09 | 0.92s | 0.96s |
| 8 | Transformers | 26 | 0.20 | 31.1s | 43.4s |
| 8 | **vLLM** | **1,045** | 8.17 | 0.98s | 1.05s |
| 32 | Transformers | 20 | 0.16 | 46.9s | 81s |
| 32 | **vLLM** | **3,463** | 27.05 | 1.18s | 1.25s |

- vLLM is about 5x faster even with a single user.
- Transformers handles requests one at a time, so throughput stays flat and latency grows with the number of users.
- With continuous batching, vLLM's throughput grows about 25x from 1 to 32 users while latency barely changes.

### 2. vLLM vs vLLM + Redis cache (VUS = 32)

| Distinct prompts | Setup | req/s | Avg latency | p95 latency |
|---:|---|---:|---:|---:|
| 50 | vLLM | 27 | 1.16s | 1.20s |
| 50 | **vLLM + Redis** | **2,811** | **11ms** | 14ms |
| 1000 | vLLM | 27 | 1.17s | 1.23s |
| 1000 | **vLLM + Redis** | **944** | **34ms** | 15ms |

- Cache hits are about 100x faster than generating a response.
- Hit rate was above 99.9% with 50 prompts and about 98% with 1000.
- The gain applies only when requests repeat. The 0% hit-rate case was not measured.

### 3. Chatbot workload: Transformers vs vLLM vs vLLM + Redis

Experiments 1 and 2 use one short prompt (~20 tokens) with 50 variants, so every cache hits almost all the time.
This experiment replays real chat sessions instead:

- **System prompt**: a fixed 842-token assistant prompt (`k6/system_prompt.txt`), shared by every request.
- **User input**: 1000 multi-turn sessions from [ShareGPT](https://huggingface.co/datasets/anon8231489123/ShareGPT_Vicuna_unfiltered) (seed 0), up to 5 user turns each, trimmed so every prompt fits in `MAX_MODEL_LEN - MAX_TOKENS` (1920 tokens).
- **Replay**: one k6 iteration = one session. Turn k sends `[system, u1, a1, …, uk]`. The history uses the dataset's assistant replies, so every server receives the same prompts. Sessions do not repeat within a run.
- **Cache reset**: before each run, `make chat` clears the vLLM prefix cache (`/reset_prefix_cache`, enabled by `VLLM_SERVER_DEV_MODE=1`) and flushes Redis. It records the cache counters before and after the run in the result file.

| Item | Value |
|---|---|
| Sessions / requests | 1000 / 2440 (2.44 turns per session) |
| Prompt tokens | mean 1192, p50 1118, max 1920 |
| Expected vLLM prefix hit | 71% (system prompt only) to 83% (system prompt + previous turn) |

```bash
make sessions                                              # downloads ShareGPT, writes k6/sessions.js
make hf;   make chat PORT=8001 NAME=chat-hf-vus8 VUS=8
make vllm; make chat PORT=8000 NAME=warmup VUS=8 DURATION=20s   # discard
           make chat PORT=8000 NAME=chat-vllm-vus8 VUS=8
make redis && make proxy
           make chat PORT=8002 NAME=chat-redis-vus8 VUS=8
```

Hit rate = Δhits / Δqueries (vLLM `prefix_cache_*_total`) or Δhits / Δ(hits + misses) (Redis `keyspace_*`), using the counters before and after the run.
Also check the k6 `iterations` count stays below 1000 so no session is reused.

| VUS | Server | req/s | output tok/s | prompt tok/s | Avg latency | p95 latency | vLLM prefix hit | Redis hit |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 32 | Transformers | 0.29 | 27 | 276 | 48.2s | 87s | – | – |
| 32 | vLLM | 11.8 | 1,195 | 14,049 | 2.53s | 4.66s | 82.1% | – |
| 32 | vLLM + Redis | 11.9 | 1,213 | 14,144 | 2.55s | 4.53s | 82.1% | 0.1% |

VUS=32 only so far (one run each). The first vLLM run gave 8.4 req/s, 3.6s avg latency, and 82.3% prefix hit, but a rerun gave 11.8 req/s; the table uses the rerun, so run-to-run noise is about 40%.
Transformers had 12 sessions (28 requests) done in 95s; k6 stopped the other 31 sessions at the end.
Redis hit 1 of 836 requests (0.1%), so the Redis case is the same as vLLM within noise.

Expected: the Redis hit rate is close to 0%, because the whole body (system prompt + history + new message) is the cache key, so vLLM + Redis should be about as fast as vLLM. vLLM's prefix cache still reuses the shared system prompt and earlier turns.
The KV cache holds 35,584 tokens. At VUS=32 (~32 × 1.2k tokens), that is only enough because prefixes are shared, so check `vllm.log` for preemption and `Waiting` requests.

## Caveats

- One run per case, so there is no variance estimate. Transformers completed only 13–18 requests per case.
- Right after a server starts, the first measurements are slow. The vLLM numbers above are from a re-run after warm-up.
- In the Redis runs, tok/s also counts tokens from cached responses, so use req/s and latency to compare.
- Streaming, time to first token, long prompts and a proxy-without-cache control were not measured.
- Raw k6 output is in `results/`. A Korean write-up is in `RESULTS.md`.
