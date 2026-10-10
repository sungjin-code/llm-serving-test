import http from "k6/http";
import { check } from "k6";
import { Counter } from "k6/metrics";

const tokens = new Counter("completion_tokens");
export const options = { vus: +__ENV.VUS, duration: __ENV.DURATION };

export default function () {
  const n = Math.floor(Math.random() * +__ENV.PROMPTS);
  const res = http.post(
    `${__ENV.TARGET}/v1/chat/completions`,
    JSON.stringify({
      model: __ENV.MODEL,
      max_tokens: +__ENV.MAX_TOKENS,
      temperature: 0,
      messages: [
        { role: "user", content: `Write a short story about the number ${n}.` },
      ],
      chat_template_kwargs: { enable_thinking: false },
    }),
    { headers: { "Content-Type": "application/json" }, timeout: "600s" },
  );
  if (
    check(res, {
      "status 200": (r) => r.status === 200,
    })
  )
    tokens.add(res.json().usage.completion_tokens);
}
