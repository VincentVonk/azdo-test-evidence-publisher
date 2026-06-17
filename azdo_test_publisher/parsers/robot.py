from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from azdo_test_publisher.models import Outcome, TestResult

from .base import ResultParser


class RobotParser(ResultParser):
    def parse(self, path: Path) -> list[TestResult]:
        root = ET.parse(path).getroot()
        results: list[TestResult] = []
        for test in root.findall(".//test"):
            name = test.attrib.get("name", "")
            tags = [tag.text or "" for tag in test.findall("./tags/tag")]
            if not tags:
                tags = [tag.text or "" for tag in test.findall("./tag")]
            status = test.find("./status")
            status_value = (status.attrib.get("status") if status is not None else "").upper()
            outcome = {
                "PASS": Outcome.PASSED,
                "FAIL": Outcome.FAILED,
                "SKIP": Outcome.SKIPPED,
                "NOT RUN": Outcome.NOT_APPLICABLE,
            }.get(status_value, Outcome.NOT_APPLICABLE)
            message = (status.text or "").strip() if status is not None and status.text else None
            duration_ms = _robot_duration_ms(status)
            full_name = _robot_full_name(test, name)
            results.append(
                TestResult(
                    test_case_id=None,
                    name=name,
                    full_name=full_name,
                    outcome=outcome,
                    duration_ms=duration_ms,
                    message=message,
                    stacktrace=message if outcome == Outcome.FAILED else None,
                    source_file=str(path),
                    evidence_hints=tags.copy(),
                    mapping_candidates=[name, full_name, *tags],
                )
            )
        return results


def _robot_full_name(test: ET.Element, name: str) -> str:
    suite_names: list[str] = []
    parent = test
    # xml.etree has no parent pointer; the test name is sufficient for v1 display.
    return ".".join([*suite_names, name]) if suite_names else name


def _robot_duration_ms(status: ET.Element | None) -> int | None:
    if status is None:
        return None
    if "elapsed" in status.attrib:
        try:
            return int(float(status.attrib["elapsed"]) * 1000)
        except ValueError:
            return None
    if "elapsedtime" in status.attrib:
        try:
            return int(float(status.attrib["elapsedtime"]))
        except ValueError:
            return None
    return None
