from __future__ import annotations

import base64
import logging
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class AzureDevOpsError(RuntimeError):
    pass


class AzureDevOpsClient:
    def __init__(self, organization: str, project: str, token: str) -> None:
        self.organization = organization.rstrip("/")
        self.project = project
        self.session = requests.Session()
        encoded = base64.b64encode(f":{token}".encode("utf-8")).decode("ascii")
        self.session.headers.update(
            {
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def get_test_points(self, plan_id: int, suite_id: int) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            f"_apis/test/Plans/{plan_id}/Suites/{suite_id}/points",
            params={"api-version": "7.1-preview.2"},
        )
        return response.get("value", [])

    def create_test_run(self, name: str, plan_id: int, point_ids: list[int]) -> dict[str, Any]:
        payload = {
            "name": name,
            "plan": {"id": str(plan_id)},
            "pointIds": [str(point_id) for point_id in point_ids],
            "automated": True,
            "state": "InProgress",
        }
        return self._request("POST", "_apis/test/runs", json=payload, params={"api-version": "7.1-preview.3"})

    def add_test_results(self, run_id: int, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        response = self._request(
            "POST",
            f"_apis/test/Runs/{run_id}/results",
            json=results,
            params={"api-version": "7.1-preview.6"},
        )
        return response.get("value", [])

    def update_test_results(self, run_id: int, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        response = self._request(
            "PATCH",
            f"_apis/test/Runs/{run_id}/results",
            json=results,
            params={"api-version": "7.1-preview.6"},
        )
        return response.get("value", [])

    def get_results_by_run(self, run_id: int) -> dict[int, dict[str, Any]]:
        response = self._request(
            "GET",
            f"_apis/test/Runs/{run_id}/results",
            params={"api-version": "7.1-preview.6"},
        )
        mapped: dict[int, dict[str, Any]] = {}
        for result in response.get("value", []):
            point_id = _result_point_id(result)
            result_id = result.get("id")
            if point_id is None or result_id is None:
                continue
            mapped[int(point_id)] = {
                "result_id": int(result_id),
                "test_case_id": str((result.get("testCase") or {}).get("id") or result.get("testCaseId") or ""),
            }
        return mapped

    def get_testcase_metadata(self, test_case_id: str) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"_apis/wit/workitems/{test_case_id}",
            params={"api-version": "7.1"},
        )
        fields = response.get("fields") or {}
        return {
            "rev": response.get("rev") or fields.get("System.Rev"),
            "title": fields.get("System.Title"),
        }

    def upload_run_attachment(self, run_id: int, name: str, data: bytes, comment: str = "") -> dict[str, Any]:
        return self._upload_attachment(f"_apis/test/Runs/{run_id}/attachments", name, data, comment)

    def upload_result_attachment(self, run_id: int, result_id: int, name: str, data: bytes, comment: str = "") -> dict[str, Any]:
        return self._upload_attachment(f"_apis/test/Runs/{run_id}/Results/{result_id}/attachments", name, data, comment)

    def complete_test_run(self, run_id: int) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"_apis/test/runs/{run_id}",
            json={"state": "Completed"},
            params={"api-version": "7.1-preview.3"},
        )

    def _upload_attachment(self, endpoint: str, name: str, data: bytes, comment: str) -> dict[str, Any]:
        payload = {
            "stream": base64.b64encode(data).decode("ascii"),
            "fileName": name,
            "comment": comment,
            "attachmentType": "GeneralAttachment",
        }
        return self._request("POST", endpoint, json=payload, params={"api-version": "7.1-preview.1"})

    @retry(
        retry=retry_if_exception_type((requests.RequestException, AzureDevOpsError)),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _request(self, method: str, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.organization}/{self.project}/{endpoint.lstrip('/')}"
        logger.debug("Azure DevOps REST request: method=%s url=%s params=%s json=%s", method, url, kwargs.get("params"), kwargs.get("json"))
        response = self.session.request(method, url, timeout=30, **kwargs)
        logger.debug("Azure DevOps REST response: status=%s body=%s", response.status_code, response.text)
        if response.status_code in {408, 429, 500, 502, 503, 504}:
            raise AzureDevOpsError(f"Transient Azure DevOps API failure: HTTP {response.status_code}")
        if not response.ok:
            raise AzureDevOpsError(f"Azure DevOps API failure: HTTP {response.status_code}: {response.text}")
        if not response.content:
            return {}
        return response.json()


def _result_point_id(result: dict[str, Any]) -> int | None:
    point = result.get("testPoint") or {}
    value = point.get("id") or result.get("testPointId") or result.get("pointId")
    return int(value) if value not in (None, "") else None
