import hashlib
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from jobagent.models import JobExtraction, LLMMatch, RawPost

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    url TEXT,
    author TEXT,
    text TEXT NOT NULL,
    status TEXT NOT NULL,          -- skipped | not_job | job | error
    detail TEXT,
    first_seen_at TEXT NOT NULL,
    UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_posts_hash ON posts (content_hash);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL UNIQUE REFERENCES posts (id),
    job_json TEXT NOT NULL,
    match_json TEXT NOT NULL,
    score INTEGER NOT NULL,
    notified_at TEXT
);
"""


def content_hash(text: str) -> str:
    normalized = re.sub(r"https?://\S+", "", text.lower())
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Storage:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def is_seen(self, post: RawPost) -> bool:
        """True if this post, or one with the same text, was already processed.

        Posts that previously errored are not "seen", so they get retried.
        """
        row = self.conn.execute(
            """SELECT 1 FROM posts WHERE status != 'error'
               AND ((source = ? AND external_id = ?) OR content_hash = ?) LIMIT 1""",
            (post.source, post.external_id, content_hash(post.text)),
        ).fetchone()
        return row is not None

    def save_post(self, post: RawPost, status: str, detail: str | None = None) -> int:
        with self.conn:
            row = self.conn.execute(
                """INSERT INTO posts (source, external_id, content_hash, url, author, text,
                                      status, detail, first_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (source, external_id) DO UPDATE
                   SET status = excluded.status, detail = excluded.detail, text = excluded.text
                   RETURNING id""",
                (post.source, post.external_id, content_hash(post.text), post.url, post.author,
                 post.text, status, detail, _now()),
            ).fetchone()
        return row["id"]

    def save_job(self, post_id: int, job: JobExtraction, match: LLMMatch) -> int:
        with self.conn:
            row = self.conn.execute(
                """INSERT INTO jobs (post_id, job_json, match_json, score) VALUES (?, ?, ?, ?)
                   ON CONFLICT (post_id) DO UPDATE
                   SET job_json = excluded.job_json, match_json = excluded.match_json,
                       score = excluded.score
                   RETURNING id""",
                (post_id, job.model_dump_json(), match.model_dump_json(), match.score),
            ).fetchone()
        return row["id"]

    def pending_notifications(self, min_score: int) -> list[tuple[int, RawPost, JobExtraction, LLMMatch]]:
        rows = self.conn.execute(
            """SELECT j.id, j.job_json, j.match_json, p.source, p.external_id, p.url, p.author, p.text
               FROM jobs j JOIN posts p ON p.id = j.post_id
               WHERE j.notified_at IS NULL AND j.score >= ?
               ORDER BY j.score DESC""",
            (min_score,),
        ).fetchall()
        return [
            (
                r["id"],
                RawPost(source=r["source"], external_id=r["external_id"], url=r["url"],
                        author=r["author"], text=r["text"]),
                JobExtraction.model_validate_json(r["job_json"]),
                LLMMatch.model_validate_json(r["match_json"]),
            )
            for r in rows
        ]

    def mark_notified(self, job_id: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE jobs SET notified_at = ? WHERE id = ?", (_now(), job_id))

    def stats(self) -> dict[str, int]:
        out = {
            f"posts_{r['status']}": r["n"]
            for r in self.conn.execute("SELECT status, COUNT(*) AS n FROM posts GROUP BY status")
        }
        out["jobs_total"] = self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        out["jobs_notified"] = self.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE notified_at IS NOT NULL").fetchone()[0]
        return out
