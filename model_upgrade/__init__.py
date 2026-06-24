import os

from model_upgrade.validation import extend_to_maximal_clique, is_valid_maximum_clique
from model_upgrade.validator_store import load_miner_env_file

load_miner_env_file()

_USE_RUST = os.environ.get("MODEL_UPGRADE_USE_RUST", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
    "enabled",
}


def _load_solver():
    if _USE_RUST:
        try:
            from model_upgrade_rs import solve_maximum_clique as rs_solve

            return rs_solve, "rust"
        except ImportError as exc:
            raise ImportError(
                "MODEL_UPGRADE_USE_RUST is set but model_upgrade_rs is not installed. "
                "Run: maturin develop --release"
            ) from exc
    from model_upgrade.solver import (
        fallback_maximum_clique,
        solve_maximum_clique as py_solve,
    )

    return py_solve, "python"


_solve_fn, _backend = _load_solver()

if _USE_RUST:
    from model_upgrade_rs import fallback_maximum_clique_py as fallback_maximum_clique
else:
    from model_upgrade.solver import fallback_maximum_clique

solve_maximum_clique = _solve_fn


def solver_backend() -> str:
    """Return the active solver backend: ``python`` or ``rust``."""
    return _backend


__all__ = [
    "solve_maximum_clique",
    "fallback_maximum_clique",
    "extend_to_maximal_clique",
    "is_valid_maximum_clique",
    "solver_backend",
]
