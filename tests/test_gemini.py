import json

import httpx
import pytest

from jobagent.llm.gemini import GeminiClient
from jobagent.models import LLMMatch


def _ok(payload: dict) -> httpx.Response:
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]})


def _client(responses: list[httpx.Response]):
    requests, sleeps = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses.pop(0)

    http = httpx.Client(base_url="https://example.test", transport=httpx.MockTransport(handler))
    client = GeminiClient("key", "gemini-test", min_interval_s=0, http=http, sleep=sleeps.append)
    return client, requests, sleeps


def test_structured_output_request_and_parse():
    client, requests, _ = _client([_ok({"score": 81, "reasons": "fit"})])
    match = client.structured("sys", "user", LLMMatch)
    assert match.score == 81
    body = json.loads(requests[0].content)
    assert requests[0].url.path == "/models/gemini-test:generateContent"
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseJsonSchema"]["required"] == ["score", "reasons"]


def test_rate_limit_waits_for_retry_delay():
    limited = httpx.Response(429, text='{"error": {"details": [{"retryDelay": "17s"}]}}')
    client, _, sleeps = _client([limited, _ok({"score": 50, "reasons": "r"})])
    assert client.structured("s", "u", LLMMatch).score == 50
    assert sleeps == [18.0]


def test_invalid_json_is_retried_then_gives_up():
    bad = httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]})
    client, requests, _ = _client([bad] * 5)
    with pytest.raises(RuntimeError, match="no usable LLMMatch"):
        client.structured("s", "u", LLMMatch)
    assert len(requests) == 5


def test_client_error_is_not_retried():
    client, requests, _ = _client([httpx.Response(400, text="bad request")])
    with pytest.raises(RuntimeError, match="Gemini error 400"):
        client.structured("s", "u", LLMMatch)
    assert len(requests) == 1


def test_check_fails_for_model_that_cannot_generate():
    client, _, _ = _client([httpx.Response(404, text="no longer available to new users")])
    with pytest.raises(RuntimeError, match="unusable"):
        client.check()


def test_missing_key_is_a_clear_error():
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiClient("", "m")
