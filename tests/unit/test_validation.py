from __future__ import annotations

import json
from pathlib import Path

import pytest

from azdo_test_publisher import cli
from azdo_test_publisher.cli import validate_config
from azdo_test_publisher.mapping import MappingError


def test_validation_uses_fixtures_without_azdo_calls() -> None:
    config = Path(__file__).parents[2] / "examples" / "publisher.json"
    validation = validate_config(config)
    assert len(validation.result_files) == 4
    assert len(validation.results) == 9
    assert all(result.test_case_id for result in validation.results)
    assert validation.attachments


def test_validation_fails_when_duplicate_strategy_fail(tmp_path: Path) -> None:
    duplicate_file = tmp_path / "results.xml"
    duplicate_file.write_text(
        """
<testsuite>
  <testcase classname="A" name="TC-1 first"/>
  <testcase classname="B" name="TC-1 second"/>
</testsuite>
""",
        encoding="utf-8",
    )
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
                "runs": [{"name": "junit", "resultFormat": "junit", "resultFiles": ["results.xml"]}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(MappingError) as exc:
        validate_config(config_file)

    message = str(exc.value)
    assert "TC-1" in message
    assert "TC-1 first" in message
    assert "TC-1 second" in message


def test_validation_report_json(tmp_path: Path) -> None:
    config = Path(__file__).parents[2] / "examples" / "publisher.json"
    validation = validate_config(config)
    output = tmp_path / "validation-report.json"

    cli.write_validation_report(validation, output)

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["publishReady"] is True
    assert report["results"]["fileCount"] == 4
    assert report["results"]["testsParsed"] == 9
    assert report["results"]["testsWithoutTcIds"] == 0
    assert report["evidence"]["filesScanned"] >= 4
    assert report["evidence"]["filesEligible"] == 4
    assert report["evidence"]["matching"]["resultLevelFilesMatched"] == 1


def test_publish_command_does_not_call_azdo_when_validation_fails(tmp_path: Path, monkeypatch) -> None:
    duplicate_file = tmp_path / "results.xml"
    duplicate_file.write_text(
        """
<testsuite>
  <testcase classname="A" name="TC-1 first"/>
  <testcase classname="B" name="TC-1 second"/>
</testsuite>
""",
        encoding="utf-8",
    )
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
                "runs": [{"name": "junit", "resultFormat": "junit", "resultFiles": ["results.xml"]}],
            }
        ),
        encoding="utf-8",
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("AzureDevOpsPublisher should not be constructed")

    monkeypatch.setattr(cli, "AzureDevOpsPublisher", fail_if_called)

    assert cli.main(["publish", "--config", str(config_file)]) == 2
