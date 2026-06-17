from __future__ import annotations

import glob
from pathlib import Path


def resolve_globs(base_dir: Path, patterns: list[str]) -> list[Path]:
    found: list[Path] = []
    for pattern in patterns:
        matches = (Path(item) for item in glob.glob(pattern, recursive=True)) if Path(pattern).is_absolute() else base_dir.glob(pattern)
        found.extend(path for path in matches if path.is_file())
    return sorted(set(path.resolve() for path in found))


def relative_or_name(path: Path, base_dir: Path) -> str:
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return path.name
