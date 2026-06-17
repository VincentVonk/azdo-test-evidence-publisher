from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from azdo_test_publisher.models import TestResult


class ResultParser(ABC):
    @abstractmethod
    def parse(self, path: Path) -> list[TestResult]:
        raise NotImplementedError
