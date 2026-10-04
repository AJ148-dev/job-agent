from jobagent.matching import excluded_keyword, passes_prefilter, too_much_experience
from jobagent.models import JobExtraction


def _job(**kw) -> JobExtraction:
    return JobExtraction(is_job_opportunity=True, reason="r", **kw)


def test_prefilter():
    assert passes_prefilter("We're hiring a backend dev")
    assert passes_prefilter("DM me your CV")
    assert not passes_prefilter("Great conference talk today, thanks all!")


def test_excluded_keyword(profile):
    assert excluded_keyword("This is an UNPAID internship", profile) == "unpaid"
    assert excluded_keyword("Paid role", profile) is None


def test_experience_gate(profile):  # profile.max_years == 3
    assert too_much_experience(_job(min_years_experience=4), profile) is None
    assert too_much_experience(_job(min_years_experience=5), profile) == "asks 5+ yrs (you: up to 3)"


def test_unstated_experience_is_kept(profile):
    assert too_much_experience(_job(), profile) is None


def test_location_and_skills_never_filter(profile):
    assert too_much_experience(_job(location="London", skills=["Cobol"]), profile) is None


def test_null_strings_cleaned():
    job = _job(company="null", skills=["null", "Python"], location="N/A")
    assert job.company is None and job.location is None and job.skills == ["Python"]
