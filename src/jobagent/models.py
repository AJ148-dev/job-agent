from typing import Literal

from pydantic import BaseModel, Field, model_validator


class RawPost(BaseModel):
    source: str
    external_id: str
    text: str
    url: str | None = None
    author: str | None = None
    posted_at: str | None = None


class JobExtraction(BaseModel):
    """LLM output: is this a hiring post, and if so, what is the job.

    Field descriptions are part of the JSON schema sent to the LLM.
    """

    is_job_opportunity: bool
    reason: str = Field(description="One short sentence explaining the decision.")
    role: str | None = Field(None, description="Job title being hired for, e.g. 'Backend Engineer'.")
    company: str | None = Field(None, description="Hiring company name.")
    location: str | None = Field(None, description="City or country of the job.")
    work_mode: Literal["onsite", "hybrid", "remote", "unknown"] = "unknown"
    min_years_experience: int | None = Field(None, description="Minimum years of experience required.")
    skills: list[str] = Field(default_factory=list,
                              description="Every technology, language, framework or tool mentioned.")
    apply_url: str | None = Field(None, description="An http(s) link to apply, copied from the post.")
    contact_email: str | None = Field(None, description="Email address to send applications to.")
    summary: str = Field("", description="One or two plain sentences describing the job.")

    @model_validator(mode="after")
    def _fix_links(self) -> "JobExtraction":
        if self.apply_url and not self.apply_url.startswith("http"):
            if "@" in self.apply_url and not self.contact_email:
                self.contact_email = self.apply_url
            self.apply_url = None
        return self


class LLMMatch(BaseModel):
    """LLM output: how well the job fits the candidate."""

    score: int = Field(ge=0, le=100)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    reasons: str


class MatchResult(BaseModel):
    llm_score: int
    score: int
    matched_skills: list[str]
    missing_skills: list[str]
    reasons: str
    penalties: list[str] = Field(default_factory=list)
