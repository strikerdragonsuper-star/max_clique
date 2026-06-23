import argparse
import json
import re
import sys
import time
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
CLIQUE_ROOT = ROOT.parent / "CliqueAI"
LOCAL_TEST_DATA = ROOT / "test_data"
sys.path.insert(0, str(CLIQUE_ROOT))

from CliqueAI.graph.codec import GraphCodec  # noqa: E402
from model_upgrade import is_valid_maximum_clique, solve_maximum_clique  # noqa: E402

# Subnet 83 problem tiers (matches CliqueAI.selection.problem_selector.PROBLEMS).
SUBNET_DIFFICULTY_TIERS: list[tuple[int, int, float]] = [
    (890, 900, 1.0),
    (690, 700, 0.9),
    (490, 500, 0.8),
    (290, 300, 0.7),
]
class TestSynapse(BaseModel):
    uuid: str = ""
    label: str = ""
    number_of_nodes: int = 0
    encoded_matrix: str = ""
    timeout: float = 30.0
    difficulty: float | None = None
    maximum_clique: list[int] = Field(default_factory=list)


DEFAULT_TEST_FILES = [
    "sample.json",
    "general_0.1.json",
    "general_0.2.json",
    "general_0.4.json",
]


def default_data_paths() -> list[Path]:
    search_roots = [LOCAL_TEST_DATA, CLIQUE_ROOT / "test_data"]
    paths: list[Path] = []

    for root in search_roots:
        if not root.exists():
            continue
        discovered = sorted(root.glob("*.json"))
        if discovered:
            return discovered

    for filename in DEFAULT_TEST_FILES:
        for root in search_roots:
            candidate = root / filename
            if candidate.exists():
                paths.append(candidate)
                break
    return paths


def difficulty_for(data_path: Path, number_of_nodes: int) -> float:
    """Resolve subnet difficulty from graph size, with filename fallback for small tests."""
    for min_nodes, max_nodes, difficulty in SUBNET_DIFFICULTY_TIERS:
        if min_nodes <= number_of_nodes <= max_nodes:
            return difficulty
    match = re.fullmatch(r"general_([\d.]+)\.json", data_path.name)
    if match:
        return float(match.group(1))

    match = re.fullmatch(r"shuffled_.+_d([\d_]+)_\d+\.json", data_path.name)
    if match:
        return float(match.group(1).replace("_", "."))

    match = re.fullmatch(r"large_clique_n\d+_d([\d_]+)_c\d+_\d+\.json", data_path.name)
    if match:
        return float(match.group(1).replace("_", "."))

    if number_of_nodes < 290:
        return 0.1

    return 0.7


def timeout_for_difficulty(difficulty: float) -> float:
    return min(30.0, 6.0 + difficulty * 30.0)

def resolve_timeout(
    data_path: Path,
    number_of_nodes: int,
    synapse: TestSynapse,
    timeout_override: float | None,
) -> tuple[float, float]:
    difficulty = (
        synapse.difficulty
        if synapse.difficulty is not None
        else difficulty_for(data_path, number_of_nodes)
    )
    if timeout_override is not None:
        timeout = timeout_override
    elif synapse.timeout:
        timeout = float(synapse.timeout)
    else:
        timeout = timeout_for_difficulty(difficulty)
    return difficulty, timeout


def load_synapse(data_path: Path) -> TestSynapse:
    with data_path.open("r", encoding="utf-8") as handle:
        return TestSynapse.model_validate(json.load(handle))


def load_reference_clique(data_path: Path) -> list[int] | None:
    with data_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    reference = data.get("maximum_clique") or []
    return reference if reference else None


def benchmark_file(
    data_path: Path,
    output_dir: Path,
    timeout_override: float | None = None,
) -> Path | None:
    synapse = load_synapse(data_path)
    difficulty, timeout = resolve_timeout(
        data_path,
        synapse.number_of_nodes,
        synapse,
        timeout_override,
    )

    codec = GraphCodec()
    adjacency_matrix = codec.decode_matrix(synapse.encoded_matrix)
    adjacency_list = codec.matrix_to_list(adjacency_matrix)

    start = time.perf_counter()
    clique = solve_maximum_clique(
        synapse.number_of_nodes,
        adjacency_list,
        time_limit=timeout,
    )
    elapsed = time.perf_counter() - start
    valid = is_valid_maximum_clique(adjacency_list, clique)

    reference_clique = load_reference_clique(data_path)
    reference_size = len(reference_clique) if reference_clique else None

    status = "valid" if valid else "INVALID"
    ref_note = ""
    if reference_size is not None:
        delta = len(clique) - reference_size
        sign = "+" if delta > 0 else ""
        ref_note = f" | ref={reference_size} ({sign}{delta})"
    delay = timeout - elapsed
    delay_note = f"delay={delay:+5.2f}s ({elapsed / timeout * 100:4.0f}%)" if timeout > 0 else ""
    print(
        f"{data_path.name:36} | nodes={synapse.number_of_nodes:4} | "
        f"timeout={timeout:4.1f}s | elapsed={elapsed:5.2f}s | {delay_note} | "
        f"clique={len(clique):4} | {status}{ref_note}"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{data_path.stem}.json"
    result = {
        "input_file": str(data_path.resolve()),
        "uuid": synapse.uuid,
        "label": synapse.label,
        "number_of_nodes": synapse.number_of_nodes,
        "difficulty": difficulty,
        "timeout": timeout,
        "elapsed_seconds": round(elapsed, 6),
        "delay_seconds": round(delay, 6),
        "elapsed_pct_of_timeout": round(elapsed / timeout * 100, 2) if timeout > 0 else None,
        "valid": valid,
        "clique_size": len(clique),
        "maximum_clique": clique,
    }
    if reference_size is not None:
        result["reference_clique_size"] = reference_size
        result["reference_maximum_clique"] = reference_clique
        result["delta_vs_reference"] = len(clique) - reference_size
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(f"{'':18}   saved -> {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the model-upgrade clique solver")
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Override timeout for all test graphs (seconds)",
    )
    parser.add_argument(
        "--validator-data",
        action="store_true",
        help="Benchmark all JSON files in validator_data/",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "test_output",
        help="Directory for per-input result JSON files (default: test_output/)",
    )
    parser.add_argument(
        "data_paths",
        nargs="*",
        type=Path,
        help="Optional test JSON paths (defaults to model-upgrade/test_data)",
    )
    args = parser.parse_args()

    data_paths = args.data_paths
    if not data_paths and args.validator_data:
        data_paths = sorted((ROOT / "validator_data").glob("*.json"))
    if not data_paths:
        data_paths = default_data_paths()
    print("model-upgrade benchmark")
    print(f"Output directory: {args.output_dir.resolve()}")
    print("-" * 72)
    for data_path in data_paths:
        if not data_path.exists():
            print(f"Skipping missing file: {data_path}")
            continue
        benchmark_file(
            data_path,
            output_dir=args.output_dir,
            timeout_override=args.timeout,
        )


if __name__ == "__main__":
    main()
