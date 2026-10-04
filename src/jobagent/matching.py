import re

from jobagent.config import Profile
from jobagent.models import JobExtraction

# Cheap gate before any LLM call. Broad on purpose: the LLM makes the real decision.
JOB_SIGNALS = re.compile(
    r"hiring|looking for|join (?:our|my|the) team|open (?:role|position)s?|openings?|vacanc"
    r"|\bjobs?\b|apply|application|\bjd\b|job description|referral|\bpositions?\b"
    r"|opportunit|internship|\binterns?\b|recruit|\b(?:cv|resume)\b|careers?\b|\bctc\b",
    re.IGNORECASE,
)

def passes_prefilter(text: str) -> bool:
    return bool(JOB_SIGNALS.search(text))


def excluded_keyword(text: str, profile: Profile) -> str | None:
    lowered = text.lower()
    return next((k for k in profile.exclude_keywords if k.lower() in lowered), None)


def too_much_experience(job: JobExtraction, profile: Profile) -> str | None:
    """Reason to drop the job if it asks clearly more experience than the user has.

    Jobs that don't state experience are kept, so no opportunity is missed.
    """
    if (profile.max_years is not None and job.min_years_experience is not None
            and job.min_years_experience > profile.max_years + 1):
        return f"asks {job.min_years_experience}+ yrs (you: up to {profile.max_years})"
    return None
