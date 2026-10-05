import json

import httpx
import pytest

from jobagent.llm.fallback import FallbackLLM
from jobagent.llm.gemini import GeminiClient
from jobagent.llm.groq import GroqClient
from jobagent.models import LLMMatch


def _groq(responses: list[httpx.Response]):
    requests, sleeps = [], []

    def handler(request):
        requests.append(request)
        return responses.pop(0)

    http = httpx.Client(base_url="https://example.test", transport=httpx.MockTransport(handler))
    return GroqClient("key", "groq-test", min_interval_s=0, http=http, sleep=sleeps.append), requests, sleeps


def _chat(payload) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})


def test_groq_request_and_parse():
    client, requests, _ = _groq([_chat({"score": 77, "reasons": "ok"})])
    assert client.structured("sys", "user", LLMMatch).score == 77
    body = json.loads(requests[0].content)
    assert body["model"] == "groq-test" and body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["response_format"]["json_schema"]["name"] == "LLMMatch"


def test_groq_short_rate_limit_waits_long_one_fails_fast():
    client, _, sleeps = _groq([httpx.Response(429, headers={"retry-after": "3"}), _chat({"score": 1, "reasons": "r"})])
    assert client.structured("s", "u", LLMMatch).score == 1 and sleeps == [3.0]

    client, _, _ = _groq([httpx.Response(429, headers={"retry-after": "3600"})])
    with pytest.raises(RuntimeError, match="retry after 3600"):
        client.structured("s", "u", LLMMatch)


def test_gemini_daily_limit_fails_fast():
    def handler(request):
        return httpx.Response(429, text='{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}')

    sleeps = []
    http = httpx.Client(base_url="https://example.test", transport=httpx.MockTransport(handler))
    client = GeminiClient("k", "m", min_interval_s=0, http=http, sleep=sleeps.append)
    with pytest.raises(RuntimeError, match="daily"):
        client.structured("s", "u", LLMMatch)
    assert sleeps == []


class Stub:
    def __init__(self, fail: bool, name: str):
        self.fail, self.name, self.calls = fail, name, 0

    def check(self):
        if self.fail:
            raise RuntimeError("down")

    def structured(self, system, user, schema):
        self.calls += 1
        if self.fail:
            raise RuntimeError("limit")
        return LLMMatch(score=50, reasons=self.name)


def test_fallback_switches_and_stays_on_backup():
    primary, backup = Stub(True, "primary"), Stub(False, "backup")
    llm = FallbackLLM(primary, backup)
    assert llm.structured("s", "u", LLMMatch).reasons == "backup"
    assert llm.structured("s", "u", LLMMatch).reasons == "backup"
    assert primary.calls == 1 and backup.calls == 2


def test_fallback_uses_primary_when_healthy_and_check_switches():
    primary, backup = Stub(False, "primary"), Stub(False, "backup")
    assert FallbackLLM(primary, backup).structured("s", "u", LLMMatch).reasons == "primary"

    llm = FallbackLLM(Stub(True, "primary"), backup)
    llm.check()
    assert llm.structured("s", "u", LLMMatch).reasons == "backup"
