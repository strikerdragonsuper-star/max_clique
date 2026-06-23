#!/usr/bin/env python3
"""Generate shuffled-node test graphs with solver reference outputs."""

from __future__ import annotations

import copy
import json
import random
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIQUE_ROOT = ROOT.parent / "CliqueAI"
TEST_DATA = ROOT / "test_data"
TEST_OUTPUT = ROOT / "test_output"
sys.path.insert(0, str(CLIQUE_ROOT))

from CliqueAI.graph.codec import GraphCodec  # noqa: E402
from model_upgrade import is_valid_maximum_clique, solve_maximum_clique  # noqa: E402

TIER_TIME_LIMITS: dict[float, list[float]] = {
    0.1: [6, 7.5, 10, 15, 30],
    0.7: [6, 7.5, 10, 15, 30],
    0.8: [6, 7.5, 10, 15, 30],
    0.9: [6, 7.5, 10, 15, 30],
    1.0: [7.5, 10, 15, 30],
}

# (source_file, difficulty, shuffle_index)
GENERATION_PLAN: list[tuple[str, float, int]] = [
    ("sample.json", 0.1, 1),
    ("sample.json", 0.1, 2),
    ("general_0.1.json", 0.1, 1),
    ("general_0.1.json", 0.1, 2),
    ("general_0.2.json", 0.7, 1),
    ("general_0.2.json", 0.7, 2),
    ("general_0.2.json", 0.7, 3),
    ("general_0.4.json", 0.8, 1),
    ("general_0.4.json", 0.8, 2),
    ("general_0.4.json", 0.8, 3),
]

SYNAPSE_TEMPLATE = {
    "name": "MaximumCliqueOfLambdaGraph",
    "total_size": 0,
    "header_size": 0,
    "dendrite": {
        "status_code": None,
        "status_message": None,
        "process_time": None,
        "ip": None,
        "port": None,
        "version": None,
        "nonce": None,
        "uuid": None,
        "hotkey": None,
        "signature": None,
    },
    "axon": {
        "status_code": None,
        "status_message": None,
        "process_time": None,
        "ip": None,
        "port": None,
        "version": None,
        "nonce": None,
        "uuid": None,
        "hotkey": None,
        "signature": None,
    },
    "computed_body_hash": "",
    "label": "general",
}


def shuffle_adjacency_list(adjacency_list: list[list[int]], seed: int) -> list[list[int]]:
    """Shuffle vertex labels the same way subnet validators do."""
    rng = random.Random(seed)
    n = len(adjacency_list)
    old_vertices = list(range(n))
    new_vertices = copy.deepcopy(old_vertices)
    rng.shuffle(new_vertices)
    vertex_map = dict(zip(old_vertices, new_vertices))

    shuffled = [[] for _ in range(n)]
    for old_u in range(n):
        new_u = vertex_map[old_u]
        shuffled[new_u] = sorted(vertex_map[old_v] for old_v in adjacency_list[old_u])
    return shuffled


def reference_timeout(difficulty: float) -> float:
    """Use the tier maximum for reference clique generation."""
    limits = TIER_TIME_LIMITS.get(difficulty, [30.0])
    return max(limits)


