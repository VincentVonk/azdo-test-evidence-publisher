from __future__ import annotations

import json
import logging

import pytest

from azdo_test_publisher.azdo.publisher import AzureDevOpsPublisher
from azdo_test_publisher.config import load_config
from azdo_test_publisher.mapping import MappingError
from azdo_test_publisher.models import Attachment, AttachmentLevel, Outcome, TestResult


class FakeClient:
    def __init__(self) -> None:
        self.get_points_called = False
        self.create_run_called = False
        self.post_results_called = False
        self.update_results_payload: list[dict] = []
        self.uploaded_run_attachments: list[tuple[int, str]] = []
        self.uploaded_result_attachments: list[tuple[int, int, str]] = []

    def get_test_points(self, plan_id: int, suite_id: int):
        self.get_points_called = True
        return [{"id": 11, "testCase": {"id": "101", "name": "Login works", "revision": 7}}]

    def create_test_run(self, name: str, plan_id: int, point_ids: list[int]):
        self.create_run_called = True
        return {"id": 99}

    def add_test_results(self, run_id: int, results: list[dict]):
        self.post_results_called = True
        raise AssertionError("planned runs must PATCH existing results, not POST new results")

    def get_results_by_run(self, run_id: int):
        return {11: {"result_id": 1001, "test_case_id": "101"}}

    def update_test_results(self, run_id: int, results: list[dict]):
        self.update_results_payload = results
        return [{"id": 1001, "testCase": {"id": "101"}}]

    def get_testcase_metadata(self, test_case_id: str):
        return {"rev": 7, "title": "Login works"}

    def upload_result_attachment(self, run_id: int, result_id: int, name: str, data: bytes, comment: str = ""):
        self.uploaded_result_attachments.append((run_id, result_id, name))
        return {}

    def upload_run_attachment(self, run_id: int, name: str, data: bytes, comment: str = ""):
        self.uploaded_run_attachments.append((run_id, name))
        return {}

    def complete_test_run(self, run_id: int):
        return {}


def test_publish_fails_for_missing_test_point(tmp_path) -> None:
    config_file = tmp_path / "publisher.json"
    config_file.write_text(
        json.dumps(
            {
                "azdo": {
                    "organization": "https://dev.azure.com/org",
                    "project": "Project",
                    "planId": 1,
                    "suiteId": 2,
                },
                "runs": [{"name": "junit", "resultFormat": "junit", "resultFiles": ["*.xml"]}],
            }
        ),
        encoding="utf-8",
    )
    publisher = AzureDevOpsPublisher(load_config(config_file), "secret")
    publisher.client = FakeClient()  # type: ignore[assignment]

    with pytest.raises(MappingError):
        publisher.publish([TestResult("999", "x", "x", Outcome.PASSED)], [])


def test_publish_maps_result_to_point(tmp_path) -> None:
    config_file = tmp_path / "publisher.json"
    config_file.write_text(
        json.dumps(
            {
                "azdo": {
                    "organization": "https://dev.azure.com/org",
                    "project": "Project",
                    "planId": 1,
                    "suiteId": 2,
                },
                "runs": [{"name": "junit", "resultFormat": "junit", "resultFiles": ["*.xml"]}],
            }
        ),
        encoding="utf-8",
    )
    publisher = AzureDevOpsPublisher(load_config(config_file), "secret")
    publisher.client = FakeClient()  # type: ignore[assignment]
    publisher.publish([TestResult("101", "x", "x", Outcome.PASSED)], [])


def test_publish_does_not_call_azdo_when_duplicates_fail(tmp_path) -> None:
    config_file = tmp_path / "publisher.json"
    config_file.write_text(
        json.dumps(
            {
                "azdo": {
                    "organization": "https://dev.azure.com/org",
                    "project": "Project",
                    "planId": 1,
                    "suiteId": 2,
                },
                "settings": {"duplicateStrategy": "fail"},
                "runs": [{"name": "junit", "resultFormat": "junit", "resultFiles": ["*.xml"]}],
            }
        ),
        encoding="utf-8",
    )
    publisher = AzureDevOpsPublisher(load_config(config_file), "secret")
    fake_client = FakeClient()
    publisher.client = fake_client  # type: ignore[assignment]

    with pytest.raises(MappingError):
        publisher.publish(
            [
                TestResult("101", "first", "first", Outcome.PASSED),
                TestResult("101", "second", "second", Outcome.FAILED),
            ],
            [],
        )

    assert fake_client.get_points_called is False


