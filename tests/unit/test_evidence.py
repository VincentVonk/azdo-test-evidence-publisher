from __future__ import annotations

from pathlib import Path

from azdo_test_publisher.evidence.collector import EvidenceAssociator, EvidenceCollector, associate_evidence
from azdo_test_publisher.models import Attachment, AttachmentLevel, Outcome, TestResult

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_evidence_collection_skips_unsupported_type() -> None:
    summary = EvidenceCollector(max_attachment_size_mb=25).collect(FIXTURES, "evidence")
    names = {attachment.name for attachment in summary.attachments}
    assert "TC-102-failure.png" in names
    assert "ignored.exe" not in names
    assert len(summary.skipped_type) == 1


def test_evidence_association_by_tc_id_in_filename() -> None:
    summary = EvidenceCollector(max_attachment_size_mb=25).collect(FIXTURES, "evidence")
    results = [
        TestResult("102", "payment is rejected", "payment is rejected", Outcome.FAILED),
    ]
    attachments = associate_evidence(summary.attachments, results, "failed")
    by_name = {attachment.name: attachment for attachment in attachments}
    assert by_name["TC-102-failure.png"].attachment_level == AttachmentLevel.RESULT
    assert by_name["TC-102-failure.png"].related_test_case_id == "102"


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
