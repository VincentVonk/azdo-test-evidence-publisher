from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from azdo_test_publisher.models import Outcome, TestResult

from .base import ResultParser


class NUnitParser(ResultParser):
    def parse(self, path: Path) -> list[TestResult]:
        root = ET.parse(path).getroot()
        results: list[TestResult] = []
        for case in root.findall(".//test-case"):
            name = case.attrib.get("name", "")
            full_name = case.attrib.get("fullname") or name
            result = case.attrib.get("result") or case.attrib.get("outcome")
            message = _text(case, "./failure/message") or _text(case, "./reason/message")
            stacktrace = _text(case, "./failure/stack-trace")
            properties = []
            for prop in case.findall("./properties/property"):
                properties.extend([prop.attrib.get("name"), prop.attrib.get("value")])
            categories = [
                prop.attrib.get("value")
                for prop in case.findall("./properties/property")
                if prop.attrib.get("name", "").lower() == "category"
            ]
            results.append(
                TestResult(
                    test_case_id=None,
                    name=name,
                    full_name=full_name,
                    outcome=_outcome(result),
                    duration_ms=_seconds_to_ms(case.attrib.get("duration")),
                    message=message,
                    stacktrace=stacktrace,
                    source_file=str(path),
                    evidence_hints=[item for item in categories if item],
                    mapping_candidates=[name, full_name, *properties],
                )
            )
        return results


def _text(node: ET.Element, xpath: str) -> str | None:
    found = node.find(xpath)
    return found.text.strip() if found is not None and found.text else None


def _outcome(value: str | None) -> Outcome:
    normalized = (value or "").lower()
    if normalized in {"passed", "success"}:
        return Outcome.PASSED
    if normalized in {"failed", "failure", "error"}:
        return Outcome.FAILED
    if normalized in {"skipped", "ignored", "inconclusive"}:
        return Outcome.SKIPPED
    return Outcome.NOT_APPLICABLE


def _seconds_to_ms(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(float(value) * 1000)
    except ValueError:
        return None
