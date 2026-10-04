from typing import Protocol

from jobagent.models import RawPost


class Source(Protocol):
    """A place job posts come from. Implement this to add a new source."""

    name: str

    def fetch(self, limit: int) -> list[RawPost]: ...
