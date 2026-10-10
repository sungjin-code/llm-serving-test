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
- `Makefile`: `hf`, `vllm`, `redis`, `proxy`, `bench`

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

## Caveats

- One run per case, so there is no variance estimate. Transformers completed only 13–18 requests per case.
- Right after a server starts, the first measurements are slow. The vLLM numbers above are from a re-run after warm-up.
- In the Redis runs, tok/s also counts tokens from cached responses, so use req/s and latency to compare.
- Streaming, time to first token, long prompts and a proxy-without-cache control were not measured.
- Raw k6 output is in `results/`. A Korean write-up is in `RESULTS.md`.
