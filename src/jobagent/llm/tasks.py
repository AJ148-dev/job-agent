import json
import re

from jobagent.config import Profile
from jobagent.llm.ollama import LLM
from jobagent.models import JobExtraction, LLMMatch

RESUME_CHARS = 6000
POST_CHARS = 4000
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+\w")

EXTRACT_SYSTEM = """You read social media posts and decide whether they advertise a job opening.

A post IS a job opportunity only if someone is hiring: a company or person announcing open
roles, asking for applications or CVs, sharing a job link, or asking for referrals for an
open position they are filling.

A post is NOT a job opportunity if it is: someone announcing they got a new job, someone
looking for work ("open to work"), career advice, layoff news, event or course promotion,
or general industry commentary.

If it is a job opportunity, fill in every field the post mentions: the role title, company,
location, work mode, minimum years of experience, and all skills/technologies listed.
Use null only when the post truly does not say. Do not invent details."""

MATCH_SYSTEM = """You are a strict technical recruiter. Score how well a job fits a candidate,
from 0 to 100, using their resume and preferences.

Rubric:
- 85-100: role, seniority and core skills all match; candidate would be a strong applicant.
- 70-84: good fit with minor gaps.
- 50-69: partial fit; notable gaps in skills, seniority or role type.
- 0-49: poor fit or different field.

matched_skills and missing_skills must be short skill names. reasons is at most two sentences."""


def extract_job(llm: LLM, post_text: str) -> JobExtraction:
    job = llm.structured(EXTRACT_SYSTEM, f"POST:\n{post_text[:POST_CHARS]}", JobExtraction)
    if job.is_job_opportunity and not job.contact_email and (m := EMAIL_RE.search(post_text)):
        job.contact_email = m.group(0)
    return job


def judge_match(llm: LLM, job: JobExtraction, post_text: str, profile: Profile) -> LLMMatch:
    preferences = {
        "target_roles": profile.target_roles,
        "locations": profile.locations,
        "remote_ok": profile.remote_ok,
        "years_of_experience": f"{profile.min_years}-{profile.max_years or 'any'}",
        "must_have_skills": profile.must_have_skills,
        "nice_to_have_skills": profile.nice_to_have_skills,
    }
    job_fields = job.model_dump(exclude={"is_job_opportunity", "reason"})
    user = (
        f"CANDIDATE PREFERENCES:\n{json.dumps(preferences)}\n\n"
        f"CANDIDATE RESUME:\n{profile.resume_text[:RESUME_CHARS]}\n\n"
        f"JOB (extracted):\n{json.dumps(job_fields)}\n\n"
        f"ORIGINAL POST:\n{post_text[:POST_CHARS]}"
    )
    return llm.structured(MATCH_SYSTEM, user, LLMMatch)
