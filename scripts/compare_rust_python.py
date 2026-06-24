"""Benchmark Python vs Rust solvers on the same validator graphs."""

import argparse
import json
import sys
import time
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
CLIQUE_ROOT = ROOT.parent / "CliqueAI"
sys.path.insert(0, str(CLIQUE_ROOT))

from CliqueAI.graph.codec import GraphCodec  # noqa: E402

from model_upgrade import (  # noqa: E402
    is_valid_maximum_clique as py_is_valid,
    solve_maximum_clique as py_solve,
)

try:
    from model_upgrade_rs import (  # noqa: E402
        is_valid_maximum_clique_py as rs_is_valid,
        solve_maximum_clique as rs_solve,
    )
except ImportError as exc:
    raise SystemExit(
        "Rust extension not installed. From the project root run:\n"
        "  .\\install.ps1 -SkipBenchmark -WithRust\n"
        "  # or: cd crates/model_upgrade_py && maturin develop --release\n"
        f"Original error: {exc}"
    ) from exc


class TestSynapse(BaseModel):
    uuid: str = ""
    number_of_nodes: int = 0
    encoded_matrix: str = ""
    timeout: float = 30.0
    maximum_clique: list[int] = Field(default_factory=list)


def run_solver(label, solve_fn, valid_fn, nodes, adj, timeout, uuid):
    start = time.perf_counter()
    clique = solve_fn(nodes, adj, time_limit=timeout, problem_id=uuid or None)
    elapsed = time.perf_counter() - start
    valid = valid_fn(adj, clique)
    return clique, elapsed, valid


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Python and Rust clique solvers")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=ROOT / "validator_data",
        help="Directory with validator JSON files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "compare_output" / "summary.json",
        help="Path for comparison summary JSON",
    )
    args = parser.parse_args()

    codec = GraphCodec()
    files = sorted(args.data_dir.glob("*.json"))
    if not files:
        raise SystemExit(f"No JSON files in {args.data_dir}")

    rows = []
    print(f"Comparing Python vs Rust on {len(files)} graphs")
    print("-" * 100)
    print(
        f"{'ID':8} {'N':>4} {'T':>5} | "
        f"{'Py':>4} {'PyT':>5} {'PyD':>5} | "
        f"{'Rs':>4} {'RsT':>5} {'RsD':>5} | "
        f"{'Ref':>4} {'Py-Rs':>5} {'Win':>4}"
    )
    print("-" * 100)

    py_net = rs_net = ref_net_py = ref_net_rs = 0
    py_valid = rs_valid = 0

    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        syn = TestSynapse.model_validate(data)
        timeout = float(syn.timeout)
        adj = codec.matrix_to_list(codec.decode_matrix(syn.encoded_matrix))
        ref = len(syn.maximum_clique) if syn.maximum_clique else None

        py_clique, py_t, py_ok = run_solver(
            "py", py_solve, py_is_valid, syn.number_of_nodes, adj, timeout, syn.uuid
        )
        rs_clique, rs_t, rs_ok = run_solver(
            "rs", rs_solve, rs_is_valid, syn.number_of_nodes, adj, timeout, syn.uuid
        )

        py_valid += int(py_ok)
        rs_valid += int(rs_ok)
        diff = len(py_clique) - len(rs_clique)
        if diff > 0:
            winner = "Py"
        elif diff < 0:
            winner = "Rs"
        else:
            winner = "="

        py_delay = timeout - py_t
        rs_delay = timeout - rs_t
        py_ref_d = len(py_clique) - ref if ref is not None else None
        rs_ref_d = len(rs_clique) - ref if ref is not None else None
        if ref is not None:
            ref_net_py += py_ref_d
            ref_net_rs += rs_ref_d
        py_net += len(py_clique)
        rs_net += len(rs_clique)

        row = {
            "file": path.name,
            "uuid": syn.uuid,
            "nodes": syn.number_of_nodes,
            "timeout": timeout,
            "reference_size": ref,
            "python": {
                "clique_size": len(py_clique),
                "elapsed": round(py_t, 4),
                "delay": round(py_delay, 4),
                "valid": py_ok,
                "delta_vs_reference": py_ref_d,
            },
            "rust": {
                "clique_size": len(rs_clique),
                "elapsed": round(rs_t, 4),
                "delay": round(rs_delay, 4),
                "valid": rs_ok,
                "delta_vs_reference": rs_ref_d,
            },
            "py_minus_rs": diff,
            "winner": winner,
        }
        rows.append(row)

        ref_s = str(ref) if ref is not None else "-"
        print(
            f"{syn.uuid[:8]:8} {syn.number_of_nodes:4d} {timeout:5.1f} | "
            f"{len(py_clique):4d} {py_t:5.2f} {py_delay:+5.2f} | "
            f"{len(rs_clique):4d} {rs_t:5.2f} {rs_delay:+5.2f} | "
            f"{ref_s:>4} {diff:+5d} {winner:>4}"
        )

    py_wins = sum(1 for r in rows if r["winner"] == "Py")
    rs_wins = sum(1 for r in rows if r["winner"] == "Rs")
    ties = sum(1 for r in rows if r["winner"] == "=")
    py_time = sum(r["python"]["elapsed"] for r in rows)
    rs_time = sum(r["rust"]["elapsed"] for r in rows)

    summary = {
        "graphs": len(rows),
        "python": {
            "valid": py_valid,
            "total_clique": py_net,
            "net_vs_reference": ref_net_py,
            "total_seconds": round(py_time, 2),
        },
        "rust": {
            "valid": rs_valid,
            "total_clique": rs_net,
            "net_vs_reference": ref_net_rs,
            "total_seconds": round(rs_time, 2),
        },
        "head_to_head": {"python_wins": py_wins, "rust_wins": rs_wins, "ties": ties},
        "speedup_total_wall": round(py_time / rs_time, 3) if rs_time > 0 else None,
        "rows": rows,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print("-" * 100)
    print(f"Python: valid {py_valid}/{len(rows)} | net vs ref {ref_net_py:+d} | total time {py_time:.1f}s")
    print(f"Rust:   valid {rs_valid}/{len(rows)} | net vs ref {ref_net_rs:+d} | total time {rs_time:.1f}s")
    print(f"Head-to-head: Py {py_wins} | Rs {rs_wins} | tie {ties} | speedup {summary['speedup_total_wall']}x")
    print(f"Saved -> {args.output}")


if __name__ == "__main__":
    main()
