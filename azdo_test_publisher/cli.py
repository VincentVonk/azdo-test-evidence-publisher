from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .azdo.publisher import AzureDevOpsPublisher
from .config import ConfigError, load_config, resolve_token
from .evidence.collector import EvidenceCollector, EvidenceSummary, associate_evidence
from .mapping import MappingError, apply_mapping, resolve_duplicate_results, summarize_mapping
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="azdo-test-evidence-publisher")
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "publish"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--config", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    try:
        validation = validate_config(args.config)
        if args.command == "publish":
            token = resolve_token(validation.config)
            if not token:
                raise ConfigError("No Azure DevOps token found in tokenEnvVar, AZDO_TOKEN, or AZDO_PAT")
            AzureDevOpsPublisher(validation.config, token).publish(validation.results, validation.attachments)
        return 0
    except (ConfigError, MappingError, ValueError) as exc:
        logger.error(str(exc))
        return 2


def validate_config(config_path: str | Path) -> ValidationResult:
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

    validation.attachments = associate_evidence(
        validation.evidence.attachments,
        validation.results,
        config.settings.upload_result_evidence_for,
    )
    summary = summarize_mapping(validation.results)
    _print_validation_summary(validation, summary.duplicates)
    if summary.unmapped and not config.settings.allow_unmapped:
        raise MappingError(f"{summary.unmapped} test(s) have no test case ID and allowUnmapped=false")
    validation.results, duplicates = resolve_duplicate_results(validation.results, config.settings.duplicate_strategy)
    if duplicates and config.settings.duplicate_strategy == DuplicateStrategy.WORST_OUTCOME_WINS:
        logger.warning(
            "Duplicate TC mappings were aggregated using worst_outcome_wins: %s",
            ", ".join(f"TC-{test_case_id} ({len(items)} executions)" for test_case_id, items in duplicates.items()),
        )
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
    logger.info("Evidence files discovered: %s", len(validation.evidence.attachments))
    logger.info("Evidence files skipped due to size: %s", len(validation.evidence.skipped_size))
    logger.info("Evidence files skipped due to type: %s", len(validation.evidence.skipped_type))
