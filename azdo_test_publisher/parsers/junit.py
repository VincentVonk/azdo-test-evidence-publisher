from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from azdo_test_publisher.models import Outcome, TestResult

from .base import ResultParser


class JUnitParser(ResultParser):
    def parse(self, path: Path) -> list[TestResult]:
        root = ET.parse(path).getroot()
        cases = root.findall(".//testcase")
        if root.tag.endswith("testcase"):
            cases = [root]

        results: list[TestResult] = []
        for case in cases:
            name = case.attrib.get("name", "")
            classname = case.attrib.get("classname", "")
            full_name = ".".join(part for part in [classname, name] if part)
            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")
            outcome = Outcome.PASSED
            message = None
            stacktrace = None
            if failure is not None or error is not None:
                node = failure if failure is not None else error
                outcome = Outcome.FAILED
                message = node.attrib.get("message") or (node.text or "").strip() or None
                stacktrace = (node.text or "").strip() or None
            elif skipped is not None:
                outcome = Outcome.SKIPPED
                message = skipped.attrib.get("message") or (skipped.text or "").strip() or None

            properties = []
            for prop in case.findall("./properties/property"):
                properties.extend([prop.attrib.get("name"), prop.attrib.get("value")])

            results.append(
                TestResult(
                    test_case_id=None,
                    name=name,
                    full_name=full_name or name,
                    outcome=outcome,
                    duration_ms=_seconds_to_ms(case.attrib.get("time")),
                    message=message,
                    stacktrace=stacktrace,
                    source_file=str(path),
                    evidence_hints=[],
                    mapping_candidates=[name, full_name, *properties],
                )
            )
        return results


def _seconds_to_ms(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value) * 1000)
    except ValueError:
        return None
