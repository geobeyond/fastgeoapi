"""The processes, a process, and what its page needs to run it.

``app.*`` is imported at the top of ``tests.html_fixtures``, and nowhere else here.
"""

import pytest

from tests.html_fixtures import (
    SERVER_URL,
    config,
    fake_build,
    island_config,
    native_client,
    with_echo,
)

EXECUTE = f"{SERVER_URL}/processes/hello-world/execution?f=json"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    return native_client(with_echo(config()), fake_build(tmp_path_factory.mktemp("static")))


def _page(client, path, **params):
    return client.get(path, params={"f": "html", **params}).text


def test_the_processes_are_cards_with_a_way_to_the_jobs(client):
    html = _page(client, "/processes")

    assert f'<h3><a href="{SERVER_URL}/processes/hello-world?f=html">Hello World</a></h3>' in html
    assert f'href="{SERVER_URL}/jobs?f=html"' in html


def test_a_process_describes_its_inputs_and_outputs(client):
    html = _page(client, "/processes/hello-world")

    assert "<h1>Hello World</h1>" in html
    assert "<td><code>name</code><br>Name</td><td>string · required</td>" in html
    assert "<td><code>echo</code><br>Hello, world</td><td>object</td>" in html


def test_the_run_island_gets_the_execution_url_and_the_inputs(client):
    run = island_config(_page(client, "/processes/hello-world"), "fga-process-run")

    assert run["executeUrl"] == EXECUTE
    assert run["inputs"]["name"]["schema"] == {"type": "string"}
    assert run["modes"] == ["sync-execute", "async-execute"]


def test_the_island_speaks_the_page_language(client):
    run = island_config(_page(client, "/processes/hello-world", lang="it"), "fga-process-run")

    assert run["messages"]["run"] == "Esegui"


def test_without_javascript_the_page_says_how_to_run_the_process(client):
    assert f"send a POST with the inputs to {EXECUTE}." in _page(client, "/processes/hello-world")


def test_markup_in_a_process_stays_text(client):
    html = _page(client, "/processes/echo")
    run = island_config(html, "fga-process-run")

    assert "<script>alert(1)</script>" not in html
    assert "<b>bold</b>" not in html
    assert "&amp;lt;" not in html  # escaped once, as the text reads, not twice
    assert run["inputs"]["anything"]["description"] == "Any JSON value </script><b>bold</b>"


def test_an_input_without_a_schema_is_listed(client):
    assert "<td><code>anything</code><br>Anything</td><td></td>" in _page(client, "/processes/echo")


def test_the_execution_url_runs_the_process(client):
    r = client.post("/processes/echo/execution", json={"inputs": {"anything": [1, 2]}})

    assert r.json() == {"echo": {"anything": [1, 2]}}
