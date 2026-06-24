from model_upgrade.validator_store import load_miner_env_file

load_miner_env_file()

try:
    from model_upgrade_rs import (
        extend_to_maximal_clique_py as extend_to_maximal_clique,
        fallback_maximum_clique_py as fallback_maximum_clique,
        is_valid_maximum_clique_py as is_valid_maximum_clique,
        solve_maximum_clique,
    )
except ImportError as exc:
    raise ImportError(
        "Rust solver not installed. From the project root run:\n"
        "  ./install.sh --skip-benchmark\n"
        "  # or: cd crates/model_upgrade_py && maturin develop --release"
    ) from exc


def solver_backend() -> str:
    """Return the active solver backend (always ``rust``)."""
    return "rust"


__all__ = [
    "solve_maximum_clique",
    "fallback_maximum_clique",
    "extend_to_maximal_clique",
    "is_valid_maximum_clique",
    "solver_backend",
]
