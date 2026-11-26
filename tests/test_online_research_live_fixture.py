"""Real, non-mocked subprocess proof against Core's published fixture harness.

`knowledge-engine-core`'s `ke online-evidence-fixture-server` command exists
specifically so knowledge-engine-ai and knowledge-engine-web can run their own
real pipeline against a known Core response instead of mocking the Core CLI
boundary -- its own docstring says this repository "still owes" exactly this
test (see `docs/online_evidence_contract.md` and
`knowledge_engine/entrypoint.py::online_evidence_fixture_server` in Core).
Every other online-evidence test in this repository calls
`knowledge_engine_ai.ke_client.online_research_evidence` through a
monkeypatched `_run_ke_command`/`subprocess.run`, or parses a hand-authored or
vendored bundle directly -- none of them actually exec real `ke` subprocesses
end to end. This module does: real `ke online-evidence-fixture-server`, real
`ke online-research --fixture-server-port ...`, real `ke
online-evidence-validate`, through this project's own unmodified
`online_research_evidence` bridge and `build_online_research_report`
projection.

Skips cleanly when `ke` is not on `PATH` (knowledge-engine-core is not
installed in this environment) rather than failing -- the same condition
`ke_client.py`'s own `KeCommandError` messages already describe. CI wires
this up by installing knowledge-engine-core alongside this repository; see
`.github/workflows/online-evidence-live-fixture.yml`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterator

import pytest

from knowledge_engine_ai.copilot.online_report import build_online_research_report
from knowledge_engine_ai.copilot.research_state import ResearchState
from knowledge_engine_ai.ke_client import KeCommandError, online_research_evidence

pytestmark = pytest.mark.skipif(
    shutil.which("ke") is None,
    reason="knowledge-engine-core's `ke` CLI is not installed/on PATH; this is a real, "
    "non-mocked integration test against it, not a unit test -- see this module's "
    "docstring and .github/workflows/online-evidence-live-fixture.yml.",
)

_QUESTION = "Does semaglutide reduce body weight versus placebo?"


@pytest.fixture
def fixture_server() -> Iterator[subprocess.Popen[str]]:
    server = subprocess.Popen(
        ["ke", "online-evidence-fixture-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        yield server
    finally:
        assert server.stdin is not None
        server.stdin.close()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.terminate()
            server.wait(timeout=5)


def _read_announcement(server: subprocess.Popen[str]) -> dict[str, object]:
    assert server.stdout is not None
    line = server.stdout.readline()
    if not line:
        stderr = server.stderr.read() if server.stderr is not None else ""
        raise AssertionError(f"fixture server produced no announcement; stderr={stderr!r}")
    payload = json.loads(line)
    assert isinstance(payload, dict)
    return payload


def test_online_research_evidence_against_real_fixture_server(
    fixture_server: subprocess.Popen[str],
) -> None:
    announcement = _read_announcement(fixture_server)
    port = announcement["port"]
    assert isinstance(port, int)
    pages = announcement["pages"]
    assert isinstance(pages, dict)
    assert set(pages) == {"retrievable", "http_500", "oversized"}

    result = online_research_evidence(_QUESTION, max_sources=3, fixture_server_port=port)

    evidence = result.evidence
    assert result.search_run_id.strip()
    assert evidence.question == _QUESTION
    # Core's fixture discovery provider names each candidate "doi:10.1/<good|broken|huge>"
    # (knowledge_engine/online_evidence_fixture_client.py); the bundle records that pinned
    # canonical source identity, not the loopback fixture URL retrieval actually used.
    by_id = {s.source_id: s for s in evidence.sources}
    assert set(by_id) == {"doi:10.1/good", "doi:10.1/broken", "doi:10.1/huge"}

    good = by_id["doi:10.1/good"]
    assert good.status == "retrieved"
    assert good.content_sha256 is not None

    broken = by_id["doi:10.1/broken"]
    assert broken.status == "failed"
    assert broken.content_sha256 is None
    assert broken.failure_reason is not None and "500" in broken.failure_reason

    # Core's fixture server always fails the oversized page (knowledge-engine-core #611),
    # whether or not the consumer passes --max-response-mb.
    huge = by_id["doi:10.1/huge"]
    assert huge.status == "failed"
    assert huge.failure_reason is not None and "exceeds 100000 bytes" in huge.failure_reason

    # Core's own documentation records claims as always empty from a bare
    # retrieval run (claim synthesis is analysis, not retrieval) -- proven
    # here against a real run rather than assumed.
    assert evidence.claims == ()

    report = build_online_research_report(evidence, search_run_id=result.search_run_id)
    assert report.research_state == ResearchState.INSUFFICIENT_EVIDENCE.value
    assert "Core supplied no claims for this question." in report.missing_evidence
    non_retrieved = [s for s in evidence.sources if s.status != "retrieved"]
    assert non_retrieved
    for source in non_retrieved:
        expected = f"Source {source.source_id} {source.status}: {source.failure_reason}"
        assert expected in report.missing_evidence


def test_online_research_evidence_fixture_mode_rejects_providers(
    fixture_server: subprocess.Popen[str],
) -> None:
    announcement = _read_announcement(fixture_server)
    port = announcement["port"]
    assert isinstance(port, int)

    with pytest.raises(KeCommandError, match="fixture mode cannot combine with providers"):
        online_research_evidence(
            _QUESTION, providers="pubmed", fixture_server_port=port, max_sources=3
        )
