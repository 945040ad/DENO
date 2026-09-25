"""Property-based contract tests: every v1 operation, fuzzed from the OpenAPI schema.

Checks: no 5xx for any generated input, responses match their declared schemas,
content types and status codes are documented. Runs against a real uvicorn
server (own event loop) on the test database, in dev-auth mode.
"""

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import schemathesis
import uvicorn
from hypothesis import HealthCheck, settings
from schemathesis.specs.openapi.checks import positive_data_acceptance

from deno_api.app import create_app
from deno_core.settings import Settings


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def server_url(migrated_url: str) -> Iterator[str]:
    app = create_app(
        Settings(
            environment="test",
            database_url=migrated_url,
            valkey_url="redis://127.0.0.1:6379/14",
            supabase_url="",  # dev auth: every call is the fixed dev user
            api_rate_limit_per_minute=100_000,
        )
    )
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started:
        if time.time() > deadline:
            pytest.fail("contract-test server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="module")
def api_schema(server_url: str) -> schemathesis.schemas.BaseSchema:
    return schemathesis.openapi.from_url(f"{server_url}/api/v1/openapi.json")


schema = schemathesis.pytest.from_fixture("api_schema")


@schema.parametrize()
@settings(max_examples=25, deadline=None, suppress_health_check=list(HealthCheck))
def test_v1_contract(case: schemathesis.Case) -> None:
    # The SSE endpoint streams until a run finishes; its contract is covered in test_v1.py.
    if case.path.endswith("/events"):
        return
    # Calls the hosted LLM (unavailable offline); its 503 path is covered by the error-envelope tests.
    if case.path.endswith("/story-bank/extract"):
        return
    # Stripe isn't configured in tests: checkout/portal answer 503 by design.
    if case.path in ("/api/v1/billing/checkout", "/api/v1/billing/portal"):
        return
    # `cursor` is an opaque server-issued token: arbitrary strings are rightly rejected (422),
    # which the positive-data check can't know. Every other check still applies.
    excluded = [positive_data_acceptance] if case.query and "cursor" in case.query else []
    # Story Bank numbers must literally appear in the story text: a cross-field rule the schema can't express.
    if case.method == "POST" and case.path == "/api/v1/stories":
        excluded = [positive_data_acceptance]
    # Titles made only of C1 control characters are cleaned to nothing; the generator's regex engine and
    # ours disagree on what those characters are, so it calls the resulting 422 a rejection of valid data.
    # Timezones are checked against the IANA database, which a JSON schema can't express.
    if case.method == "PATCH" and case.path in ("/api/v1/projects/{project_id}", "/api/v1/me"):
        excluded = [positive_data_acceptance]
    case.call_and_validate(timeout=10, excluded_checks=excluded)
