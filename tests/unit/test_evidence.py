from __future__ import annotations

from pathlib import Path

from azdo_test_publisher.evidence.collector import EvidenceCollector, associate_evidence
from azdo_test_publisher.models import AttachmentLevel, Outcome, TestResult

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_evidence_collection_skips_unsupported_type() -> None:
    summary = EvidenceCollector(max_attachment_size_mb=25).collect(FIXTURES, "evidence")
    names = {attachment.name for attachment in summary.attachments}
    assert "TC-102-failure.png" in names
    assert "ignored.exe" not in names
    assert len(summary.skipped_type) == 1


def test_evidence_association_by_tc_id_and_robot_run_level() -> None:
    summary = EvidenceCollector(max_attachment_size_mb=25).collect(FIXTURES, "evidence")
    results = [
        TestResult("102", "payment is rejected", "payment is rejected", Outcome.FAILED),
        TestResult("201", "User can sign in", "User can sign in", Outcome.PASSED),
    ]
    attachments = associate_evidence(summary.attachments, results, "failed")
    by_name = {attachment.name: attachment for attachment in attachments}
    assert by_name["TC-102-failure.png"].attachment_level == AttachmentLevel.RESULT
    assert by_name["TC-102-failure.png"].related_test_case_id == "102"
    assert by_name["output.xml"].attachment_level == AttachmentLevel.RUN
