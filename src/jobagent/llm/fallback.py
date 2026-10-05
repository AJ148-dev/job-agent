import logging

from jobagent.llm.ollama import LLM, T

log = logging.getLogger(__name__)


class FallbackLLM:
    """Use the primary LLM; on any failure switch to the backup for the rest of this run."""

    def __init__(self, primary: LLM, backup: LLM):
        self.primary = primary
        self.backup = backup
        self.current = primary

    def check(self) -> None:
        try:
            self.primary.check()
        except Exception as e:
            log.warning("Primary LLM unavailable (%s); using backup", e)
            self.current = self.backup
            self.backup.check()

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        if self.current is self.primary:
            try:
                return self.primary.structured(system, user, schema)
            except Exception as e:
                log.warning("Primary LLM failed (%s); switching to backup for the rest of this run", e)
                self.current = self.backup
        return self.backup.structured(system, user, schema)
