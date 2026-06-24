#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIQUE_ROOT="$(cd "$PROJECT_ROOT/../CliqueAI" && pwd)"
VENV_DIR="$PROJECT_ROOT/venv"
RUN_BENCHMARK=0
WITH_RUST=0

for arg in "$@"; do
    case "$arg" in
        --skip-benchmark) RUN_BENCHMARK=0 ;;
        --with-benchmark) RUN_BENCHMARK=1 ;;
        --with-rust) WITH_RUST=1 ;;
    esac
done

echo "Installing model-upgrade miner stack for subnet 83..."
echo "Project root: $PROJECT_ROOT"
echo "CliqueAI root: $CLIQUE_ROOT"

if [ ! -d "$CLIQUE_ROOT" ]; then
    echo "CliqueAI repo not found at $CLIQUE_ROOT" >&2
    echo "Clone it beside model-upgrade:" >&2
    echo "  git clone https://github.com/toptensor/CliqueAI.git ../CliqueAI" >&2
    exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
pip install -e "$CLIQUE_ROOT"
pip install -e "$PROJECT_ROOT"

if [ "$WITH_RUST" -eq 1 ]; then
    if ! command -v cargo >/dev/null 2>&1; then
        echo "Rust toolchain not found. Install from https://rustup.rs/" >&2
        exit 1
    fi
    echo "Building Rust solver extension (maturin)..."
    pip install maturin
    (cd "$PROJECT_ROOT/crates/model_upgrade_py" && maturin develop --release)
    echo "Rust extension installed as model_upgrade_rs"
    echo "Enable with: export MODEL_UPGRADE_USE_RUST=1"
fi

echo
echo "Install complete."
echo "  venv: $VENV_DIR"
echo "  activate: source venv/bin/activate"

if [ "$RUN_BENCHMARK" -eq 1 ]; then
    echo
    echo "Running benchmark..."
    python "$PROJECT_ROOT/scripts/benchmark.py"
fi
