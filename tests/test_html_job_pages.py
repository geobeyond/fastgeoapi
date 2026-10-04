"""The jobs, a job and its results.

``app.*`` is imported inside ``tests.html_fixtures.native_client``, and nowhere else here.
"""

import re

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

    process = f'<td><a href="{SERVER_URL}/processes/hello-world?f=html">hello-world</a></td>'

    assert f'<a href="{SERVER_URL}/jobs/{finished}?f=html"><code>{finished}</code></a>' in html
    assert f"{process}<td>successful</td>" in html
    assert f"{process}<td>running</td>" in html


def test_the_jobs_show_their_start_duration_and_message(service):
    client, _ = service
    html = _page(client, "/jobs").text

    assert "<th>Started</th><th>Duration</th><th>Progress</th><th>Message</th>" in html
    assert "<td>50%</td><td>Halfway there</td>" in html


def test_a_job_running_for_days_counts_its_hours(service):
    client, _ = service
    html = _page(client, "/jobs", lang="it").text
    running = html[html.index("Halfway there") - 200 : html.index("Halfway there")]

    assert re.search(r"<td>\d{2,}:\d\d:\d\d</td>", running)
    assert "day" not in running


def test_the_jobs_come_a_page_at_a_time(service):
    client, _ = service
    html = _page(client, "/jobs", limit=1).text

    assert '<option value="1" selected>1</option>' in html
    assert '<option value="20">20</option>' in html
    assert f'<a rel="next" href="{SERVER_URL}/jobs?offset=1&amp;limit=1&amp;f=html">' in html


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
    assert "<dt>Duration</dt>" in html


def test_a_job_shows_its_parameters(service):
    client, _ = service
    html = _page(client, f"/jobs/{RUNNING_JOB}").text

    assert "<h2>Parameters</h2>" in html
    assert "&#34;name&#34;: &#34;Ada&#34;" in html


def test_a_finished_job_states_how_long_it_took(service):
    client, finished = service

    assert "<dt>Duration</dt><dd>0:00:0" in _page(client, f"/jobs/{finished}").text


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
