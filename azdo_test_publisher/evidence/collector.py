from __future__ import annotations

from dataclasses import dataclass, field
from mimetypes import guess_type
from pathlib import Path
import re

from azdo_test_publisher.models import Attachment, AttachmentLevel, Outcome, TestResult


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
ROBOT_RUN_LEVEL = {"output.xml", "log.html", "report.html"}


@dataclass(slots=True)
class EvidenceSummary:
    attachments: list[Attachment] = field(default_factory=list)
    skipped_size: list[Path] = field(default_factory=list)
    skipped_type: list[Path] = field(default_factory=list)


class EvidenceCollector:
    def __init__(self, max_attachment_size_mb: int = 25) -> None:
        self.max_bytes = max_attachment_size_mb * 1024 * 1024

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
                files.extend(path for path in folder.rglob("*") if path.is_file())
        for path in sorted(set(file.resolve() for file in files)):
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                summary.skipped_type.append(path)
                continue
            size = path.stat().st_size
            if size > self.max_bytes:
                summary.skipped_size.append(path)
                continue
            mime_type = guess_type(path.name)[0] or "application/octet-stream"
            summary.attachments.append(
                Attachment(
                    path=path,
                    name=path.name,
                    size_bytes=size,
                    mime_type=mime_type,
                    attachment_level=AttachmentLevel.RUN,
                )
            )
        return summary


def associate_evidence(
    attachments: list[Attachment],
    results: list[TestResult],
    upload_result_evidence_for: str = "failed",
) -> list[Attachment]:
    by_id = {result.test_case_id: result for result in results if result.test_case_id}
    result_scope = upload_result_evidence_for.lower()
    associated: list[Attachment] = []
    for attachment in attachments:
        if attachment.name.lower() in ROBOT_RUN_LEVEL:
            associated.append(attachment)
            continue
        text = str(attachment.path).lower()
        matched_id = _match_by_tc_id(text, by_id.keys()) or _match_by_title(text, results)
        matched_result = by_id.get(matched_id) if matched_id else None
        if matched_result and _outcome_allowed(matched_result, result_scope):
            attachment.attachment_level = AttachmentLevel.RESULT
            attachment.related_test_case_id = matched_result.test_case_id
        associated.append(attachment)
    return associated


def _match_by_tc_id(text: str, test_case_ids: object) -> str | None:
    for test_case_id in test_case_ids:
        if test_case_id and re.search(rf"(tc[-_ ]?)?{re.escape(str(test_case_id).lower())}", text):
            return str(test_case_id)
    return None


def _match_by_title(text: str, results: list[TestResult]) -> str | None:
    for result in results:
        if not result.test_case_id:
            continue
        fragments = [fragment for fragment in re.split(r"[^a-z0-9]+", result.name.lower()) if len(fragment) >= 4]
        if fragments and all(fragment in text for fragment in fragments[:4]):
            return result.test_case_id
    return None


def _outcome_allowed(result: TestResult, result_scope: str) -> bool:
    if result_scope == "all":
        return True
    if result_scope == "failed":
        return result.outcome == Outcome.FAILED
    if result_scope == "passed":
        return result.outcome == Outcome.PASSED
    return False
