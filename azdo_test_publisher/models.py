from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Outcome(StrEnum):
    PASSED = "Passed"
    FAILED = "Failed"
    SKIPPED = "Skipped"
    NOT_APPLICABLE = "NotApplicable"


class AttachmentLevel(StrEnum):
    RUN = "run"
    RESULT = "result"


class DuplicateStrategy(StrEnum):
    FAIL = "fail"
    WORST_OUTCOME_WINS = "worst_outcome_wins"


@dataclass(slots=True)
class TestResult:
    __test__ = False

    test_case_id: str | None
    name: str
    full_name: str
    outcome: Outcome
    duration_ms: int | None = None
    message: str | None = None
    stacktrace: str | None = None
    source_file: str | None = None
    evidence_hints: list[str] = field(default_factory=list)
    mapping_candidates: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Attachment:
    __test__ = False

    path: Path
    name: str
    size_bytes: int
    mime_type: str
    attachment_level: AttachmentLevel
    related_test_case_id: str | None = None


@dataclass(slots=True)
class RunConfig:
    name: str
    result_format: str
    result_files: list[str]
    evidence_folder: str | None = None


@dataclass(slots=True)
class AzdoConfig:
    organization: str
    project: str
    plan_id: int
    suite_id: int
    token_env_var: str | None = None


@dataclass(slots=True)
class Settings:
    mapping_pattern: str = r"TC-(\d+)"
    allow_unmapped: bool = False
    allow_multiple_test_case_ids: bool = False
    duplicate_strategy: DuplicateStrategy = DuplicateStrategy.FAIL
    upload_run_evidence: bool = True
    upload_result_evidence: bool = True
    upload_result_evidence_for: str = "failed"
    max_attachment_size_mb: int = 25


@dataclass(slots=True)
class PublisherConfig:
    azdo: AzdoConfig
    settings: Settings
    runs: list[RunConfig]
    base_dir: Path
