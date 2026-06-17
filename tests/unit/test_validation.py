from __future__ import annotations

import json
from pathlib import Path

import pytest

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
