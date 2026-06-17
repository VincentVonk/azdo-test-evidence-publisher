from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

from azdo_test_publisher.models import Outcome, TestResult

from .base import ResultParser


class TRXParser(ResultParser):
    def parse(self, path: Path) -> list[TestResult]:
        root = ET.parse(path).getroot()
        ns = _ns(root)
        definitions = {
            unit.attrib.get("id"): {
                "name": unit.attrib.get("name", ""),
                "class": _find_text_attr(unit, f".//{ns}TestMethod", "className")
                or _find_text_attr(unit, f".//{ns}TestClass", "className"),
            }
            for unit in root.findall(f".//{ns}UnitTest")
        }
        results: list[TestResult] = []
        for node in root.findall(f".//{ns}UnitTestResult"):
            test_id = node.attrib.get("testId")
            definition = definitions.get(test_id, {})
            name = node.attrib.get("testName") or definition.get("name") or ""
            class_name = definition.get("class") or ""
            full_name = ".".join(part for part in [class_name, name] if part) or name
            outcome = _outcome(node.attrib.get("outcome"))
            message_node = node.find(f".//{ns}Message")
            stack_node = node.find(f".//{ns}StackTrace")
            message = message_node.text.strip() if message_node is not None and message_node.text else None
            stacktrace = stack_node.text.strip() if stack_node is not None and stack_node.text else None
            results.append(
                TestResult(
                    test_case_id=None,
                    name=name,
                    full_name=full_name,
                    outcome=outcome,
                    duration_ms=_duration_to_ms(node.attrib.get("duration")),
                    message=message,
                    stacktrace=stacktrace,
                    source_file=str(path),
                    evidence_hints=[],
                    mapping_candidates=[name, full_name],
                )
            )
        return results


def _ns(root: ET.Element) -> str:
    if root.tag.startswith("{"):
        return root.tag.split("}", 1)[0] + "}"
    return ""


def _find_text_attr(node: ET.Element, xpath: str, attr: str) -> str | None:
    found = node.find(xpath)
    return found.attrib.get(attr) if found is not None else None


def _outcome(value: str | None) -> Outcome:
    normalized = (value or "").lower()
    if normalized in {"passed"}:
        return Outcome.PASSED
    if normalized in {"failed", "error", "timeout"}:
        return Outcome.FAILED
    if normalized in {"notexecuted", "not executed", "skipped"}:
        return Outcome.SKIPPED
    return Outcome.NOT_APPLICABLE


def _duration_to_ms(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parts = value.split(":")
        hours, minutes = int(parts[0]), int(parts[1])
        seconds = float(parts[2])
        return int(timedelta(hours=hours, minutes=minutes, seconds=seconds).total_seconds() * 1000)
    except (IndexError, ValueError):
        return None
