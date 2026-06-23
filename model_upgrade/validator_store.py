"""Persist live validator synapses for offline benchmarking."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from CliqueAI.protocol import MaximumCliqueOfLambdaGraph

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALIDATOR_DATA_DIR = PROJECT_ROOT / "validator_data"

_TRUTHY = frozenset({"1", "true", "yes", "on", "enabled"})
_FALSY = frozenset({"0", "false", "no", "off", "disabled"})


def is_validator_data_enabled() -> bool:
    """Return False when SAVE_VALIDATOR_DATA is set to a falsy value."""
    raw = os.environ.get("SAVE_VALIDATOR_DATA", "true").strip().lower()
    if raw in _FALSY:
        return False
    if raw in _TRUTHY:
        return True
    logger.warning(
        "Unrecognized SAVE_VALIDATOR_DATA=%r; defaulting to enabled",
        os.environ.get("SAVE_VALIDATOR_DATA"),
    )
    return True


def validator_data_dir() -> Path:
    override = os.environ.get("VALIDATOR_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_VALIDATOR_DATA_DIR


def build_validator_record(
    synapse: MaximumCliqueOfLambdaGraph,
    *,
    elapsed_seconds: float,
    validator_hotkey: str | None,
) -> dict[str, Any]:
    maximum_clique = list(synapse.maximum_clique or [])
    timeout = float(synapse.timeout) if getattr(synapse, "timeout", None) else 30.0
    return {
        "name": synapse.__class__.__name__,
        "timeout": timeout,
        "uuid": synapse.uuid,
        "label": synapse.label,
        "number_of_nodes": synapse.number_of_nodes,
        "encoded_matrix": synapse.encoded_matrix,
        "maximum_clique": maximum_clique,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "validator_hotkey": validator_hotkey,
        "elapsed_seconds": round(elapsed_seconds, 6),
        "clique_size": len(maximum_clique),
    }


def save_validator_record(
    record: dict[str, Any],
    data_dir: Path | None = None,
) -> Path | None:
    """Write one validator query/response JSON under validator_data/."""
    if not is_validator_data_enabled():
        return None

    uuid = (record.get("uuid") or "").strip()
    if not uuid:
        logger.warning("Skipping validator_data save: record has no uuid")
        return None

    target_dir = data_dir or validator_data_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / f"{uuid}.json"

    tmp_path = output_path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")
    tmp_path.replace(output_path)

    logger.info("Saved validator data -> %s", output_path)
    return output_path


def save_validator_request(
    synapse: MaximumCliqueOfLambdaGraph,
    *,
    elapsed_seconds: float,
    validator_hotkey: str | None = None,
    data_dir: Path | None = None,
) -> Path | None:
    record = build_validator_record(
        synapse,
        elapsed_seconds=elapsed_seconds,
        validator_hotkey=validator_hotkey,
    )
    return save_validator_record(record, data_dir=data_dir)
