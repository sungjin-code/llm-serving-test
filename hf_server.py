import os
import threading

import torch
from fastapi import FastAPI
from transformers import AutoModelForCausalLM, AutoTokenizer

tok = AutoTokenizer.from_pretrained(os.environ["MODEL"])
model = AutoModelForCausalLM.from_pretrained(
    os.environ["MODEL"], dtype=torch.bfloat16
).to("cuda")
lock = threading.Lock()
app = FastAPI()


@app.post("/v1/chat/completions")
def chat(req: dict):
    ids = tok.apply_chat_template(
        req["messages"],
        add_generation_prompt=True,
        enable_thinking=False,
        return_tensors="pt",
        return_dict=True,
    )["input_ids"].to("cuda")
    with lock:
        out = model.generate(
            ids, max_new_tokens=req.get("max_tokens", 128), do_sample=False
        )
    new = out[0, ids.shape[1] :]
    return {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": tok.decode(new, skip_special_tokens=True),
                },
            }
        ],
        "usage": {"prompt_tokens": ids.shape[1], "completion_tokens": len(new)},
    }
