from jobagent.matching import excluded_keyword, final_score, passes_prefilter
from jobagent.models import JobExtraction, LLMMatch

LLM_OK = LLMMatch(score=85, reasons="fit")


def _job(**kw) -> JobExtraction:
    return JobExtraction(is_job_opportunity=True, reason="r", **kw)


def test_prefilter():
    assert passes_prefilter("We're hiring a backend dev")
    assert passes_prefilter("DM me your CV")
    assert not passes_prefilter("Great conference talk today, thanks all!")


def test_excluded_keyword(profile):
    assert excluded_keyword("This is an UNPAID internship", profile) == "unpaid"
    assert excluded_keyword("Paid role", profile) is None


def test_no_penalty_for_good_fit(profile):
    result = final_score(_job(location="Bengaluru, India", min_years_experience=2, skills=["Python"]), LLM_OK, profile)
    assert result.score == 85 and result.penalties == []


def test_penalties_stack(profile):
    job = _job(location="London", min_years_experience=8, skills=["Java"])
    result = final_score(job, LLM_OK, profile)
    assert result.score == 85 - 25 - 20 - 15
    assert len(result.penalties) == 3


def test_remote_skips_location_penalty(profile):
    result = final_score(_job(location="London", work_mode="remote"), LLM_OK, profile)
    assert result.score == 85


def test_unknown_fields_not_penalised(profile):
    assert final_score(_job(), LLM_OK, profile).score == 85
