from jobagent.llm.tasks import extract_job
from jobagent.models import JobExtraction


class OneShotLLM:
    def __init__(self, result):
        self.result = result

    def structured(self, system, user, schema):
        return self.result


def test_email_filled_from_post_when_llm_misses_it():
    llm = OneShotLLM(JobExtraction(is_job_opportunity=True, reason="r"))
    job = extract_job(llm, "Hiring! Send CV to talent@acme.io.")
    assert job.contact_email == "talent@acme.io"


def test_email_in_apply_url_moved_to_contact():
    job = JobExtraction(is_job_opportunity=True, reason="r", apply_url="jobs@x.com")
    assert job.apply_url is None and job.contact_email == "jobs@x.com"
