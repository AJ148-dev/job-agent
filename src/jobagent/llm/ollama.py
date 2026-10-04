import logging
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLM(Protocol):
    def structured(self, system: str, user: str, schema: type[T]) -> T: ...


class OllamaClient:
    def __init__(self, url: str, model: str, timeout: float = 300.0, attempts: int = 2):
        self.model = model
        self.attempts = attempts
        self._http = httpx.Client(base_url=url, timeout=timeout)

    def check(self) -> None:
        names = [m["name"] for m in self._http.get("/api/tags").raise_for_status().json()["models"]]
        if self.model not in names:
            raise RuntimeError(f"Ollama model {self.model!r} not pulled. Run: ollama pull {self.model}")

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema.model_json_schema(),
            "stream": False,
            "options": {"temperature": 0},
        }
        for attempt in range(1, self.attempts + 1):
            content = self._http.post("/api/chat", json=payload).raise_for_status().json()["message"]["content"]
            try:
                return schema.model_validate_json(content)
            except ValidationError:
                if attempt == self.attempts:
                    raise
                log.warning("Invalid %s from LLM, retrying: %s", schema.__name__, content[:200])
        raise AssertionError("unreachable")
