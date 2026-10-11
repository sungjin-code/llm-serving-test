import http from "k6/http";
import { check } from "k6";
import exec from "k6/execution";
import { Counter } from "k6/metrics";

const completion = new Counter("completion_tokens");
const prompt = new Counter("prompt_tokens");
export const options = { vus: +__ENV.VUS, duration: __ENV.DURATION };

// One iteration replays one ShareGPT session turn by turn. SYSTEM and SESSIONS
// are defined in k6/sessions.js, which `make chat` appends to this script.
export default function () {
  const s = SESSIONS[exec.scenario.iterationInTest % SESSIONS.length];
  for (let i = 0; i < s.length; i += 2) {
    const res = http.post(
      `${__ENV.TARGET}/v1/chat/completions`,
      JSON.stringify({
        model: __ENV.MODEL,
        max_tokens: +__ENV.MAX_TOKENS,
        temperature: 0,
        messages: [{ role: "system", content: SYSTEM }, ...s.slice(0, i + 1)],
        chat_template_kwargs: { enable_thinking: false },
      }),
      { headers: { "Content-Type": "application/json" }, timeout: "600s" },
    );
    if (!check(res, { "status 200": (r) => r.status === 200 })) return;
    const usage = res.json().usage;
    completion.add(usage.completion_tokens);
    prompt.add(usage.prompt_tokens);
  }
}
