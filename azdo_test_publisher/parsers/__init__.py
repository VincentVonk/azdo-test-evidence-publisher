from __future__ import annotations

from .base import ResultParser
from .junit import JUnitParser
from .nunit import NUnitParser
from .robot import RobotParser
from .trx import TRXParser


def get_parser(result_format: str) -> ResultParser:
    parsers: dict[str, ResultParser] = {
        "junit": JUnitParser(),
        "robot": RobotParser(),
        "trx": TRXParser(),
        "nunit": NUnitParser(),
    }
    try:
        return parsers[result_format.lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported resultFormat '{result_format}'") from exc
