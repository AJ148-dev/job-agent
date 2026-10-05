import logging
import re
import time

import httpx
from pydantic import ValidationError

from jobagent.llm.ollama import T

log = logging.getLogger(__name__)

API_URL = "https://generativelanguage.googleapis.com/v1beta"
RETRY_DELAY_RE = re.compile(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"')


class GeminiClient:
    """Gemini via the REST API, with JSON-schema structured output.

    min_interval_s spaces out requests to stay under the free tier's per-minute limit;
    429 and 5xx responses are retried after the delay Google asks for.
    """

    def __init__(self, api_key: str, model: str, min_interval_s: float = 4.0, attempts: int = 5,
                 http: httpx.Client | None = None, sleep=time.sleep):
        if not api_key:
            raise ValueError("Set GEMINI_API_KEY in .env (get one at https://aistudio.google.com/apikey)")
        self.model = model
        self.min_interval_s = min_interval_s
        self.attempts = attempts
        self._sleep = sleep
        self._last_call = 0.0
        self._http = http or httpx.Client(base_url=API_URL, timeout=120,
                                          headers={"x-goog-api-key": api_key})

    def check(self) -> None:
        # A tiny real request: listed models can still refuse to generate for some accounts.
        resp = self._post({"contents": [{"role": "user", "parts": [{"text": "Reply with: ok"}]}]})
        if resp.status_code not in (200, 429):
            raise RuntimeError(f"Gemini model {self.model!r} unusable ({resp.status_code}): {resp.text[:200]}")

    def _post(self, payload: dict) -> httpx.Response:
        wait = self.min_interval_s - (time.monotonic() - self._last_call)
        if wait > 0:
            self._sleep(wait)
        self._last_call = time.monotonic()
        return self._http.post(f"/models/{self.model}:generateContent", json=payload)

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseJsonSchema": schema.model_json_schema(),
            },
        }
        for attempt in range(1, self.attempts + 1):
            resp = self._post(payload)
            if resp.status_code == 429 or resp.status_code >= 500:
                match = RETRY_DELAY_RE.search(resp.text)
                delay = float(match.group(1)) + 1 if match else 5 * 2 ** attempt
                log.warning("Gemini %d, retrying in %.0fs", resp.status_code, delay)
                self._sleep(delay)
                continue
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini error {resp.status_code}: {resp.text[:300]}")
            body = resp.json()
            try:
                text = body["candidates"][0]["content"]["parts"][0]["text"]
                return schema.model_validate_json(text)
            except (KeyError, IndexError, ValidationError):
                log.warning("Unusable %s from Gemini, retrying: %s", schema.__name__, str(body)[:200])
        raise RuntimeError(f"Gemini gave no usable {schema.__name__} after {self.attempts} attempts")
