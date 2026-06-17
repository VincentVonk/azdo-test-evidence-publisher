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
    oversized = nested_dir / "trace.zip"
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


def test_evidence_collection_excludes_default_report_assets(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    allowed_trace = evidence_dir / "trace.zip"
    excluded_html = evidence_dir / "index.html"
    excluded_json = evidence_dir / ".last-run.json"
    excluded_css = evidence_dir / "style.css"
    allowed_trace.write_text("trace", encoding="utf-8")
    excluded_html.write_text("html", encoding="utf-8")
    excluded_json.write_text("json", encoding="utf-8")
    excluded_css.write_text("css", encoding="utf-8")

    summary = EvidenceCollector(
        max_attachment_size_mb=25,
        run_level_exclude_patterns=[
            "**/index.html",
            "**/.last-run.json",
            "**/*.css",
        ],
        result_level_exclude_patterns=[
            "**/index.html",
            "**/.last-run.json",
            "**/*.css",
        ],
    ).collect(tmp_path, "evidence")

    assert summary.scanned_count == 4
    assert summary.eligible_count == 1
    assert summary.attachments[0].name == "trace.zip"
    assert summary.skipped_type_count == 3


def test_evidence_collection_include_exclude_override(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    trace = evidence_dir / "trace.zip"
    screenshot = evidence_dir / "screenshot.png"
    trace.write_text("trace", encoding="utf-8")
    screenshot.write_text("png", encoding="utf-8")

    summary = EvidenceCollector(
        max_attachment_size_mb=25,
        run_level_include_patterns=[],
        run_level_exclude_patterns=[],
        result_level_include_patterns=["**/*.zip"],
        result_level_exclude_patterns=[],
    ).collect(tmp_path, "evidence")

    assert summary.eligible_count == 1
    assert summary.attachments[0].name == "trace.zip"


def test_default_evidence_selection_keeps_playwright_trace_and_excludes_report_internals(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    evidence_dir = root / "test-results" / "TC-42"
    report_dir = root / "playwright-report"
    evidence_dir.mkdir(parents=True)
    report_dir.mkdir()
    trace = evidence_dir / "trace.zip"
    screenshot = evidence_dir / "screenshot.png"
    video = evidence_dir / "video.webm"
    report_index = report_dir / "index.html"
    report_js = report_dir / "bundle.js"
    report_svg = report_dir / "icon.svg"
    trace.write_text("trace", encoding="utf-8")
    screenshot.write_text("png", encoding="utf-8")
    video.write_text("webm", encoding="utf-8")
    report_index.write_text("html", encoding="utf-8")
    report_js.write_text("js", encoding="utf-8")
    report_svg.write_text("svg", encoding="utf-8")

    summary = EvidenceCollector(max_attachment_size_mb=25).collect(tmp_path, "evidence")

    names = {attachment.name for attachment in summary.attachments}
    assert {"trace.zip", "screenshot.png", "video.webm"}.issubset(names)
    assert "index.html" not in names
    assert "bundle.js" not in names
    assert "icon.svg" not in names


def test_default_evidence_selection_keeps_robot_summary_files_as_run_level(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "robot-results"
    evidence_dir.mkdir()
    output = evidence_dir / "output.xml"
    log = evidence_dir / "log.html"
    report = evidence_dir / "report.html"
    output.write_text("xml", encoding="utf-8")
    log.write_text("html", encoding="utf-8")
    report.write_text("html", encoding="utf-8")

    summary = EvidenceCollector(max_attachment_size_mb=25).collect(tmp_path, "robot-results")

    by_name = {attachment.name: attachment for attachment in summary.attachments}
    assert by_name["output.xml"].attachment_level == AttachmentLevel.RUN
    assert by_name["log.html"].attachment_level == AttachmentLevel.RUN
    assert by_name["report.html"].attachment_level == AttachmentLevel.RUN


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
