from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from azdo_test_publisher.config import ConfigError, load_config, resolve_token


def test_load_config_and_env_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AZDO_ORG", "https://dev.azure.com/env-org")
    monkeypatch.setenv("AZDO_PROJECT", "EnvProject")
    monkeypatch.setenv("AZDO_PLAN_ID", "12")
    monkeypatch.setenv("AZDO_SUITE_ID", "34")
    config_file = tmp_path / "publisher.json"
    config_file.write_text(json.dumps({"runs": [{"name": "junit", "resultFormat": "junit", "resultFiles": ["*.xml"]}]}), encoding="utf-8")

    config = load_config(config_file)

    assert config.azdo.organization == "https://dev.azure.com/env-org"
    assert config.azdo.project == "EnvProject"
    assert config.azdo.plan_id == 12
    assert config.azdo.suite_id == 34
    assert config.runs[0].result_format == "junit"


def test_token_priority(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPECIAL_TOKEN", "special")
    monkeypatch.setenv("AZDO_TOKEN", "token")
    monkeypatch.setenv("AZDO_PAT", "pat")
    config_file = tmp_path / "publisher.json"
    config_file.write_text(
        json.dumps(
            {
                "azdo": {
                    "organization": "https://dev.azure.com/org",
                    "project": "Project",
                    "planId": 1,
                    "suiteId": 2,
                    "tokenEnvVar": "SPECIAL_TOKEN",
                },
                "runs": [{"name": "junit", "resultFormat": "junit", "resultFiles": ["*.xml"]}],
            }
        ),
        encoding="utf-8",
    )

    assert resolve_token(load_config(config_file)) == "special"


def test_yaml_without_pyyaml_has_clear_error(tmp_path: Path, monkeypatch) -> None:
    config_file = tmp_path / "publisher.yml"
    config_file.write_text("runs: []", encoding="utf-8")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ConfigError, match="YAML config requires PyYAML. Use JSON config or install PyYAML."):
        load_config(config_file)


def test_json_config_loads_when_yaml_import_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    config_file = tmp_path / "publisher.json"
    config_file.write_text(
        json.dumps(
            {
                "azdo": {
                    "organization": "https://dev.azure.com/org",
                    "project": "Project",
                    "planId": 1,
                    "suiteId": 2,
                },
                "runs": [{"name": "junit", "resultFormat": "junit", "resultFiles": ["*.xml"]}],
            }
        ),
        encoding="utf-8",
    )
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    config = load_config(config_file)
    assert config.azdo.project == "Project"
