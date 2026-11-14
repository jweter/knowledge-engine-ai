"""Cross-repo contract check: AI's adapter against Core's own golden fixture.

Every other online-evidence test in this repository hand-authors its own bundle
JSON, so a silent field-level drift between AI's and Core's independently
maintained implementations of `ke-online-evidence/v1` would go undetected.
This test instead loads the fixture `knowledge-engine-core` committed at
`tests/fixtures/online_evidence/` (vendored here; see the adjacent README.md
for the exact source commit) and parses it with no network access and no
pre-ingested corpus.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from knowledge_engine_ai.copilot.online_evidence_adapter import (
    parse_content_checked_online_evidence,
)
from knowledge_engine_ai.copilot.online_report import build_online_research_report

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "online_evidence"


def _load_bundle_and_contents() -> tuple[dict[str, Any], dict[str, str]]:
    bundle = json.loads((FIXTURE_DIR / "bundle.json").read_text(encoding="utf-8"))
    contents: dict[str, str] = {}
    for source in bundle["sources"]:
        if source["status"] != "retrieved":
            continue
        content_path = FIXTURE_DIR / "contents" / f"{source['content_sha256']}.txt"
        contents[source["source_id"]] = content_path.read_text(encoding="utf-8")
    return bundle, contents


def test_core_golden_fixture_parses_unmodified() -> None:
    bundle, contents = _load_bundle_and_contents()
    assert contents, "fixture must vendor at least one retrieved source's content"

    evidence = parse_content_checked_online_evidence(bundle, contents)

    assert evidence.question == bundle["question"]
    by_status = {source.status for source in evidence.sources}
    assert by_status == {"retrieved", "failed", "unavailable"}

    by_id = {source.source_id: source for source in evidence.sources}
    for raw_source in bundle["sources"]:
        source = by_id[raw_source["source_id"]]
        assert source.status == raw_source["status"]
        assert source.failure_reason == raw_source["failure_reason"]
        assert source.content_sha256 == raw_source["content_sha256"]

    assert len(evidence.excerpts) == len(bundle["excerpts"])
    assert len(evidence.claims) == len(bundle["claims"])


def test_core_golden_fixture_projects_missing_failed_and_unavailable_sources() -> None:
    bundle, contents = _load_bundle_and_contents()
    evidence = parse_content_checked_online_evidence(bundle, contents)

    report = build_online_research_report(evidence, search_run_id="core-fixture-run")

    non_retrieved = [s for s in evidence.sources if s.status != "retrieved"]
    assert non_retrieved, "fixture must vendor at least one failed/unavailable source"
    for source in non_retrieved:
        assert source.status in {"failed", "unavailable"}
        expected = f"Source {source.source_id} {source.status}: {source.failure_reason}"
        assert expected in report.missing_evidence
