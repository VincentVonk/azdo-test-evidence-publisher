from __future__ import annotations

from pathlib import Path

from azdo_test_publisher.evidence.collector import (
    EvidenceAssociator,
    EvidenceCollector,
    associate_evidence,
    associate_evidence_with_summary,
)
from azdo_test_publisher.models import Attachment, AttachmentLevel, Outcome, TestResult

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_evidence_collection_skips_unsupported_type() -> None:
    summary = EvidenceCollector(max_attachment_size_mb=25).collect(FIXTURES, "evidence")
    names = {attachment.name for attachment in summary.attachments}
    assert "TC-102-failure.png" in names
    assert "ignored.exe" not in names
    assert len(summary.skipped_type) == 1
    assert summary.scanned_count == 4
    assert summary.eligible_count == 3
    assert summary.skipped_type_count == 1
    assert summary.skipped_size_count == 0
    assert summary.directories_skipped_count == 1


def test_evidence_collection_counts_size_skips_and_directories(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    nested_dir = evidence_dir / "nested"
    nested_dir.mkdir(parents=True)
    eligible = evidence_dir / "TC-1.log"
    oversized = nested_dir / "TC-1.zip"
    unsupported = evidence_dir / "style.css"
    eligible.write_text("ok", encoding="utf-8")
    oversized.write_bytes(b"x" * 2)
    unsupported.write_text("css", encoding="utf-8")

    summary = EvidenceCollector(max_attachment_size_mb=0).collect(tmp_path, "evidence")

    assert summary.scanned_count == 3
    assert summary.eligible_count == 0
    assert summary.skipped_type_count == 1
    assert summary.skipped_size_count == 2
    assert summary.directories_skipped_count == 1


def test_evidence_association_by_tc_id_in_filename() -> None:
    summary = EvidenceCollector(max_attachment_size_mb=25).collect(FIXTURES, "evidence")
    results = [
        TestResult("102", "payment is rejected", "payment is rejected", Outcome.FAILED),
    ]
    attachments = associate_evidence(summary.attachments, results, "failed")
    by_name = {attachment.name: attachment for attachment in attachments}
    assert by_name["TC-102-failure.png"].attachment_level == AttachmentLevel.RESULT
    assert by_name["TC-102-failure.png"].related_test_case_id == "102"


def test_evidence_matching_summary_counts_tc_id_match() -> None:
    summary = EvidenceCollector(max_attachment_size_mb=25).collect(FIXTURES, "evidence")
    results = [
        TestResult("102", "payment is rejected", "payment is rejected", Outcome.FAILED),
        TestResult("999", "unmatched", "unmatched", Outcome.FAILED),
    ]

    _attachments, matching = associate_evidence_with_summary(summary.attachments, results, "failed")

    assert matching.tests_requiring_result_evidence == 2
    assert matching.tests_with_matched_evidence == 1
    assert matching.tests_without_matched_evidence == 1
    assert matching.result_level_files_matched == 1


def test_evidence_association_by_tc_id_in_directory(tmp_path: Path) -> None:
    directory = tmp_path / "TC-16444932" / "screenshots"
    directory.mkdir(parents=True)
    evidence = directory / "trace.zip"
    evidence.write_text("trace", encoding="utf-8")
    attachment = _attachment(evidence)
    result = TestResult("16444932", "release smoke", "release smoke", Outcome.FAILED)

    associations = EvidenceAssociator().associate([result], [attachment])

    assert associations["16444932"].evidence_files == [attachment]


def test_evidence_association_by_test_name(tmp_path: Path) -> None:
    evidence = tmp_path / "checkout completes successfully" / "screenshot.png"
    evidence.parent.mkdir()
    evidence.write_text("png", encoding="utf-8")
    attachment = _attachment(evidence)
    result = TestResult("42", "Checkout completes successfully", "Checkout completes successfully", Outcome.FAILED)

    associations = EvidenceAssociator().associate([result], [attachment])

    assert associations["42"].evidence_files == [attachment]


def test_evidence_association_deduplicates_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "TC-42.log"
    evidence.write_text("log", encoding="utf-8")
    attachment = _attachment(evidence)
    result = TestResult("42", "checkout", "checkout", Outcome.FAILED)

    associations = EvidenceAssociator().associate([result], [attachment, attachment])

    assert associations["42"].evidence_files == [attachment]


def test_evidence_association_no_match(tmp_path: Path) -> None:
    evidence = tmp_path / "unrelated.log"
    evidence.write_text("log", encoding="utf-8")
    attachment = _attachment(evidence)
    result = TestResult("42", "checkout", "checkout", Outcome.FAILED)

    associations = EvidenceAssociator().associate([result], [attachment])

    assert associations["42"].evidence_files == []


def test_evidence_association_custom_matcher(tmp_path: Path) -> None:
    evidence = tmp_path / "custom-artifact.log"
    evidence.write_text("log", encoding="utf-8")
    attachment = _attachment(evidence)
    result = TestResult("42", "checkout", "checkout", Outcome.FAILED)

    associations = EvidenceAssociator(custom_matchers=[lambda file, test: file.name.startswith("custom")]).associate(
        [result],
        [attachment],
    )

    assert associations["42"].evidence_files == [attachment]


def _attachment(path: Path) -> Attachment:
    return Attachment(
        path=path,
        name=path.name,
        size_bytes=path.stat().st_size,
        mime_type="application/octet-stream",
        attachment_level=AttachmentLevel.RUN,
    )
