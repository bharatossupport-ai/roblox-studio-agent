"""Minimal OpenAI-compatible chat client (requests only, no SDK)."""
from __future__ import annotations

import time

import requests


class LLMError(RuntimeError):
    pass


class ChatClient:
    def __init__(self, base_url: str, api_key: str = "", model: str = "", timeout: float = 180):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.model = model
        self.timeout = timeout

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """Return the assistant message dict (content, tool_calls)."""
        if not self.base_url:
            raise LLMError("Set a base URL for this provider in Settings.")
        url = self.base_url + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        # The keyless free endpoint rejects any Authorization header, so only send a real key.
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body: dict = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        last_err = ""
        for attempt in range(4):
            try:
                r = requests.post(url, json=body, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                last_err = f"Network error: {e}"
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last_err = f"HTTP {r.status_code}: {r.text[:300]}"
                wait = float(r.headers.get("retry-after", 0) or 0) or 4 * (attempt + 1)
                time.sleep(min(wait, 30))
                continue
            if r.status_code >= 400:
                raise LLMError(f"HTTP {r.status_code}: {r.text[:500]}")
            data = r.json()
            choices = data.get("choices") or []
            if not choices:
                raise LLMError(f"The AI returned no answer: {str(data)[:300]}")
            return choices[0].get("message") or {}
        raise LLMError(last_err or "The AI didn't respond.")


# Keyless free backends, best first. Limits are per IP address (checked Nov 2026):
#   Kilo AI Gateway: ~200 requests/hour   OVHcloud AI Endpoints: ~2 requests/minute per model
#   Pollinations: ~1 reply / 45 s
FREE_BACKENDS = [
    ("Kilo free", "https://ai-gateway.kilo.ai/api/v1", "kilo-auto/free"),
    ("OVH Qwen3.5", "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1", "Qwen3.5-397B-A17B"),
    ("OVH gpt-oss-120b", "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1", "gpt-oss-120b"),
    ("OVH Llama 3.3 70B", "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1", "Meta-Llama-3_3-70B-Instruct"),
    ("Pollinations", "https://text.pollinations.ai/openai", "openai-fast"),
]


class FreePoolClient:
    """Rotates across keyless free endpoints; sticks with whichever answered last."""

    def __init__(self, timeout: float = 180, max_wait_s: float = 300, on_status=None):
        self.timeout = timeout
        self.max_wait_s = max_wait_s
        self.on_status = on_status or (lambda msg: None)
        self.start = 0
        self.model = "free-pool"
        self.last_backend = ""

    def _try(self, base: str, model: str, messages: list[dict], tools) -> dict | None:
        body: dict = {"model": model, "messages": messages}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        try:
            r = requests.post(base + "/chat/completions", json=body,
                              headers={"Content-Type": "application/json"}, timeout=self.timeout)
        except requests.RequestException:
            return None
        if r.status_code != 200:
            return None
        try:
            choices = r.json().get("choices") or []
        except ValueError:
            return None
        if not choices:
            return None
        msg = choices[0].get("message") or {}
        if not (msg.get("content") or msg.get("tool_calls")):
            return None  # empty reply (reasoning model ran out of tokens): try another
        return msg

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        deadline = time.time() + self.max_wait_s
        n = len(FREE_BACKENDS)
        while True:
            for i in range(n):
                idx = (self.start + i) % n
                name, base, model = FREE_BACKENDS[idx]
                msg = self._try(base, model, messages, tools)
                if msg is not None:
                    self.start = idx
                    self.last_backend = name
                    return msg
            if time.time() > deadline:
                raise LLMError(
                    "All free AI servers are busy or at their limit right now. Wait a few minutes, "
                    "or add a free Gemini or Groq key in AI settings for faster, steadier answers."
                )
            self.on_status("Free AI servers are busy, retrying in 20 seconds…")
            time.sleep(20)
