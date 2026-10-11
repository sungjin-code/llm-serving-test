import json
import os
import random
import statistics

from huggingface_hub import hf_hub_download
from transformers import AutoTokenizer

N, TURNS = 1000, 5
BUDGET = int(os.environ["MAX_MODEL_LEN"]) - int(os.environ["MAX_TOKENS"])
ROLES = ("user", "assistant")
FROM = {"human": "user", "gpt": "assistant"}

tok = AutoTokenizer.from_pretrained(os.environ["MODEL"])
system = open("k6/system_prompt.txt").read()


def prompt_len(msgs):
    return len(
        tok.apply_chat_template(
            [{"role": "system", "content": system}, *msgs],
            add_generation_prompt=True,
            enable_thinking=False,
            return_dict=True,
        )["input_ids"]
    )


path = hf_hub_download(
    "anon8231489123/ShareGPT_Vicuna_unfiltered",
    "ShareGPT_V3_unfiltered_cleaned_split.json",
    repo_type="dataset",
)
convs = json.load(open(path))
random.Random(0).shuffle(convs)

# Each session: user/assistant alternating, ending on a user turn. The dataset's own
# assistant replies are kept as history so every server sees identical prompts.
sessions, turn_lens = [], []
for c in convs:
    msgs = []
    for t in c["conversations"][: 2 * TURNS - 1]:
        if FROM.get(t["from"]) != ROLES[len(msgs) % 2] or not t["value"].strip():
            break
        msgs.append({"role": ROLES[len(msgs) % 2], "content": t["value"]})
    if len(msgs) % 2 == 0:
        msgs = msgs[:-1]
    while msgs and prompt_len(msgs) > BUDGET:
        msgs = msgs[:-2]
    if not msgs:
        continue
    sessions.append(msgs)
    turn_lens.append([prompt_len(msgs[: i + 1]) for i in range(0, len(msgs), 2)])
    if len(sessions) == N:
        break

with open("k6/sessions.js", "w") as f:
    f.write(f"const SYSTEM = {json.dumps(system)};\n")
    f.write(f"const SESSIONS = {json.dumps(sessions)};\n")

assert len(sessions) == N
for s in sessions:
    assert len(s) % 2 == 1 and len(s) <= 2 * TURNS - 1
    assert all(m["role"] == ROLES[i % 2] for i, m in enumerate(s))
lens = [n for t in turn_lens for n in t]
assert max(lens) <= BUDGET

# Expected vLLM prefix-cache hit: turn 1 can reuse the system prompt, turn k the
# whole turn k-1 prompt (block granularity and the reply mismatch make it a bit lower).
sys_len = prompt_len([])
shared = sum(sys_len + sum(t[:-1]) for t in turn_lens)
print(f"sessions={N} requests={len(lens)} turns/session={len(lens) / N:.2f}")
print(f"system prompt tokens={sys_len}")
print(
    f"prompt tokens mean={statistics.mean(lens):.0f} "
    f"p50={statistics.median(lens):.0f} max={max(lens)}"
)
print(f"expected prefix hit: system only={sys_len * len(lens) / sum(lens):.1%}")
print(f"expected prefix hit: system + previous turn={shared / sum(lens):.1%}")
