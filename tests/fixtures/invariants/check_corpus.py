"""Validate fixture metadata without implementing deferred invariants."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
REGISTER = ROOT / "architecture" / "schemas" / "v1.0" / "deferred-invariants.md"
CORPUS = Path(__file__).with_name("corpus.json")
FIELDS = (
    "invariant_id",
    "validator",
    "enforcement_phase",
    "failure_resolution",
    "positive_test",
    "negative_test",
)
SUPPLEMENTAL_IDS = {
    "INV-002-N.stale-state-version",
    "INV-002-N.precondition",
    "INV-003-N.dangling",
    "INV-004-N.plan-id",
    "INV-004-N.plan-version",
    "INV-010-N.missing-audit",
    "INV-010-N.unverifiable-audit",
    "INV-011-N.user-response-count",
    "INV-012-N.target-modules",
    "INV-012-N.runtime",
    "INV-013-N.template",
    "INV-013-N.graph",
    "INV-013-N.disruption",
    "INV-014-N.evaluator-only",
    "INV-014-N.validator-visible",
    "INV-015-N.event-log-hash",
    "INV-016-N.uniqueness",
    "INV-016-N.contiguity",
    "INV-016-N.ascending-order",
}
TEST_ID_PATTERN = re.compile(r"^(INV-\d{3})-([PN])(?:\.[a-z0-9-]+)?$")


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_label(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def differing_paths(left: object, right: object, path: str = "") -> set[str]:
    if type(left) is not type(right):
        return {path}
    if isinstance(left, dict):
        paths: set[str] = set()
        for key in set(left) | set(right):
            child = f"{path}/{key}" if path else key
            if key not in left or key not in right:
                paths.add(child)
            else:
                paths.update(differing_paths(left[key], right[key], child))
        return paths
    if isinstance(left, list):
        if len(left) != len(right):
            return {f"{path}/length"}
        paths: set[str] = set()
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            paths.update(differing_paths(left_item, right_item, f"{path}/{index}"))
        return paths
    return set() if left == right else {path}


def assert_integrity_fixtures(cases: dict[str, dict[str, object]]) -> None:
    positive = cases["INV-015-P"]["input"]
    artifact_negative = cases["INV-015-N"]["input"]
    log_negative = cases["INV-015-N.event-log-hash"]["input"]

    def artifact_hashes_match(case_input: dict[str, object]) -> bool:
        artifacts = case_input["artifacts"]
        return all(
            sha256_label(canonical_json_bytes(artifact["content"])) == artifact["content_hash"]
            for artifact in artifacts
        )

    def log_hash_matches(case_input: dict[str, object]) -> bool:
        event_log = case_input["event_log"]
        assert event_log["serialization"] == "CANONICAL_JSONL_WITH_FINAL_NEWLINE"
        canonical_jsonl = b"".join(
            canonical_json_bytes(event) + b"\n" for event in event_log["events"]
        )
        return sha256_label(canonical_jsonl) == event_log["integrity_hash"]

    assert artifact_hashes_match(positive) and log_hash_matches(positive)
    assert not artifact_hashes_match(artifact_negative) and log_hash_matches(artifact_negative)
    assert artifact_hashes_match(log_negative) and not log_hash_matches(log_negative)

    assert artifact_negative["canonicalization"] == positive["canonicalization"]
    assert artifact_negative["event_log"] == positive["event_log"]
    assert artifact_negative["artifacts"][0]["content_hash"] == positive["artifacts"][0]["content_hash"]
    assert artifact_negative["artifacts"][0]["content"] != positive["artifacts"][0]["content"]

    assert log_negative["canonicalization"] == positive["canonicalization"]
    assert log_negative["artifacts"] == positive["artifacts"]
    assert log_negative["event_log"]["serialization"] == positive["event_log"]["serialization"]
    assert log_negative["event_log"]["events"] == positive["event_log"]["events"]
    assert log_negative["event_log"]["integrity_hash"] != positive["event_log"]["integrity_hash"]
    assert differing_paths(positive, artifact_negative) == {"artifacts/0/content/value"}
    assert differing_paths(positive, log_negative) == {"event_log/integrity_hash"}


def load_register() -> dict[str, dict[str, str]]:
    text = REGISTER.read_text(encoding="utf-8")
    records: dict[str, dict[str, str]] = {}
    for block in re.findall(r"```yaml\s*(.*?)```", text, flags=re.DOTALL):
        values: dict[str, str] = {}
        for line in block.splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip() in FIELDS:
                values[key.strip()] = value.strip()
        invariant_id = values.get("invariant_id")
        if invariant_id:
            records[invariant_id] = values
    return records


def main() -> None:
    register = load_register()
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    cases = corpus.get("cases")
    assert corpus.get("format_version") == "1.0", "unexpected corpus format"
    assert isinstance(cases, list), "cases must be an array"

    expected_ids = {
        record[test_key]
        for record in register.values()
        for test_key in ("positive_test", "negative_test")
    }
    actual_ids = [case.get("test_id") for case in cases]
    assert len(actual_ids) == len(set(actual_ids)), "duplicate test_id"
    assert expected_ids.issubset(actual_ids), "corpus must contain every registered P/N test"
    assert set(actual_ids) - expected_ids == SUPPLEMENTAL_IDS, "supplemental coverage changed"

    for case in cases:
        test_id = case["test_id"]
        match = TEST_ID_PATTERN.fullmatch(test_id)
        assert match, f"invalid test_id: {test_id}"
        invariant_id, polarity = match.groups()
        record = register[invariant_id]
        assert case["invariant_id"] == invariant_id
        assert case["validator"] == record["validator"]
        assert case["enforcement_phase"] == record["enforcement_phase"]
        assert isinstance(case.get("input"), dict) and case["input"], f"{test_id}: empty input"
        expected = case.get("expected", {})
        if test_id in SUPPLEMENTAL_IDS:
            assert isinstance(case.get("coverage_clause"), str) and case["coverage_clause"]
        if polarity == "P":
            assert expected == {"verdict": "PASS", "expected_failure_resolution": None}
        else:
            assert expected == {
                "verdict": "FAIL",
                "expected_failure_resolution": record["failure_resolution"],
            }

    cases_by_id = {case["test_id"]: case for case in cases}
    assert_integrity_fixtures(cases_by_id)

    canonical = json.dumps(corpus, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert json.loads(canonical) == corpus, "corpus is not JSON round-trip stable"
    print(f"Invariant fixture corpus: {len(register)} invariants, {len(cases)} cases, PASS")


if __name__ == "__main__":
    main()
