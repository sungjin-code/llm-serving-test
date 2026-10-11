include .env
export

.PHONY: hf vllm redis proxy bench sessions chat

hf:
	uv run uvicorn hf_server:app --host 0.0.0.0 --port $(HF_PORT)

vllm:
	VLLM_SERVER_DEV_MODE=1 uv run vllm serve $(MODEL) --host 0.0.0.0 --port $(VLLM_PORT) --gpu-memory-utilization $(GPU_UTIL) --max-model-len $(MAX_MODEL_LEN)

redis:
	docker run -d --rm --name redis -p $(REDIS_PORT):6379 redis:7-alpine

proxy:
	uv run uvicorn proxy:app --host 0.0.0.0 --port $(PROXY_PORT)

K6 = kubectl run k6-$(NAME) --rm -i --restart=Never --image=grafana/k6:$(K6_VERSION) \
  --env TARGET=http://host.docker.internal:$(PORT) --env MODEL=$(MODEL) --env VUS=$(VUS) --env DURATION=$(DURATION) \
  --env MAX_TOKENS=$(MAX_TOKENS) --env PROMPTS=$(PROMPTS) \
  -- run -

# make bench PORT=8000 NAME=vllm
bench:
	mkdir -p results && $(K6) < k6/bench.js | tee results/$(NAME).txt

sessions:
	uv run python prep_sessions.py

# Cache counters, recorded before and after each chat run: hit rate = delta hits / delta (queries | hits+misses).
CACHE_STATS = (curl -sf localhost:$(VLLM_PORT)/metrics | grep -E '^vllm:prefix_cache_(hits|queries)_total'; \
  docker exec redis redis-cli INFO stats | grep -E '^keyspace_(hits|misses)' || true)

# make chat PORT=8000 NAME=chat-vllm-vus8 VUS=8   (needs `make sessions` first)
chat:
	mkdir -p results
	-curl -sf -X POST localhost:$(VLLM_PORT)/reset_prefix_cache
	-docker exec redis redis-cli FLUSHALL
	$(CACHE_STATS) > results/$(NAME).txt
	cat k6/chat.js k6/sessions.js | $(K6) | tee -a results/$(NAME).txt
	$(CACHE_STATS) >> results/$(NAME).txt
