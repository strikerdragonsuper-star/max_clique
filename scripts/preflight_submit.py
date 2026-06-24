#!/usr/bin/env python3
"""Pre-submit checks: Rust solver enabled, extension installed, validator benchmark."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIQUE_ROOT = ROOT.parent / "CliqueAI"
sys.path.insert(0, str(CLIQUE_ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from model_upgrade.validator_store import load_miner_env_file  # noqa: E402

load_miner_env_file()

from CliqueAI.graph.codec import GraphCodec  # noqa: E402

from model_upgrade import (  # noqa: E402
    is_valid_maximum_clique,
    solve_maximum_clique,
    solver_backend,
)

from benchmark import TestSynapse, load_reference_clique  # noqa: E402


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def check_backend(require_rust: bool) -> None:
    backend = solver_backend()
    print(f"MODEL_UPGRADE_USE_RUST={os.environ.get('MODEL_UPGRADE_USE_RUST', '(unset)')}")
    print(f"Active solver backend: {backend}")

    if require_rust and not env_flag("MODEL_UPGRADE_USE_RUST"):
        raise SystemExit("MODEL_UPGRADE_USE_RUST is not enabled (set in miner.env)")

    if require_rust and backend != "rust":
        raise SystemExit(
            "Rust backend not active. Build the extension:\n"
            "  cd crates/model_upgrade_py && maturin develop --release"
        )


def smoke_test() -> None:
    sample = ROOT / "test_data" / "sample.json"
    if not sample.exists():
        print("Skipping smoke test (test_data/sample.json missing)")
        return

    syn = TestSynapse.model_validate(json.loads(sample.read_text(encoding="utf-8")))
    codec = GraphCodec()
    adj = codec.matrix_to_list(codec.decode_matrix(syn.encoded_matrix))
    timeout = float(syn.timeout or 30.0)

    start = time.perf_counter()
    clique = solve_maximum_clique(
        syn.number_of_nodes,
        adj,
        time_limit=timeout,
        problem_id=syn.uuid or None,
    )
    elapsed = time.perf_counter() - start
    valid = is_valid_maximum_clique(adj, clique)
    print(
        f"Smoke test: clique={len(clique)} valid={valid} "
        f"elapsed={elapsed:.2f}s timeout={timeout:.1f}s"
    )
    if not valid:
        raise SystemExit("Smoke test failed: invalid clique")


def run_validator_benchmark(data_dir: Path) -> dict:
    files = sorted(data_dir.glob("*.json"))
    if not files:
        raise SystemExit(f"No validator JSON files in {data_dir}")

    codec = GraphCodec()
    valid_count = 0
    ref_net = 0
    over_timeout = 0
    total_elapsed = 0.0

    print(f"\nValidator benchmark ({len(files)} graphs)")
    print("-" * 88)
    print(f"{'ID':8} {'N':>4} {'T':>5} {'Size':>4} {'Delay':>6} {'Ref':>4} {'dRef':>5} {'OK':>3}")
    print("-" * 88)

    for path in files:
        syn = TestSynapse.model_validate(json.loads(path.read_text(encoding="utf-8")))
        timeout = float(syn.timeout or 30.0)
        adj = codec.matrix_to_list(codec.decode_matrix(syn.encoded_matrix))
        ref = load_reference_clique(path)
        ref_size = len(ref) if ref else None

        start = time.perf_counter()
        clique = solve_maximum_clique(
            syn.number_of_nodes,
            adj,
            time_limit=timeout,
            problem_id=syn.uuid or None,
        )
        elapsed = time.perf_counter() - start
        delay = timeout - elapsed
        ok = is_valid_maximum_clique(adj, clique)
        valid_count += int(ok)
        total_elapsed += elapsed
        if elapsed > timeout:
            over_timeout += 1
        delta = len(clique) - ref_size if ref_size is not None else None
        if delta is not None:
            ref_net += delta

        ref_s = str(ref_size) if ref_size is not None else "-"
        delta_s = f"{delta:+d}" if delta is not None else "-"
        print(
            f"{syn.uuid[:8]:8} {syn.number_of_nodes:4d} {timeout:5.1f} "
            f"{len(clique):4d} {delay:+5.2f} {ref_s:>4} {delta_s:>5} {'Y' if ok else 'N':>3}"
        )

    summary = {
        "graphs": len(files),
        "backend": solver_backend(),
        "valid": valid_count,
        "net_vs_reference": ref_net,
        "over_timeout": over_timeout,
        "total_elapsed_seconds": round(total_elapsed, 2),
    }
    print("-" * 88)
    print(
        f"Summary: valid {valid_count}/{len(files)} | net vs ref {ref_net:+d} | "
        f"over-timeout {over_timeout} | total time {total_elapsed:.1f}s"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-submit Rust solver checks")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=ROOT / "validator_data",
        help="Validator JSON directory for benchmark",
    )
    parser.add_argument(
        "--skip-benchmark",
        action="store_true",
        help="Only check backend + smoke test",
    )
    parser.add_argument(
        "--allow-python",
        action="store_true",
        help="Do not require MODEL_UPGRADE_USE_RUST=1",
    )
    args = parser.parse_args()

    print("Pre-submit solver check")
    print("=" * 88)
    check_backend(require_rust=not args.allow_python)
    smoke_test()

    if args.skip_benchmark:
        print("\nPreflight passed (benchmark skipped).")
        return

    summary = run_validator_benchmark(args.data_dir)
    if summary["valid"] != summary["graphs"]:
        raise SystemExit(f"Benchmark failed: {summary['valid']}/{summary['graphs']} valid")
    if summary["over_timeout"] > 0:
        raise SystemExit(f"Benchmark failed: {summary['over_timeout']} graphs over timeout")

    print("\nPreflight passed — ready to submit/deploy.")


if __name__ == "__main__":
    main()