def test_publish_aggregates_duplicates_with_worst_outcome(tmp_path) -> None:
    config_file = tmp_path / "publisher.json"
    config_file.write_text(
        json.dumps(
            {
                "azdo": {
                    "organization": "https://dev.azure.com/org",
                    "project": "Project",
                    "planId": 1,
                    "suiteId": 2,
                },
                "settings": {"duplicateStrategy": "worst_outcome_wins"},
                "runs": [{"name": "junit", "resultFormat": "junit", "resultFiles": ["*.xml"]}],
            }
        ),
        encoding="utf-8",
    )

    class CapturingClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.results_payload: list[dict] = []

        def update_test_results(self, run_id: int, results: list[dict]):
            self.results_payload = results
            return [{"id": 1001, "testCase": {"id": "101"}}]

    publisher = AzureDevOpsPublisher(load_config(config_file), "secret")
    fake_client = CapturingClient()
    publisher.client = fake_client  # type: ignore[assignment]

    publisher.publish(
        [
            TestResult("101", "first", "first", Outcome.PASSED, duration_ms=1),
            TestResult("101", "second", "second", Outcome.FAILED, duration_ms=2, message="failed"),
        ],
        [],
    )

    assert len(fake_client.results_payload) == 1
    assert fake_client.results_payload[0]["outcome"] == "Failed"
    assert fake_client.results_payload[0]["durationInMs"] == 3
    assert fake_client.results_payload[0]["automatedTestName"] == "Aggregated result for TC-101 (2 executions)"
    assert fake_client.post_results_called is False


def test_planned_result_payload_includes_required_test_point_metadata(tmp_path) -> None:
    config_file = tmp_path / "publisher.json"
    config_file.write_text(
        json.dumps(
            {
                "azdo": {
                    "organization": "https://dev.azure.com/org",
                    "project": "Project",
                    "planId": 1,
                    "suiteId": 2,
                },
                "runs": [{"name": "junit", "resultFormat": "junit", "resultFiles": ["*.xml"]}],
            }
        ),
        encoding="utf-8",
    )

    class CapturingClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.results_payload: list[dict] = []

        def update_test_results(self, run_id: int, results: list[dict]):
            self.results_payload = results
            return [{"id": 1001, "testCase": {"id": "101"}}]

    publisher = AzureDevOpsPublisher(load_config(config_file), "secret")
    fake_client = CapturingClient()
    publisher.client = fake_client  # type: ignore[assignment]

    publisher.publish([TestResult("101", "parsed name", "parsed full name", Outcome.PASSED, duration_ms=123)], [])

    payload = fake_client.results_payload[0]
    assert payload["id"] == 1001
    assert payload["testPoint"] == {"id": 11}
    assert payload["testCase"] == {"id": "101"}
    assert payload["testCaseTitle"] == "Login works"
    assert payload["testCaseRevision"] == 7
    assert payload["state"] == "Completed"
    assert payload["durationInMs"] == 123


def test_publish_fails_before_creating_run_when_point_metadata_missing(tmp_path) -> None:
    config_file = tmp_path / "publisher.json"
    config_file.write_text(
        json.dumps(
            {
                "azdo": {
                    "organization": "https://dev.azure.com/org",
                    "project": "Project",
                    "planId": 1,
                    "suiteId": 2,
                },
                "runs": [{"name": "junit", "resultFormat": "junit", "resultFiles": ["*.xml"]}],
            }
        ),
        encoding="utf-8",
    )

    class MissingMetadataClient(FakeClient):
        def get_test_points(self, plan_id: int, suite_id: int):
            self.get_points_called = True
            return [{"id": 11, "testCase": {"id": "101"}}]

        def get_testcase_metadata(self, test_case_id: str):
            return {}

    publisher = AzureDevOpsPublisher(load_config(config_file), "secret")
    fake_client = MissingMetadataClient()
    publisher.client = fake_client  # type: ignore[assignment]

    with pytest.raises(MappingError, match="testCaseTitle"):
        publisher.publish([TestResult("101", "parsed name", "parsed full name", Outcome.PASSED)], [])

    assert fake_client.create_run_called is False


def test_planned_result_payload_uses_work_item_properties_fallback(tmp_path) -> None:
    config_file = tmp_path / "publisher.json"
    config_file.write_text(
        json.dumps(
            {
                "azdo": {
                    "organization": "https://dev.azure.com/org",
                    "project": "Project",
                    "planId": 1,
                    "suiteId": 2,
                },
                "runs": [{"name": "junit", "resultFormat": "junit", "resultFiles": ["*.xml"]}],
            }
        ),
        encoding="utf-8",
    )

    class WorkItemPropertiesClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.results_payload: list[dict] = []

        def get_test_points(self, plan_id: int, suite_id: int):
            self.get_points_called = True
            return [
                {
                    "id": 11,
                    "workItemProperties": [
                        {"workItem": {"key": "System.Id", "value": "101"}},
                        {"workItem": {"key": "System.Title", "value": "Login works"}},
                        {"workItem": {"key": "System.Rev", "value": 7}},
                    ],
                }
            ]

        def update_test_results(self, run_id: int, results: list[dict]):
            self.results_payload = results
            return [{"id": 1001, "testCase": {"id": "101"}}]

    publisher = AzureDevOpsPublisher(load_config(config_file), "secret")
    fake_client = WorkItemPropertiesClient()
    publisher.client = fake_client  # type: ignore[assignment]

    publisher.publish([TestResult("101", "parsed name", "parsed full name", Outcome.PASSED)], [])

    payload = fake_client.results_payload[0]
    assert payload["testPoint"] == {"id": 11}
    assert payload["testCase"] == {"id": "101"}
    assert payload["testCaseTitle"] == "Login works"
    assert payload["testCaseRevision"] == 7


