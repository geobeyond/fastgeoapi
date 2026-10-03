"""The jobs, a job and its results.

``app.*`` is imported at the top of ``tests.html_fixtures``, and nowhere else here.
"""

import pytest

from tests.html_fixtures import (
    RUNNING_JOB,
    SERVER_URL,
    add_running_job,
    config,
    fake_build,
    island_config,
    native_client,
    with_jobs,
)


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    directory = tmp_path_factory.mktemp("jobs")
    add_running_job(directory)
    client = native_client(with_jobs(config(), directory), fake_build(directory / "static"))
    done = client.post("/processes/hello-world/execution", json={"inputs": {"name": "Ada"}})
    return client, done.headers["location"].rsplit("/", 1)[1]


def _page(client, path, **params):
    return client.get(path, params={"f": "html", **params})


def test_the_jobs_are_rows_linked_to_their_pages(service):
    client, finished = service
    html = _page(client, "/jobs").text

    assert f'<a href="{SERVER_URL}/jobs/{finished}?f=html"><code>{finished}</code></a>' in html
    assert "<td>hello-world</td><td>successful</td>" in html
    assert "<td>hello-world</td><td>running</td>" in html


def test_a_finished_job_links_its_results_and_stops_following(service):
    client, finished = service
    html = _page(client, f"/jobs/{finished}").text

    assert f'href="{SERVER_URL}/jobs/{finished}/results?f=html"' in html
    assert "<fga-job-status>" not in html


def test_a_running_job_is_followed_from_its_page(service):
    client, _ = service
    html = _page(client, f"/jobs/{RUNNING_JOB}").text
    follow = island_config(html, "fga-job-status")

    assert follow["jobUrl"] == f"{SERVER_URL}/jobs/{RUNNING_JOB}?f=json"
    assert (follow["interval"], follow["labels"]["running"]) == (2000, "running")
    assert "<dd>50%</dd>" in html


def test_a_running_job_in_italian(service):
    client, _ = service
    html = _page(client, f"/jobs/{RUNNING_JOB}", lang="it").text

    assert island_config(html, "fga-job-status")["labels"]["running"] == "in esecuzione"
    assert "<dd>3 ott 2026" in html


def test_the_results_are_shown_as_json(service):
    client, finished = service
    html = _page(client, f"/jobs/{finished}/results").text

    assert "Hello Ada!" in html
    assert "<pre>{" in html


@pytest.mark.parametrize("path", ["/jobs/nope", f"/jobs/{RUNNING_JOB}/results"])
def test_a_missing_job_or_unready_results_keep_their_json(service, path):
    client, _ = service
    r = _page(client, path)

    assert (r.status_code, r.headers["content-type"]) == (404, "application/json")
