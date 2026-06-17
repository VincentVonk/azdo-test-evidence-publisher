from __future__ import annotations

import logging
from datetime import datetime, timezone

from azdo_test_publisher.mapping import MappingError, resolve_duplicate_results
from azdo_test_publisher.models import DuplicateStrategy
from azdo_test_publisher.models import Attachment, AttachmentLevel, Outcome, PublisherConfig, TestResult

from .client import AzureDevOpsClient

logger = logging.getLogger(__name__)


class AzureDevOpsPublisher:
    def __init__(self, config: PublisherConfig, token: str) -> None:
        if not token:
            raise ValueError("Azure DevOps token is required")
        if config.azdo.plan_id <= 0 or config.azdo.suite_id <= 0:
            raise ValueError("Azure DevOps planId and suiteId must be positive integers")
        self.config = config
        self.client = AzureDevOpsClient(config.azdo.organization, config.azdo.project, token)

    def publish(self, results: list[TestResult], attachments: list[Attachment]) -> None:
        results, duplicates = resolve_duplicate_results(results, self.config.settings.duplicate_strategy)
        if duplicates and self.config.settings.duplicate_strategy == DuplicateStrategy.WORST_OUTCOME_WINS:
            logger.warning(
                "Duplicate TC mappings were aggregated using worst_outcome_wins before publishing: %s",
                ", ".join(f"TC-{test_case_id} ({len(items)} executions)" for test_case_id, items in duplicates.items()),
            )

        logger.info("Fetching Azure DevOps test points")
        points = self.client.get_test_points(self.config.azdo.plan_id, self.config.azdo.suite_id)
        point_by_case_id = _point_by_test_case_id(points)
        mapped_count = sum(1 for result in results if result.test_case_id in point_by_case_id)
        unmapped_count = sum(1 for result in results if not result.test_case_id or result.test_case_id not in point_by_case_id)
        logger.info("Azure DevOps mapping summary: mapped=%s unmapped=%s", mapped_count, unmapped_count)
        missing = sorted(
            {
                result.test_case_id
                for result in results
                if result.test_case_id and result.test_case_id not in point_by_case_id
            }
        )
        if missing and not self.config.settings.allow_unmapped:
            raise MappingError(
                "Test case IDs are not present in the configured Azure DevOps suite: "
                + ", ".join(str(item) for item in missing)
            )

        publishable = [result for result in results if result.test_case_id in point_by_case_id]
        if not publishable:
            raise MappingError("No parsed results map to Azure DevOps test points")

        point_ids = sorted({int(point_by_case_id[result.test_case_id]["id"]) for result in publishable if result.test_case_id})
        run_name = f"Automated evidence run {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        run = self.client.create_test_run(run_name, self.config.azdo.plan_id, point_ids)
        run_id = int(run["id"])
        logger.info("Created Azure DevOps test run %s", run_id)

        payload = [_result_payload(result, point_by_case_id[result.test_case_id]) for result in publishable if result.test_case_id]
        created = self.client.add_test_results(run_id, payload)
        result_id_by_case_id = _result_id_by_case_id(created)

        if self.config.settings.upload_run_evidence:
            for attachment in attachments:
                if attachment.attachment_level == AttachmentLevel.RUN:
                    self.client.upload_run_attachment(run_id, attachment.name, attachment.path.read_bytes())

        if self.config.settings.upload_result_evidence:
            for attachment in attachments:
                if attachment.attachment_level != AttachmentLevel.RESULT or not attachment.related_test_case_id:
                    continue
                result_id = result_id_by_case_id.get(attachment.related_test_case_id)
                if result_id:
                    self.client.upload_result_attachment(run_id, result_id, attachment.name, attachment.path.read_bytes())

        self.client.complete_test_run(run_id)
        logger.info("Completed Azure DevOps test run %s", run_id)


def _point_by_test_case_id(points: list[dict]) -> dict[str, dict]:
    mapped: dict[str, dict] = {}
    for point in points:
        test_case = point.get("testCase") or {}
        case_id = test_case.get("id")
        if case_id is not None:
            mapped[str(case_id)] = point
    return mapped


def _result_payload(result: TestResult, point: dict) -> dict:
    payload = {
        "testPoint": {"id": str(point["id"])},
        "testCase": {"id": str(result.test_case_id)},
        "testCaseTitle": result.name,
        "automatedTestName": result.full_name,
        "outcome": _azdo_outcome(result.outcome),
    }
    if result.duration_ms is not None:
        payload["durationInMs"] = str(result.duration_ms)
    if result.message or result.stacktrace:
        payload["errorMessage"] = result.message or ""
        payload["stackTrace"] = result.stacktrace or ""
    return payload


def _azdo_outcome(outcome: Outcome) -> str:
    if outcome == Outcome.PASSED:
        return "Passed"
    if outcome == Outcome.FAILED:
        return "Failed"
    if outcome == Outcome.SKIPPED:
        return "NotExecuted"
    return "NotApplicable"


def _result_id_by_case_id(results: list[dict]) -> dict[str, int]:
    mapped: dict[str, int] = {}
    for result in results:
        case_id = (result.get("testCase") or {}).get("id")
        result_id = result.get("id")
        if case_id and result_id:
            mapped[str(case_id)] = int(result_id)
    return mapped
