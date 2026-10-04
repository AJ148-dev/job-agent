from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from pypdf import PdfReader


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    data_dir: Path = Path("data")
    profile_path: Path = Path("profile.yaml")
    max_posts_per_run: int = 60
    # "chrome" drives the installed Google Chrome; empty uses Playwright's bundled Chromium.
    browser_channel: str = "chrome"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobagent.db"

    @property
    def browser_profile_dir(self) -> Path:
        return self.data_dir / "browser-profile"


class Profile(BaseModel):
    resume_path: Path
    target_roles: list[str] = []
    locations: list[str] = []
    remote_ok: bool = True
    min_years: int = 0
    max_years: int | None = None
    must_have_skills: list[str] = []
    nice_to_have_skills: list[str] = []
    exclude_keywords: list[str] = []
    min_score: int = 0
    resume_text: str = ""


def read_resume(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages).strip()
    return path.read_text(encoding="utf-8").strip()


def load_profile(path: Path) -> Profile:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    profile = Profile(**data)
    if not profile.resume_path.is_absolute():
        profile.resume_path = path.parent / profile.resume_path
    profile.resume_text = read_resume(profile.resume_path)
    if not profile.resume_text:
        raise ValueError(f"No text could be extracted from resume {profile.resume_path}")
    return profile
