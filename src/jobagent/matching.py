import re

from jobagent.config import Profile
from jobagent.models import JobExtraction, LLMMatch, MatchResult

# Cheap gate before any LLM call. Broad on purpose: the LLM makes the real decision.
JOB_SIGNALS = re.compile(
    r"hiring|looking for|join (?:our|my|the) team|open (?:role|position)s?|openings?|vacanc"
    r"|\bjobs?\b|apply|application|\bjd\b|job description|referral|\bpositions?\b"
    r"|opportunit|internship|\binterns?\b|recruit|\b(?:cv|resume)\b|careers?\b|\bctc\b",
    re.IGNORECASE,
)

OVER_EXPERIENCE_PENALTY = 25
LOCATION_PENALTY = 20
MUST_HAVE_PENALTY = 15


def passes_prefilter(text: str) -> bool:
    return bool(JOB_SIGNALS.search(text))


def excluded_keyword(text: str, profile: Profile) -> str | None:
    lowered = text.lower()
    return next((k for k in profile.exclude_keywords if k.lower() in lowered), None)


def final_score(job: JobExtraction, llm_match: LLMMatch, profile: Profile) -> MatchResult:
    """Apply the user's hard preferences on top of the LLM's fit score."""
    penalties: list[str] = []
    score = llm_match.score

    if (profile.max_years is not None and job.min_years_experience is not None
            and job.min_years_experience > profile.max_years + 1):
        score -= OVER_EXPERIENCE_PENALTY
        penalties.append(f"asks {job.min_years_experience}+ yrs (you: up to {profile.max_years})")

    remote_fine = profile.remote_ok and job.work_mode == "remote"
    if profile.locations and job.location and not remote_fine:
        if not any(loc.lower() in job.location.lower() for loc in profile.locations):
            score -= LOCATION_PENALTY
            penalties.append(f"location {job.location} not in preferences")

    if profile.must_have_skills and job.skills:
        job_skills = " ".join(job.skills).lower()
        if not any(s.lower() in job_skills for s in profile.must_have_skills):
            score -= MUST_HAVE_PENALTY
            penalties.append("none of your must-have skills listed")

    return MatchResult(
        llm_score=llm_match.score,
        score=max(0, min(100, score)),
        matched_skills=llm_match.matched_skills,
        missing_skills=llm_match.missing_skills,
        reasons=llm_match.reasons,
        penalties=penalties,
    )