def test_result_attachment_uses_existing_run_result_id(tmp_path) -> None:
    config_file = tmp_path / "publisher.json"
    config_file.write_text(
        json.dumps(
            {
                "azdo": {
                    "organization": "https://dev.azure.com/org",
                    "project": "Project",
                    "planId": 1,
                    "suiteId": 2,
                },
                "runs": [{"name": "junit", "resultFormat": "junit", "resultFiles": ["*.xml"]}],
            }
        ),
        encoding="utf-8",
    )
    evidence = tmp_path / "TC-101-failure.log"
    evidence.write_text("failure evidence", encoding="utf-8")
    attachment = Attachment(
        path=evidence,
        name=evidence.name,
        size_bytes=evidence.stat().st_size,
        mime_type="text/plain",
        attachment_level=AttachmentLevel.RESULT,
        related_test_case_id="101",
    )
    publisher = AzureDevOpsPublisher(load_config(config_file), "secret")
    fake_client = FakeClient()
    publisher.client = fake_client  # type: ignore[assignment]

    publisher.publish([TestResult("101", "x", "x", Outcome.FAILED, message="failed")], [attachment])

    assert fake_client.uploaded_result_attachments == [(99, 1001, "TC-101-failure.log")]
    assert fake_client.post_results_called is False


def test_upload_summary_counts_result_attachment(tmp_path, caplog) -> None:
    config_file = tmp_path / "publisher.json"
    config_file.write_text(
        json.dumps(
            {
                "azdo": {
                    "organization": "https://dev.azure.com/org",
                    "project": "Project",
                    "planId": 1,
                    "suiteId": 2,
                },
                "runs": [{"name": "junit", "resultFormat": "junit", "resultFiles": ["*.xml"]}],
            }
        ),
        encoding="utf-8",
    )
    evidence = tmp_path / "TC-101-failure.log"
    evidence.write_text("failure evidence", encoding="utf-8")
    attachment = Attachment(
        path=evidence,
        name=evidence.name,
        size_bytes=evidence.stat().st_size,
        mime_type="text/plain",
        attachment_level=AttachmentLevel.RESULT,
        related_test_case_id="101",
    )
    publisher = AzureDevOpsPublisher(load_config(config_file), "secret")
    fake_client = FakeClient()
    publisher.client = fake_client  # type: ignore[assignment]

    with caplog.at_level(logging.INFO):
        publisher.publish([TestResult("101", "x", "x", Outcome.FAILED, message="failed")], [attachment])

    assert "Evidence upload summary" in caplog.text
    assert "  Result-level attachments uploaded: 1" in caplog.text
    assert "  Run-level attachments uploaded: 0" in caplog.text
    assert "  Attachments skipped: 0" in caplog.text


def test_eligible_evidence_but_no_upload_warns(tmp_path, caplog) -> None:
    config_file = tmp_path / "publisher.json"
    config_file.write_text(
        json.dumps(
            {
                "azdo": {
                    "organization": "https://dev.azure.com/org",
                    "project": "Project",
                    "planId": 1,
                    "suiteId": 2,
                },
                "settings": {"uploadRunEvidence": False, "uploadResultEvidence": False},
                "runs": [{"name": "junit", "resultFormat": "junit", "resultFiles": ["*.xml"]}],
            }
        ),
        encoding="utf-8",
    )
    evidence = tmp_path / "run.log"
    evidence.write_text("run evidence", encoding="utf-8")
    attachment = Attachment(
        path=evidence,
        name=evidence.name,
        size_bytes=evidence.stat().st_size,
        mime_type="text/plain",
        attachment_level=AttachmentLevel.RUN,
    )
    publisher = AzureDevOpsPublisher(load_config(config_file), "secret")
    fake_client = FakeClient()
    publisher.client = fake_client  # type: ignore[assignment]

    with caplog.at_level(logging.WARNING):
        publisher.publish([TestResult("101", "x", "x", Outcome.PASSED)], [attachment])

    assert "Evidence files were eligible but no attachments were uploaded." in caplog.text
