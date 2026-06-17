from __future__ import annotations

import json

import pytest

from azdo_test_publisher.azdo.publisher import AzureDevOpsPublisher
from azdo_test_publisher.config import load_config
from azdo_test_publisher.mapping import MappingError
from azdo_test_publisher.models import Outcome, TestResult


class FakeClient:
    def __init__(self) -> None:
        self.get_points_called = False

    def get_test_points(self, plan_id: int, suite_id: int):
        self.get_points_called = True
        return [{"id": 11, "testCase": {"id": "101"}}]

    def create_test_run(self, name: str, plan_id: int, point_ids: list[int]):
        return {"id": 99}

    def add_test_results(self, run_id: int, results: list[dict]):
        return [{"id": 1001, "testCase": {"id": "101"}}]

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

        def add_test_results(self, run_id: int, results: list[dict]):
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
    assert fake_client.results_payload[0]["durationInMs"] == "3"
    assert fake_client.results_payload[0]["automatedTestName"] == "Aggregated result for TC-101 (2 executions)"
