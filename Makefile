include .env
export

.PHONY: hf vllm redis proxy bench

hf:
	uv run uvicorn hf_server:app --host 0.0.0.0 --port $(HF_PORT)

vllm:
	uv run vllm serve $(MODEL) --host 0.0.0.0 --port $(VLLM_PORT) --gpu-memory-utilization $(GPU_UTIL) --max-model-len $(MAX_MODEL_LEN)

redis:
	docker run -d --rm --name redis -p $(REDIS_PORT):6379 redis:7-alpine

proxy:
	uv run uvicorn proxy:app --host 0.0.0.0 --port $(PROXY_PORT)

# make bench PORT=8000 NAME=vllm
bench:
	mkdir -p results && kubectl run k6-$(NAME) --rm -i --restart=Never --image=grafana/k6:$(K6_VERSION) \
	  --env TARGET=http://host.docker.internal:$(PORT) --env MODEL=$(MODEL) --env VUS=$(VUS) --env DURATION=$(DURATION) \
	  --env MAX_TOKENS=$(MAX_TOKENS) --env PROMPTS=$(PROMPTS) \
	  -- run - < k6/bench.js | tee results/$(NAME).txt
