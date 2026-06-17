from __future__ import annotations

import pytest

from azdo_test_publisher.mapping import (
    MappingError,
    aggregate_worst_outcome_wins,
    apply_mapping,
    duplicate_results_by_test_case_id,
    extract_test_case_ids,
    resolve_duplicate_results,
    summarize_mapping,
)
from azdo_test_publisher.models import DuplicateStrategy, Outcome, TestResult


def test_extract_tc_ids() -> None:
    assert extract_test_case_ids(["login TC-123", "tag TC-456"], r"TC-(\d+)") == ["123", "456"]


def test_multiple_tc_ids_fail_by_default() -> None:
    result = TestResult(None, "TC-1 TC-2", "TC-1 TC-2", Outcome.PASSED, mapping_candidates=["TC-1 TC-2"])
    with pytest.raises(MappingError):
        apply_mapping([result], r"TC-(\d+)")


def test_mapping_summary_duplicates() -> None:
    results = [
        TestResult("1", "a", "a", Outcome.PASSED),
        TestResult("1", "b", "b", Outcome.FAILED),
        TestResult(None, "c", "c", Outcome.PASSED),
    ]
    summary = summarize_mapping(results)
    assert summary.mapped == 2
    assert summary.unmapped == 1
    assert summary.duplicates == {"1": 2}


def test_duplicate_detection() -> None:
    results = [
        TestResult("1", "first", "first", Outcome.PASSED, source_file="a.xml"),
        TestResult("1", "second", "second", Outcome.FAILED, source_file="b.xml"),
        TestResult("2", "third", "third", Outcome.PASSED, source_file="c.xml"),
    ]

    duplicates = duplicate_results_by_test_case_id(results)

    assert list(duplicates) == ["1"]
    assert [result.name for result in duplicates["1"]] == ["first", "second"]


def test_duplicate_strategy_fail_lists_sources() -> None:
    results = [
        TestResult("1", "first test", "first test", Outcome.PASSED, source_file="a.xml"),
        TestResult("1", "second test", "second test", Outcome.FAILED, source_file="b.xml"),
    ]

    with pytest.raises(MappingError) as exc:
        resolve_duplicate_results(results, DuplicateStrategy.FAIL)

    message = str(exc.value)
    assert "TC-1" in message
    assert "first test (a.xml)" in message
    assert "second test (b.xml)" in message


def test_worst_outcome_wins_aggregation() -> None:
    results = [
        TestResult("1", "passed", "passed", Outcome.PASSED, duration_ms=10, evidence_hints=["TC-1", "video"]),
        TestResult(
            "1",
            "skipped",
            "skipped",
            Outcome.SKIPPED,
            duration_ms=None,
            message="dependency unavailable",
            evidence_hints=["log"],
        ),
        TestResult(
            "1",
            "failed",
            "failed",
            Outcome.FAILED,
            duration_ms=20,
            message="boom",
            stacktrace="trace",
            evidence_hints=["screenshot"],
        ),
    ]

    aggregated = aggregate_worst_outcome_wins(results)

    assert len(aggregated) == 1
    assert aggregated[0].outcome == Outcome.FAILED
    assert aggregated[0].duration_ms == 30
    assert aggregated[0].full_name == "Aggregated result for TC-1 (3 executions)"
    assert "skipped: dependency unavailable" in aggregated[0].message
    assert "failed: boom" in aggregated[0].message
    assert set(aggregated[0].evidence_hints) == {"TC-1", "video", "log", "screenshot"}
