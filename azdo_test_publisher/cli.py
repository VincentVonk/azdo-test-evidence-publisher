from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .azdo.publisher import AzureDevOpsPublisher
from .config import ConfigError, load_config, resolve_token
from .evidence.collector import (
    EvidenceCollector,
    EvidenceMatchingSummary,
    EvidenceSummary,
    associate_evidence_with_summary,
)
from .mapping import (
    MappingError,
    apply_mapping,
    duplicate_results_by_test_case_id,
    format_duplicate_error,
    resolve_duplicate_results,
    summarize_mapping,
)
from .models import DuplicateStrategy
from .models import Attachment, PublisherConfig, TestResult
from .parsers import get_parser
from .utils.files import resolve_globs
from .utils.logging import configure_logging

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ValidationResult:
    config: PublisherConfig
    result_files: list[Path] = field(default_factory=list)
    results: list[TestResult] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    evidence: EvidenceSummary = field(default_factory=EvidenceSummary)
    evidence_matching: EvidenceMatchingSummary = field(default_factory=EvidenceMatchingSummary)
    errors: list[str] = field(default_factory=list)
    duplicate_details: dict[str, list[TestResult]] = field(default_factory=dict)
    publish_ready: bool = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="azdo-test-evidence-publisher")
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "publish"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--config", required=True)
        if command == "validate":
            sub.add_argument("--output", help="Write a JSON validation report to this path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    try:
        validation = validate_config(args.config, enforce=args.command == "publish")
        if args.command == "validate" and args.output:
            write_validation_report(validation, args.output)
        if args.command == "publish":
            token = resolve_token(validation.config)
            if not token:
                raise ConfigError("No Azure DevOps token found in tokenEnvVar, AZDO_TOKEN, or AZDO_PAT")
            AzureDevOpsPublisher(validation.config, token).publish(validation.results, validation.attachments)
        if validation.errors:
            raise MappingError("; ".join(validation.errors))
        return 0
    except (ConfigError, MappingError, ValueError) as exc:
        logger.error(str(exc))
        return 2


def validate_config(config_path: str | Path, enforce: bool = True) -> ValidationResult:
    config = load_config(config_path)
    validation = ValidationResult(config=config)
    collector = EvidenceCollector(config.settings.max_attachment_size_mb)

    for run in config.runs:
        parser = get_parser(run.result_format)
        result_files = resolve_globs(config.base_dir, run.result_files)
        if not result_files:
            logger.warning("Run '%s' discovered no result files", run.name)
        validation.result_files.extend(result_files)
        for result_file in result_files:
            parsed = parser.parse(result_file)
            apply_mapping(parsed, config.settings.mapping_pattern, config.settings.allow_multiple_test_case_ids)
            validation.results.extend(parsed)
        evidence = collector.collect(config.base_dir, run.evidence_folder)
        validation.evidence.attachments.extend(evidence.attachments)
        validation.evidence.skipped_size.extend(evidence.skipped_size)
        validation.evidence.skipped_type.extend(evidence.skipped_type)
        validation.evidence.scanned_count += evidence.scanned_count
        validation.evidence.directories_skipped_count += evidence.directories_skipped_count

    validation.attachments, validation.evidence_matching = associate_evidence_with_summary(
        validation.evidence.attachments,
        validation.results,
        config.settings.upload_result_evidence_for,
        config.settings.mapping_pattern,
    )
    summary = summarize_mapping(validation.results)
    validation.duplicate_details = duplicate_results_by_test_case_id(validation.results)
    if summary.unmapped and not config.settings.allow_unmapped:
        validation.errors.append(f"{summary.unmapped} test(s) have no test case ID and allowUnmapped=false")
    if validation.duplicate_details and config.settings.duplicate_strategy == DuplicateStrategy.FAIL:
        validation.errors.append(format_duplicate_error(validation.duplicate_details))
    _print_validation_summary(validation, summary.duplicates)

    if validation.errors:
        validation.publish_ready = False
        if enforce:
            raise MappingError("; ".join(validation.errors))
        return validation

    validation.results, duplicates = resolve_duplicate_results(validation.results, config.settings.duplicate_strategy)
    if duplicates and config.settings.duplicate_strategy == DuplicateStrategy.WORST_OUTCOME_WINS:
        logger.warning(
            "Duplicate TC mappings were aggregated using worst_outcome_wins: %s",
            ", ".join(f"TC-{test_case_id} ({len(items)} executions)" for test_case_id, items in duplicates.items()),
        )
    validation.publish_ready = True
    return validation


def _print_validation_summary(validation: ValidationResult, duplicates: dict[str, int]) -> None:
    summary = summarize_mapping(validation.results)
    logger.info("Validation summary")
    logger.info("Result files discovered: %s", len(validation.result_files))
    logger.info("Tests parsed: %s", len(validation.results))
    logger.info("Tests with TC IDs: %s", summary.mapped)
    logger.info("Tests without TC IDs: %s", summary.unmapped)
    if duplicates:
        logger.warning("Duplicate TC mappings: %s", ", ".join(f"{key} ({value})" for key, value in duplicates.items()))
    else:
        logger.info("Duplicate TC mappings: none")
    logger.info("Evidence scan summary")
    logger.info("  Files scanned: %s", validation.evidence.scanned_count)
    logger.info("  Files eligible: %s", validation.evidence.eligible_count)
    logger.info("  Files skipped due to unsupported type: %s", validation.evidence.skipped_type_count)
    logger.info("  Files skipped due to size limit: %s", validation.evidence.skipped_size_count)
    logger.info("  Directories skipped: %s", validation.evidence.directories_skipped_count)
    logger.info("Evidence matching summary")
    logger.info("  Tests requiring result-level evidence: %s", validation.evidence_matching.tests_requiring_result_evidence)
    logger.info("  Tests with matched evidence: %s", validation.evidence_matching.tests_with_matched_evidence)
    logger.info("  Tests without matched evidence: %s", validation.evidence_matching.tests_without_matched_evidence)
    logger.info("  Result-level files matched: %s", validation.evidence_matching.result_level_files_matched)
    logger.info("  Run-level files selected: %s", validation.evidence_matching.run_level_files_selected)
    if validation.errors:
        logger.error("Publish readiness: not ready")
        for error in validation.errors:
            logger.error(error)
    else:
        logger.info("Publish readiness: ready")


def write_validation_report(validation: ValidationResult, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(validation_report(validation), indent=2), encoding="utf-8")
    logger.info("Validation report written: %s", path)


def validation_report(validation: ValidationResult) -> dict:
    summary = summarize_mapping(validation.results)
    return {
        "publishReady": validation.publish_ready,
        "errors": validation.errors,
        "config": {
            "project": validation.config.azdo.project,
            "planId": validation.config.azdo.plan_id,
            "suiteId": validation.config.azdo.suite_id,
            "duplicateStrategy": validation.config.settings.duplicate_strategy.value,
            "allowUnmapped": validation.config.settings.allow_unmapped,
        },
        "results": {
            "filesDiscovered": [str(path) for path in validation.result_files],
            "fileCount": len(validation.result_files),
            "testsParsed": len(validation.results),
            "testsWithTcIds": summary.mapped,
            "testsWithoutTcIds": summary.unmapped,
            "duplicateTcIds": {
                test_case_id: [
                    {
                        "name": result.name,
                        "fullName": result.full_name,
                        "sourceFile": result.source_file,
                        "outcome": result.outcome.value,
                    }
                    for result in results
                ]
                for test_case_id, results in validation.duplicate_details.items()
            },
        },
        "evidence": {
            "filesScanned": validation.evidence.scanned_count,
            "filesEligible": validation.evidence.eligible_count,
            "directoriesSkipped": validation.evidence.directories_skipped_count,
            "skippedDueToSize": [str(path) for path in validation.evidence.skipped_size],
            "skippedDueToType": [str(path) for path in validation.evidence.skipped_type],
            "matching": {
                "testsRequiringResultLevelEvidence": validation.evidence_matching.tests_requiring_result_evidence,
                "testsWithMatchedEvidence": validation.evidence_matching.tests_with_matched_evidence,
                "testsWithoutMatchedEvidence": validation.evidence_matching.tests_without_matched_evidence,
                "resultLevelFilesMatched": validation.evidence_matching.result_level_files_matched,
                "runLevelFilesSelected": validation.evidence_matching.run_level_files_selected,
            },
        },
    }
