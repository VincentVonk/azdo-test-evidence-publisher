from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
import logging
from mimetypes import guess_type
from pathlib import Path
import re
from typing import Callable

from azdo_test_publisher.models import Attachment, AttachmentLevel, Outcome, TestResult
from .patterns import DEFAULT_EXCLUDE_PATTERNS, DEFAULT_RESULT_LEVEL_INCLUDE_PATTERNS, DEFAULT_RUN_LEVEL_INCLUDE_PATTERNS

logger = logging.getLogger(__name__)


SUPPORTED_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".txt",
    ".log",
    ".json",
    ".xml",
    ".html",
    ".zip",
    ".webm",
}

EvidenceMatcher = Callable[[Attachment, TestResult], bool]


@dataclass(slots=True)
class EvidenceSummary:
    attachments: list[Attachment] = field(default_factory=list)
    skipped_size: list[Path] = field(default_factory=list)
    skipped_type: list[Path] = field(default_factory=list)
    scanned_count: int = 0
    directories_skipped_count: int = 0

    @property
    def eligible_count(self) -> int:
        return len(self.attachments)

    @property
    def skipped_size_count(self) -> int:
        return len(self.skipped_size)

    @property
    def skipped_type_count(self) -> int:
        return len(self.skipped_type)


@dataclass(slots=True)
class EvidenceMatchingSummary:
    tests_requiring_result_evidence: int = 0
    tests_with_matched_evidence: int = 0
    tests_without_matched_evidence: int = 0
    result_level_files_matched: int = 0
    run_level_files_selected: int = 0


class EvidenceCollector:
    def __init__(
        self,
        max_attachment_size_mb: int = 25,
        run_level_include_patterns: list[str] | None = None,
        run_level_exclude_patterns: list[str] | None = None,
        result_level_include_patterns: list[str] | None = None,
        result_level_exclude_patterns: list[str] | None = None,
    ) -> None:
        self.max_bytes = max_attachment_size_mb * 1024 * 1024
        self.run_level_include_patterns = (
            run_level_include_patterns
            if run_level_include_patterns is not None
            else DEFAULT_RUN_LEVEL_INCLUDE_PATTERNS
        )
        self.run_level_exclude_patterns = (
            run_level_exclude_patterns
            if run_level_exclude_patterns is not None
            else DEFAULT_EXCLUDE_PATTERNS
        )
        self.result_level_include_patterns = (
            result_level_include_patterns
            if result_level_include_patterns is not None
            else DEFAULT_RESULT_LEVEL_INCLUDE_PATTERNS
        )
        self.result_level_exclude_patterns = (
            result_level_exclude_patterns
            if result_level_exclude_patterns is not None
            else DEFAULT_EXCLUDE_PATTERNS
        )

    def collect(self, base_dir: Path, evidence_folder: str | None) -> EvidenceSummary:
        summary = EvidenceSummary()
        if not evidence_folder:
            return summary
        folders = list(base_dir.glob(evidence_folder)) if not Path(evidence_folder).is_absolute() else [Path(evidence_folder)]
        files: list[Path] = []
        for folder in folders:
            if folder.is_file():
                files.append(folder)
            elif folder.is_dir():
                for path in folder.rglob("*"):
                    if path.is_dir():
                        summary.directories_skipped_count += 1
                    elif path.is_file():
                        files.append(path)
        for path in sorted(set(file.resolve() for file in files)):
            summary.scanned_count += 1
            attachment_level = self._candidate_level(path)
            if attachment_level is None:
                summary.skipped_type.append(path)
                logger.debug("Evidence skipped by include/exclude pattern: %s", path)
                continue
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                summary.skipped_type.append(path)
                logger.debug("Evidence skipped due to unsupported type: %s", path)
                continue
            size = path.stat().st_size
            if size > self.max_bytes:
                summary.skipped_size.append(path)
                logger.debug("Evidence skipped due to size limit: %s", path)
                continue
            mime_type = guess_type(path.name)[0] or "application/octet-stream"
            logger.debug("Evidence eligible: path=%s level=%s size=%s", path, attachment_level.value, size)
            summary.attachments.append(
                Attachment(
                    path=path,
                    name=path.name,
                    size_bytes=size,
                    mime_type=mime_type,
                    attachment_level=attachment_level,
                )
            )
        return summary

    def _candidate_level(self, path: Path) -> AttachmentLevel | None:
        if self._matches(path, self.run_level_include_patterns) and not self._matches(path, self.run_level_exclude_patterns):
            return AttachmentLevel.RUN
        if self._matches(path, self.result_level_include_patterns) and not self._matches(path, self.result_level_exclude_patterns):
            return AttachmentLevel.RESULT
        return None

    def _matches(self, path: Path, patterns: list[str]) -> bool:
        value = _path_for_matching(path)
        return any(fnmatch(value, pattern) or fnmatch(path.name, pattern) for pattern in patterns)


@dataclass(slots=True)
class EvidenceAssociation:
    result: TestResult
    evidence_files: list[Attachment] = field(default_factory=list)


