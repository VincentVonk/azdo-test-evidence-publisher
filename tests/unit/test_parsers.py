from __future__ import annotations

from pathlib import Path

from azdo_test_publisher.mapping import apply_mapping
from azdo_test_publisher.models import Outcome
from azdo_test_publisher.parsers.junit import JUnitParser
from azdo_test_publisher.parsers.nunit import NUnitParser
from azdo_test_publisher.parsers.robot import RobotParser
from azdo_test_publisher.parsers.trx import TRXParser

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_junit_parsing() -> None:
    results = apply_mapping(JUnitParser().parse(FIXTURES / "junit" / "results.xml"), r"TC-(\d+)")
    assert len(results) == 3
    assert results[0].test_case_id == "101"
    assert results[1].outcome == Outcome.FAILED
    assert results[2].outcome == Outcome.SKIPPED


def test_robot_parsing() -> None:
    results = apply_mapping(RobotParser().parse(FIXTURES / "robot" / "output.xml"), r"TC-(\d+)")
    assert len(results) == 2
    assert results[0].test_case_id == "201"
    assert results[1].message == "Expected confirmation page"
    assert results[1].duration_ms == 100


def test_trx_parsing() -> None:
    results = apply_mapping(TRXParser().parse(FIXTURES / "trx" / "results.trx"), r"TC-(\d+)")
    assert len(results) == 2
    assert results[0].test_case_id == "301"
    assert results[0].full_name == "CalculatorTests.TC-301 Calculator adds"
    assert results[0].duration_ms == 1250
    assert results[1].stacktrace == "at CalculatorTests.Divides()"


def test_nunit_parsing() -> None:
    results = apply_mapping(NUnitParser().parse(FIXTURES / "nunit" / "results.xml"), r"TC-(\d+)")
    assert len(results) == 2
    assert results[0].test_case_id == "401"
    assert results[1].test_case_id == "402"
    assert results[1].outcome == Outcome.FAILED
