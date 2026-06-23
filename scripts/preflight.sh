#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLIQUE_ROOT="$(cd "$PROJECT_ROOT/../CliqueAI" && pwd)"
ERRORS=0

fail() {
    echo "ERROR: $1" >&2
    ERRORS=$((ERRORS + 1))
}

warn() {
    echo "WARN: $1" >&2
}

ok() {
    echo "OK: $1"
}

echo "Subnet 83 miner preflight"
echo "========================="

if [ ! -d "$CLIQUE_ROOT" ]; then
    fail "CliqueAI repo not found at $CLIQUE_ROOT"
else
    ok "CliqueAI repo found"
fi

if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 not found"
else
    PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    PYTHON_MAJOR="$(echo "$PYTHON_VERSION" | cut -d. -f1)"
    PYTHON_MINOR="$(echo "$PYTHON_VERSION" | cut -d. -f2)"
    if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 12 ]; }; then
        fail "Python 3.12+ required (found $PYTHON_VERSION)"
    else
        ok "Python $PYTHON_VERSION"
    fi
fi

if ! command -v pm2 >/dev/null 2>&1; then
    warn "pm2 not found (install with: npm install -g pm2)"
else
    ok "pm2 installed"
fi

if [ -f "$PROJECT_ROOT/miner.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/miner.env"
    set +a
    ok "miner.env loaded"
else
    warn "miner.env not found (copy miner.env.example to miner.env)"
fi

for var in WALLET_NAME WALLET_HOTKEY AXON_IP AXON_PORT; do
    if [ -z "${!var:-}" ]; then
        warn "$var is not set"
    else
        ok "$var is set"
    fi
done

if [ -n "${AXON_PORT:-}" ] && command -v ss >/dev/null 2>&1; then
    if ss -tuln | grep -q ":${AXON_PORT} "; then
        warn "Port ${AXON_PORT} is already in use"
    else
        ok "Port ${AXON_PORT} appears free"
    fi
fi

VENV_PYTHON="$PROJECT_ROOT/venv/bin/python"
if [ -x "$VENV_PYTHON" ]; then
    if "$VENV_PYTHON" -c "import model_upgrade, CliqueAI.miner" 2>/dev/null; then
        ok "model_upgrade and CliqueAI importable in venv"
    else
        warn "venv exists but packages missing; run ./install.sh --skip-benchmark"
    fi
else
    warn "venv not installed yet; run ./install.sh --skip-benchmark"
fi

if [ "$ERRORS" -gt 0 ]; then
    echo
    echo "Preflight failed with $ERRORS error(s)."
    exit 1
fi

echo
echo "Preflight passed."
