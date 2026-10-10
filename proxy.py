import hashlib
import os

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, Request, Response

r = redis.Redis(port=int(os.environ["REDIS_PORT"]))
vllm = httpx.AsyncClient(
    base_url=f"http://localhost:{os.environ['VLLM_PORT']}", timeout=None
)
app = FastAPI()


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.body()
    key = hashlib.sha256(body).hexdigest()
    if hit := await r.get(key):
        return Response(hit, media_type="application/json")
    resp = await vllm.post(
        "/v1/chat/completions",
        content=body,
        headers={"content-type": "application/json"},
    )
    if resp.status_code == 200:
        await r.set(key, resp.content)
    return Response(resp.content, resp.status_code, media_type="application/json")
