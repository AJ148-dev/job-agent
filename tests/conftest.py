from pathlib import Path

import pytest

from jobagent.config import Profile
from jobagent.models import JobExtraction, LLMMatch, RawPost

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def profile(tmp_path: Path) -> Profile:
    return Profile(
        resume_path=tmp_path / "resume.txt",
        resume_text="Python backend engineer, 2 years, FastAPI, Postgres.",
        target_roles=["Backend Engineer"],
        locations=["Bangalore", "Bengaluru"],
        min_years=0,
        max_years=3,
        must_have_skills=["Python"],
        exclude_keywords=["unpaid"],
    )


def make_post(external_id: str, text: str) -> RawPost:
    return RawPost(source="fake", external_id=external_id, text=text,
                   url=f"https://example.com/{external_id}")


class FakeLLM:
    """Answers by keyword so tests can steer each post's outcome."""

    def __init__(self, fail_on: str | None = None):
        self.calls = 0
        self.fail_on = fail_on

    def structured(self, system, user, schema):
        self.calls += 1
        if self.fail_on and self.fail_on in user:
            raise RuntimeError("llm down")
        if schema is JobExtraction:
            is_job = "hiring" in user.lower()
            return JobExtraction(
                is_job_opportunity=is_job, reason="test",
                role="Backend Engineer" if is_job else None, company="Acme",
                location="Bangalore", skills=["Python"], summary="Backend role.",
                min_years_experience=8 if "senior" in user.lower() else None,
            )
        if schema is LLMMatch:
            score = 40 if "weak" in user.lower() else 88
            return LLMMatch(score=score, matched_skills=["Python"], reasons="Good fit.")
        raise AssertionError(schema)


class FakeSource:
    name = "fake"

    def __init__(self, posts: list[RawPost]):
        self.posts = posts

    def fetch(self, limit: int) -> list[RawPost]:
        return self.posts[:limit]


class FakeNotifier:
    def __init__(self, fail: bool = False):
        self.sent: list[str] = []
        self.fail = fail

    def send(self, text: str) -> None:
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append(text)
