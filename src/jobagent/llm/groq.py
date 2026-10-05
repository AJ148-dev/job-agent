import json
import logging
import time

import httpx
from pydantic import ValidationError

from jobagent.llm.ollama import T

log = logging.getLogger(__name__)

API_URL = "https://api.groq.com/openai/v1"
MAX_RETRY_WAIT_S = 60


class GroqClient:
    """Groq via its OpenAI-compatible chat API, with JSON-schema structured output."""

    def __init__(self, api_key: str, model: str, min_interval_s: float = 2.0, attempts: int = 4,
                 http: httpx.Client | None = None, sleep=time.sleep):
        if not api_key:
            raise ValueError("Set GROQ_API_KEY in .env (get one at https://console.groq.com/keys)")
        self.model = model
        self.min_interval_s = min_interval_s
        self.attempts = attempts
        self._sleep = sleep
        self._last_call = 0.0
        self._http = http or httpx.Client(base_url=API_URL, timeout=120,
                                          headers={"Authorization": f"Bearer {api_key}"})

    def _post(self, payload: dict) -> httpx.Response:
        wait = self.min_interval_s - (time.monotonic() - self._last_call)
        if wait > 0:
            self._sleep(wait)
        self._last_call = time.monotonic()
        return self._http.post("/chat/completions", json=payload)

    def check(self) -> None:
        resp = self._post({"model": self.model, "max_completion_tokens": 5,
                           "messages": [{"role": "user", "content": "Reply with: ok"}]})
        if resp.status_code not in (200, 429):
            raise RuntimeError(f"Groq model {self.model!r} unusable ({resp.status_code}): {resp.text[:200]}")

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()}},
        }
        for attempt in range(1, self.attempts + 1):
            resp = self._post(payload)
            if resp.status_code == 429 or resp.status_code >= 500:
                delay = float(resp.headers.get("retry-after") or 5 * 2 ** attempt)
                if delay > MAX_RETRY_WAIT_S:
                    raise RuntimeError(f"Groq rate limit: retry after {delay:.0f}s")
                log.warning("Groq %d, retrying in %.0fs", resp.status_code, delay)
                self._sleep(delay)
                continue
            if resp.status_code != 200:
                raise RuntimeError(f"Groq error {resp.status_code}: {resp.text[:300]}")
            try:
                content = resp.json()["choices"][0]["message"]["content"]
                return schema.model_validate(json.loads(content))
            except (KeyError, IndexError, ValueError, ValidationError):
                log.warning("Unusable %s from Groq, retrying: %s", schema.__name__, resp.text[:200])
        raise RuntimeError(f"Groq gave no usable {schema.__name__} after {self.attempts} attempts")
