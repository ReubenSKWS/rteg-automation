"""Configuration for the series MTE width experiment."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_ENV_LOADED = False


def python_code_root() -> Path:
    """Directory containing ``input_files/`` and ``src/``."""
    return Path(__file__).resolve().parents[3]


def default_env_file() -> Path:
    """Canonical agent env file: ``python_code/.env``."""
    return python_code_root() / ".env"


def env_file_candidates() -> tuple[Path, ...]:
    """`.env` search order: explicit default, repo root, process cwd."""
    cwd = Path.cwd()
    seen: set[Path] = set()
    out: list[Path] = []

    def add(base: Path) -> None:
        path = (base / ".env").resolve()
        if path not in seen:
            seen.add(path)
            out.append(path)

    add(default_env_file().parent)
    add(python_code_root().parent)
    add(cwd)
    return tuple(out)


def load_agent_env(
    *,
    env_file: Path | str | None = None,
    force: bool = False,
) -> Path | None:
    """
    Load agent env vars from ``python_code/.env`` (or ``env_file`` if given).

    Does not override variables already set in the process environment.
    Retries when ``ANTHROPIC_API_KEY`` is still missing after a prior attempt.
    """
    global _ENV_LOADED
    if _ENV_LOADED and not force and os.environ.get("ANTHROPIC_API_KEY"):
        return None

    loaded_from: Path | None = None
    try:
        from dotenv import load_dotenv
    except ImportError:
        import warnings

        warnings.warn(
            "python-dotenv not installed — cannot load .env; "
            "pip install -r requirements-agentic.txt",
            stacklevel=2,
        )
        _ENV_LOADED = True
        return None

    candidates: list[Path] = []
    if env_file is not None:
        candidates.append(Path(env_file).resolve())
    for path in env_file_candidates():
        if path not in candidates:
            candidates.append(path)

    for path in candidates:
        if path.is_file():
            load_dotenv(path, override=False)
            loaded_from = path
            break

    _ENV_LOADED = True
    return loaded_from


DEFAULT_MARGINS = (1.0, 1.5, 2.0, 3.0, 4.0, 5.0)
DEFAULT_BANDS = (1.0, 1.5, 2.0, 3.0, 4.0)
SERIES_INDICES = (2, 3, 6, 7)
SHUNT_INDICES = (0, 1, 4, 5)


@dataclass(frozen=True)
class SeriesMteExperimentConfig:
    """Tunables for margin/band sweep + agent."""

    model: str = field(
        default_factory=lambda: os.environ.get(
            "SERIES_MTE_AGENT_MODEL", "claude-opus-4-6"
        )
    )
    max_turns: int = 10
    margin_candidates: tuple[float, ...] = DEFAULT_MARGINS
    band_candidates: tuple[float, ...] = DEFAULT_BANDS
    series_indices: tuple[int, ...] = SERIES_INDICES
    shunt_indices: tuple[int, ...] = SHUNT_INDICES
    artifacts_dir: Path = Path("artifacts/mte_experiment")
    output_gds_dir: Path = Path("draft_output/MTE_experiment")
    parent_name: str = "KB331_N_01"