class EvidenceAssociator:
    def __init__(
        self,
        tc_id_pattern: str = r"TC-(\d+)",
        custom_matchers: list[EvidenceMatcher] | None = None,
        detailed_logging: bool = False,
    ) -> None:
        self.tc_id_regex = re.compile(tc_id_pattern, re.IGNORECASE)
        self.custom_matchers = custom_matchers or []
        self.detailed_logging = detailed_logging

    def associate(
        self,
        results: list[TestResult],
        attachments: list[Attachment],
    ) -> dict[str, EvidenceAssociation]:
        associations = {
            result.test_case_id: EvidenceAssociation(result=result)
            for result in results
            if result.test_case_id
        }
        seen_by_result: dict[str, set[Path]] = {test_case_id: set() for test_case_id in associations}
        unique_attachments = _deduplicate_attachments(attachments)

        for result in results:
            if not result.test_case_id:
                continue
            for attachment in unique_attachments:
                strategy = self._match_strategy(attachment, result)
                if not strategy:
                    continue
                resolved_path = attachment.path.resolve()
                if resolved_path in seen_by_result[result.test_case_id]:
                    continue
                associations[result.test_case_id].evidence_files.append(attachment)
                seen_by_result[result.test_case_id].add(resolved_path)
                if self.detailed_logging:
                    logger.info("Matched evidence")
                    logger.info("  tcId=%s", result.test_case_id)
                    logger.info("  file=%s", attachment.name)
                    logger.info("  strategy=%s", strategy)

        for test_case_id, association in associations.items():
            if not association.evidence_files:
                logger.debug("No evidence matched: tcId=%s", test_case_id)

        return associations

    def _match_strategy(self, attachment: Attachment, result: TestResult) -> str | None:
        if self._matches_tc_id(attachment, result.test_case_id):
            return "tcId"
        if self._matches_test_name(attachment, result):
            return "testName"
        for index, matcher in enumerate(self.custom_matchers, start=1):
            if matcher(attachment, result):
                return f"custom:{index}"
        return None

    def _matches_tc_id(self, attachment: Attachment, test_case_id: str | None) -> bool:
        if not test_case_id:
            return False
        for value in _path_search_values(attachment.path):
            ids = [match.group(1) if match.groups() else match.group(0) for match in self.tc_id_regex.finditer(value)]
            if test_case_id in ids:
                return True
        return False

    def _matches_test_name(self, attachment: Attachment, result: TestResult) -> bool:
        normalized_name = _normalize(result.name)
        if not normalized_name:
            return False
        return normalized_name in _normalize(str(attachment.path))


def associate_evidence_with_summary(
    attachments: list[Attachment],
    results: list[TestResult],
    upload_result_evidence_for: str = "failed",
    tc_id_pattern: str = r"TC-(\d+)",
    custom_matchers: list[EvidenceMatcher] | None = None,
    detailed_logging: bool = False,
) -> tuple[list[Attachment], EvidenceMatchingSummary]:
    by_id = {result.test_case_id: result for result in results if result.test_case_id}
    result_scope = upload_result_evidence_for.lower()
    associator = EvidenceAssociator(
        tc_id_pattern=tc_id_pattern,
        custom_matchers=custom_matchers,
        detailed_logging=detailed_logging,
    )
    associations = associator.associate(results, attachments)
    associated = _deduplicate_attachments(attachments)
    attachment_by_path = {attachment.path.resolve(): attachment for attachment in associated}
    matching_summary = EvidenceMatchingSummary()
    for test_case_id, association in associations.items():
        matched_result = by_id.get(test_case_id)
        if not matched_result or not _outcome_allowed(matched_result, result_scope):
            continue
        matching_summary.tests_requiring_result_evidence += 1
        if association.evidence_files:
            matching_summary.tests_with_matched_evidence += 1
        else:
            matching_summary.tests_without_matched_evidence += 1
            if detailed_logging:
                logger.warning("No result-level evidence matched")
                logger.warning("  tcId=%s", matched_result.test_case_id)
                logger.warning("  testName=%s", matched_result.name)
        for evidence_file in association.evidence_files:
            attachment = attachment_by_path[evidence_file.path.resolve()]
            attachment.attachment_level = AttachmentLevel.RESULT
            attachment.related_test_case_id = matched_result.test_case_id
    matching_summary.result_level_files_matched = sum(
        1
        for attachment in associated
        if attachment.attachment_level == AttachmentLevel.RESULT and attachment.related_test_case_id
    )
    matching_summary.run_level_files_selected = sum(
        1 for attachment in associated if attachment.attachment_level == AttachmentLevel.RUN
    )
    return associated, matching_summary


def associate_evidence(
    attachments: list[Attachment],
    results: list[TestResult],
    upload_result_evidence_for: str = "failed",
    tc_id_pattern: str = r"TC-(\d+)",
    custom_matchers: list[EvidenceMatcher] | None = None,
    detailed_logging: bool = False,
) -> list[Attachment]:
    associated, _summary = associate_evidence_with_summary(
        attachments,
        results,
        upload_result_evidence_for,
        tc_id_pattern,
        custom_matchers,
        detailed_logging,
    )
    return associated


def _deduplicate_attachments(attachments: list[Attachment]) -> list[Attachment]:
    seen: set[Path] = set()
    unique: list[Attachment] = []
    for attachment in attachments:
        path = attachment.path.resolve()
        if path in seen:
            continue
        seen.add(path)
        unique.append(attachment)
    return unique


def _path_search_values(path: Path) -> list[str]:
    resolved = path.resolve()
    return [resolved.name, *[parent.name for parent in resolved.parents], str(resolved)]


def _normalize(value: str) -> str:
    return "".join(re.findall(r"[a-z0-9]+", value.lower()))


def _path_for_matching(path: Path) -> str:
    return str(path).replace("\\", "/")


def _outcome_allowed(result: TestResult, result_scope: str) -> bool:
    if result_scope == "all":
        return True
    if result_scope == "failed":
        return result.outcome == Outcome.FAILED
    if result_scope == "passed":
        return result.outcome == Outcome.PASSED
    return False
