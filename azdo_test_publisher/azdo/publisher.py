from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

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
        _ensure_planned_result_metadata(publishable, point_by_case_id, self.client)
        _validate_planned_result_metadata(publishable, point_by_case_id)

        point_ids = sorted(
            {
                int(_point_metadata(point_by_case_id[result.test_case_id])["point_id"])
                for result in publishable
                if result.test_case_id
            }
        )
        run_name = f"Automated evidence run {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        run = self.client.create_test_run(run_name, self.config.azdo.plan_id, point_ids)
        run_id = int(run["id"])
        logger.info("Created Azure DevOps test run %s", run_id)

        run_results_by_point_id = self.client.get_results_by_run(run_id)
        _validate_existing_run_results(publishable, point_by_case_id, run_results_by_point_id)
        payload = [
            _planned_result_patch_payload(
                result,
                point_by_case_id[result.test_case_id],
                run_results_by_point_id[int(_point_metadata(point_by_case_id[result.test_case_id])["point_id"])],
            )
            for result in publishable
            if result.test_case_id
        ]
        updated = self.client.update_test_results(run_id, payload)
        result_id_by_case_id = _result_id_by_case_id(updated) or _result_id_by_case_id_from_existing(run_results_by_point_id)

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
        metadata = _point_metadata(point)
        case_id = metadata["test_case_id"]
        if case_id is not None:
            mapped[str(case_id)] = point
            logger.debug(
                "Mapped Azure DevOps point metadata: pointId=%s testCaseId=%s testCaseTitle=%s testCaseRevision=%s",
                metadata["point_id"],
                metadata["test_case_id"],
                metadata["test_case_title"],
                metadata["test_case_revision"],
            )
    return mapped


def _planned_result_patch_payload(result: TestResult, point: dict, existing_result: dict[str, Any]) -> dict:
    metadata = _point_metadata(point)
    payload = {
        "id": int(existing_result["result_id"]),
        "testPoint": {"id": int(metadata["point_id"])},
        "testCase": {"id": str(metadata["test_case_id"])},
        "testCaseTitle": str(metadata["test_case_title"]),
        "testCaseRevision": int(metadata["test_case_revision"]),
        "automatedTestName": result.full_name,
        "outcome": _azdo_outcome(result.outcome),
        "state": "Completed",
        "comment": result.message or "",
    }
    logger.debug(
        "Updating planned Azure DevOps result: pointId=%s resultId=%s testCaseId=%s testCaseRevision=%s testCaseTitle=%s",
        payload["testPoint"]["id"],
        payload["id"],
        payload["testCase"]["id"],
        payload["testCaseRevision"],
        payload["testCaseTitle"],
    )
    if result.duration_ms is not None:
        payload["durationInMs"] = int(result.duration_ms)
    if result.outcome == Outcome.FAILED and (result.message or result.stacktrace):
        payload["errorMessage"] = result.message or ""
        payload["stackTrace"] = result.stacktrace or ""
    return payload


def _ensure_planned_result_metadata(
    results: list[TestResult],
    point_by_case_id: dict[str, dict],
    client: AzureDevOpsClient,
) -> None:
    for result in results:
        if not result.test_case_id:
            continue
        point = point_by_case_id[result.test_case_id]
        metadata = _point_metadata(point)
        if metadata["test_case_title"] not in (None, "") and metadata["test_case_revision"] not in (None, ""):
            continue
        testcase_metadata = client.get_testcase_metadata(str(metadata["test_case_id"]))
        test_case = point.setdefault("testCase", {})
        if metadata["test_case_title"] in (None, "") and testcase_metadata.get("title"):
            test_case["name"] = testcase_metadata["title"]
        if metadata["test_case_revision"] in (None, "") and testcase_metadata.get("rev") not in (None, ""):
            test_case["revision"] = testcase_metadata["rev"]


def _validate_planned_result_metadata(results: list[TestResult], point_by_case_id: dict[str, dict]) -> None:
    errors: list[str] = []
    for result in results:
        if not result.test_case_id:
            continue
        point = point_by_case_id[result.test_case_id]
        metadata = _point_metadata(point)
        missing = [
            label
            for label, value in {
                "testPoint.id": metadata["point_id"],
                "testCase.id": metadata["test_case_id"],
                "testCaseTitle": metadata["test_case_title"],
                "testCaseRevision": metadata["test_case_revision"],
            }.items()
            if value in (None, "")
        ]
        if missing:
            errors.append(f"TC-{result.test_case_id} mapped point is missing required metadata: {', '.join(missing)}")
    if errors:
        raise MappingError("Cannot publish planned test results. " + "; ".join(errors))


def _validate_existing_run_results(
    results: list[TestResult],
    point_by_case_id: dict[str, dict],
    run_results_by_point_id: dict[int, dict[str, Any]],
) -> None:
    missing: list[str] = []
    for result in results:
        if not result.test_case_id:
            continue
        point_id = int(_point_metadata(point_by_case_id[result.test_case_id])["point_id"])
        if point_id not in run_results_by_point_id:
            missing.append(f"TC-{result.test_case_id} pointId={point_id}")
    if missing:
        raise MappingError(
            "Azure DevOps did not return planned result records for mapped test points: " + ", ".join(missing)
        )


def _point_metadata(point: dict[str, Any]) -> dict[str, Any]:
    test_case = point.get("testCase") or {}
    work_item_obj = point.get("workItem") or {}
    work_item = point.get("workItemProperties") or []
    return {
        "point_id": _first_value(point, ["id", "testPointId", "pointId"]),
        "test_case_id": _first_value(test_case, ["id"])
        or _first_value(work_item_obj, ["id"])
        or _work_item_property(work_item, ["System.Id", "Microsoft.VSTS.TCM.TestCaseId"]),
        "test_case_title": _first_value(test_case, ["name", "title", "testCaseTitle"])
        or _first_value(work_item_obj, ["name", "title"])
        or _work_item_property(work_item, ["System.Title"]),
        "test_case_revision": _first_value(test_case, ["revision", "rev"])
        or _first_value(work_item_obj, ["revision", "rev"])
        or _work_item_property(work_item, ["System.Rev", "Microsoft.VSTS.TCM.TestCaseRevision"]),
    }


def _first_value(source: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _work_item_property(properties: list[dict[str, Any]], names: list[str]) -> Any:
    for prop in properties:
        prop_name = prop.get("workItem", {}).get("key") or prop.get("key") or prop.get("name")
        if prop_name in names:
            return prop.get("workItem", {}).get("value") or prop.get("value")
    return None


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


def _result_id_by_case_id_from_existing(results_by_point_id: dict[int, dict[str, Any]]) -> dict[str, int]:
    mapped: dict[str, int] = {}
    for result in results_by_point_id.values():
        case_id = result.get("test_case_id")
        result_id = result.get("result_id")
        if case_id and result_id:
            mapped[str(case_id)] = int(result_id)
    return mapped
