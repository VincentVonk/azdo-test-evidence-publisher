from __future__ import annotations

import re
from collections import Counter
from collections import defaultdict
from dataclasses import dataclass

from .models import DuplicateStrategy, Outcome, TestResult


class MappingError(ValueError):
    pass


@dataclass(slots=True)
class MappingSummary:
    mapped: int
    unmapped: int
    duplicates: dict[str, int]


OUTCOME_PRIORITY = {
    Outcome.FAILED: 4,
    Outcome.NOT_APPLICABLE: 3,
    Outcome.SKIPPED: 2,
    Outcome.PASSED: 1,
}


def extract_test_case_ids(values: list[str | None], pattern: str) -> list[str]:
    regex = re.compile(pattern)
    ids: list[str] = []
    for value in values:
        if not value:
            continue
        for match in regex.finditer(value):
            candidate = match.group(1) if match.groups() else match.group(0)
            ids.append(candidate)
    return sorted(set(ids), key=ids.index)


def apply_mapping(
    results: list[TestResult],
    pattern: str,
    allow_multiple: bool = False,
) -> list[TestResult]:
    for result in results:
        candidates = extract_test_case_ids(result.mapping_candidates, pattern)
        if not candidates:
            candidates = extract_test_case_ids([result.message], pattern)
        result.evidence_hints.extend([f"TC-{candidate}" for candidate in candidates])
        if len(candidates) > 1 and not allow_multiple:
            raise MappingError(
                f"Test '{result.full_name}' maps to multiple test case IDs: {', '.join(candidates)}. "
                "Set settings.allowMultipleTestCaseIds=true to allow this."
            )
        result.test_case_id = candidates[0] if candidates else None
    return results


def summarize_mapping(results: list[TestResult]) -> MappingSummary:
    ids = [result.test_case_id for result in results if result.test_case_id]
    counts = Counter(ids)
    duplicates = {test_case_id: count for test_case_id, count in counts.items() if count > 1}
    return MappingSummary(
        mapped=len(ids),
        unmapped=sum(1 for result in results if not result.test_case_id),
        duplicates=duplicates,
    )


def duplicate_results_by_test_case_id(results: list[TestResult]) -> dict[str, list[TestResult]]:
    grouped: dict[str, list[TestResult]] = defaultdict(list)
    for result in results:
        if result.test_case_id:
            grouped[result.test_case_id].append(result)
    return {test_case_id: items for test_case_id, items in grouped.items() if len(items) > 1}


def format_duplicate_error(duplicates: dict[str, list[TestResult]]) -> str:
    lines = ["Duplicate TC mappings found:"]
    for test_case_id in sorted(duplicates, key=_numeric_sort):
        lines.append(f"TC-{test_case_id}:")
        for result in duplicates[test_case_id]:
            source = result.source_file or "<unknown source>"
            lines.append(f"  - {result.name} ({source})")
    return "\n".join(lines)


def resolve_duplicate_results(
    results: list[TestResult],
    duplicate_strategy: DuplicateStrategy,
) -> tuple[list[TestResult], dict[str, list[TestResult]]]:
    duplicates = duplicate_results_by_test_case_id(results)
    if not duplicates:
        return results, duplicates
    if duplicate_strategy == DuplicateStrategy.FAIL:
        raise MappingError(format_duplicate_error(duplicates))
    if duplicate_strategy == DuplicateStrategy.WORST_OUTCOME_WINS:
        return aggregate_worst_outcome_wins(results, duplicates), duplicates
    raise MappingError(f"Unsupported duplicateStrategy: {duplicate_strategy}")


def aggregate_worst_outcome_wins(
    results: list[TestResult],
    duplicates: dict[str, list[TestResult]] | None = None,
) -> list[TestResult]:
    duplicates = duplicates or duplicate_results_by_test_case_id(results)
    duplicate_ids = set(duplicates)
    aggregated: list[TestResult] = []
    added_duplicate_ids: set[str] = set()

    for result in results:
        test_case_id = result.test_case_id
        if not test_case_id or test_case_id not in duplicate_ids:
            aggregated.append(result)
            continue
        if test_case_id in added_duplicate_ids:
            continue
        aggregated.append(_aggregate_group(test_case_id, duplicates[test_case_id]))
        added_duplicate_ids.add(test_case_id)
    return aggregated


def _aggregate_group(test_case_id: str, group: list[TestResult]) -> TestResult:
    outcome = max((result.outcome for result in group), key=lambda item: OUTCOME_PRIORITY[item])
    duration_values = [result.duration_ms for result in group if result.duration_ms is not None]
    messages = [
        _message_line(result)
        for result in group
        if result.outcome in {Outcome.FAILED, Outcome.SKIPPED} and (result.message or result.stacktrace)
    ]
    stacktraces = [
        _stacktrace_line(result)
        for result in group
        if result.outcome in {Outcome.FAILED, Outcome.SKIPPED} and result.stacktrace
    ]
    evidence_hints = sorted({hint for result in group for hint in result.evidence_hints})
    source_files = sorted({result.source_file for result in group if result.source_file})
    return TestResult(
        test_case_id=test_case_id,
        name=f"Aggregated result for TC-{test_case_id}",
        full_name=f"Aggregated result for TC-{test_case_id} ({len(group)} executions)",
        outcome=outcome,
        duration_ms=sum(duration_values) if duration_values else None,
        message="\n".join(messages) or None,
        stacktrace="\n".join(stacktraces) or None,
        source_file=", ".join(source_files) or None,
        evidence_hints=evidence_hints,
    )


def _message_line(result: TestResult) -> str:
    return f"{result.name}: {result.message or result.stacktrace or ''}".strip()


def _stacktrace_line(result: TestResult) -> str:
    return f"{result.name}:\n{result.stacktrace or ''}".strip()


def _numeric_sort(value: str) -> tuple[int, str]:
    return (int(value), value) if value.isdigit() else (0, value)