def load_source(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def build_synapse_payload(
    *,
    adjacency_list: list[list[int]],
    difficulty: float,
    source_file: str,
    shuffle_index: int,
    seed: int,
    maximum_clique: list[int],
    solver_timeout: float,
    solver_elapsed: float,
) -> dict:
    codec = GraphCodec()
    n = len(adjacency_list)
    adj_matrix = codec.list_to_matrix(adjacency_list, n)
    encoded_matrix = codec.encode_matrix(adj_matrix)
    timeout = reference_timeout(difficulty)

    payload = copy.deepcopy(SYNAPSE_TEMPLATE)
    payload.update(
        {
            "uuid": str(uuid.uuid4()),
            "number_of_nodes": n,
            "encoded_matrix": encoded_matrix,
            "timeout": timeout,
            "difficulty": difficulty,
            "source_file": source_file,
            "shuffle_index": shuffle_index,
            "shuffle_seed": seed,
            "maximum_clique": maximum_clique,
            "reference_solver": {
                "elapsed_seconds": round(solver_elapsed, 6),
                "solver_timeout": solver_timeout,
                "valid": is_valid_maximum_clique(adjacency_list, maximum_clique),
                "clique_size": len(maximum_clique),
            },
        }
    )
    return payload


def generate_one(
    source_path: Path,
    difficulty: float,
    shuffle_index: int,
) -> tuple[Path, Path]:
    source = load_source(source_path)
    codec = GraphCodec()
    adjacency_matrix = codec.decode_matrix(source["encoded_matrix"])
    adjacency_list = codec.matrix_to_list(adjacency_matrix)

    seed = int(difficulty * 1000) + shuffle_index * 17 + len(adjacency_list)
    shuffled = shuffle_adjacency_list(adjacency_list, seed=seed)

    solver_timeout = reference_timeout(difficulty)
    import time

    start = time.perf_counter()
    clique = solve_maximum_clique(
        len(shuffled),
        shuffled,
        time_limit=solver_timeout,
        seed=seed,
    )
    elapsed = time.perf_counter() - start

    if not is_valid_maximum_clique(shuffled, clique):
        raise RuntimeError(f"Solver returned invalid clique for {source_path.name} seed={seed}")

    difficulty_label = str(difficulty).replace(".", "_")
    source_stem = source_path.stem
    filename = f"shuffled_{source_stem}_d{difficulty_label}_{shuffle_index:02d}.json"
    test_path = TEST_DATA / filename
    output_path = TEST_OUTPUT / filename

    payload = build_synapse_payload(
        adjacency_list=shuffled,
        difficulty=difficulty,
        source_file=source_path.name,
        shuffle_index=shuffle_index,
        seed=seed,
        maximum_clique=clique,
        solver_timeout=solver_timeout,
        solver_elapsed=elapsed,
    )

    TEST_DATA.mkdir(parents=True, exist_ok=True)
    TEST_OUTPUT.mkdir(parents=True, exist_ok=True)

    with test_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=4)
        handle.write("\n")

    result = {
        "input_file": str(test_path.resolve()),
        "uuid": payload["uuid"],
        "label": payload["label"],
        "number_of_nodes": payload["number_of_nodes"],
        "difficulty": difficulty,
        "timeout": payload["timeout"],
        "source_file": source_path.name,
        "shuffle_seed": seed,
        "elapsed_seconds": round(elapsed, 6),
        "valid": True,
        "clique_size": len(clique),
        "maximum_clique": clique,
    }
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")

    return test_path, output_path


def main() -> None:
    print("Generating 10 shuffled test files...")
    print(f"test_data  -> {TEST_DATA}")
    print(f"test_output -> {TEST_OUTPUT}")
    print("-" * 72)

    for source_name, difficulty, shuffle_index in GENERATION_PLAN:
        source_path = TEST_DATA / source_name
        if not source_path.exists():
            source_path = CLIQUE_ROOT / "test_data" / source_name
        if not source_path.exists():
            raise FileNotFoundError(f"Missing source graph: {source_name}")

        test_path, output_path = generate_one(source_path, difficulty, shuffle_index)
        with test_path.open("r", encoding="utf-8") as handle:
            meta = json.load(handle)
        print(
            f"{test_path.name:28} | d={difficulty:.1f} | nodes={meta['number_of_nodes']:4} | "
            f"clique={meta['reference_solver']['clique_size']:4} | "
            f"from {source_name}"
        )
        print(f"{'':28}   saved test   -> {test_path}")
        print(f"{'':28}   saved output -> {output_path}")

    print("-" * 72)
    print("Done.")


if __name__ == "__main__":
    main()
