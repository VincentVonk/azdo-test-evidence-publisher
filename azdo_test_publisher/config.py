from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .models import AzdoConfig, DuplicateStrategy, PublisherConfig, RunConfig, Settings


class ConfigError(ValueError):
    pass


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _int_value(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Missing or invalid integer value for {field_name}") from exc


def load_config(path: str | Path) -> PublisherConfig:
    load_dotenv()
    config_path = Path(path).resolve()
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    raw = _load_raw_config(config_path)

    azdo_raw = raw.get("azdo") or {}
    settings_raw = raw.get("settings") or {}
    runs_raw = raw.get("runs") or []

    organization = _first_present(azdo_raw.get("organization"), os.getenv("AZDO_ORG"))
    project = _first_present(azdo_raw.get("project"), os.getenv("AZDO_PROJECT"))
    plan_id = _first_present(azdo_raw.get("planId"), os.getenv("AZDO_PLAN_ID"))
    suite_id = _first_present(azdo_raw.get("suiteId"), os.getenv("AZDO_SUITE_ID"))

    missing = [
        name
        for name, value in {
            "azdo.organization/AZDO_ORG": organization,
            "azdo.project/AZDO_PROJECT": project,
            "azdo.planId/AZDO_PLAN_ID": plan_id,
            "azdo.suiteId/AZDO_SUITE_ID": suite_id,
        }.items()
        if value in (None, "")
    ]
    if missing:
        raise ConfigError(f"Missing required config values: {', '.join(missing)}")
    if not runs_raw:
        raise ConfigError("At least one run must be configured")

    runs: list[RunConfig] = []
    for index, item in enumerate(runs_raw):
        try:
            runs.append(
                RunConfig(
                    name=str(item["name"]),
                    result_format=str(item["resultFormat"]).lower(),
                    result_files=list(item["resultFiles"]),
                    evidence_folder=item.get("evidenceFolder"),
                )
            )
        except KeyError as exc:
            raise ConfigError(f"Run at index {index} is missing required field {exc.args[0]}") from exc

    duplicate_strategy = str(settings_raw.get("duplicateStrategy", DuplicateStrategy.FAIL.value)).lower()
    try:
        duplicate_strategy_value = DuplicateStrategy(duplicate_strategy)
    except ValueError as exc:
        raise ConfigError(
            "settings.duplicateStrategy must be one of: fail, worst_outcome_wins"
        ) from exc

    return PublisherConfig(
        azdo=AzdoConfig(
            organization=str(organization).rstrip("/"),
            project=str(project),
            plan_id=_int_value(plan_id, "azdo.planId"),
            suite_id=_int_value(suite_id, "azdo.suiteId"),
            token_env_var=azdo_raw.get("tokenEnvVar"),
        ),
        settings=Settings(
            mapping_pattern=settings_raw.get("mappingPattern", r"TC-(\d+)"),
            allow_unmapped=bool(settings_raw.get("allowUnmapped", False)),
            allow_multiple_test_case_ids=bool(settings_raw.get("allowMultipleTestCaseIds", False)),
            duplicate_strategy=duplicate_strategy_value,
            upload_run_evidence=bool(settings_raw.get("uploadRunEvidence", True)),
            upload_result_evidence=bool(settings_raw.get("uploadResultEvidence", True)),
            upload_result_evidence_for=str(settings_raw.get("uploadResultEvidenceFor", "failed")).lower(),
            max_attachment_size_mb=int(settings_raw.get("maxAttachmentSizeMb", 25)),
            evidence_include_patterns=list(settings_raw.get("evidenceIncludePatterns", ["**/*"])),
            evidence_exclude_patterns=list(
                settings_raw.get(
                    "evidenceExcludePatterns",
                    [
                        "**/index.html",
                        "**/snapshot.html",
                        "**/uiMode.html",
                        "**/.last-run.json",
                        "**/*.css",
                        "**/*.js",
                        "**/*.mjs",
                        "**/*.map",
                        "**/*.woff",
                        "**/*.woff2",
                        "**/*.ttf",
                        "**/*.otf",
                        "**/playwright-report/**",
                    ],
                )
            ),
        ),
        runs=runs,
        base_dir=config_path.parent,
    )


def resolve_token(config: PublisherConfig) -> str | None:
    env_names = []
    if config.azdo.token_env_var:
        env_names.append(config.azdo.token_env_var)
    env_names.extend(["AZDO_TOKEN", "AZDO_PAT"])
    for name in env_names:
        token = os.getenv(name)
        if token:
            return token
    return None


def _load_raw_config(config_path: Path) -> dict[str, Any]:
    suffix = config_path.suffix.lower()
    if suffix == ".json":
        with config_path.open("r", encoding="utf-8") as handle:
            try:
                return json.load(handle) or {}
            except json.JSONDecodeError as exc:
                raise ConfigError(f"Invalid JSON config: {exc}") from exc
    if suffix in {".yml", ".yaml"}:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ConfigError("YAML config requires PyYAML. Use JSON config or install PyYAML.") from exc
        with config_path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    raise ConfigError("Unsupported config format. Use .json, .yml, or .yaml.")
