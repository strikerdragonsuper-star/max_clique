#!/usr/bin/env python3
"""Generate synthetic graphs with a maximum clique and several smaller embedded cliques."""

from __future__ import annotations

import copy
import json
import random
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIQUE_ROOT = ROOT.parent / "CliqueAI"
TEST_DATA = ROOT / "test_data"
TEST_OUTPUT = ROOT / "test_output"
sys.path.insert(0, str(CLIQUE_ROOT))

from CliqueAI.graph.codec import GraphCodec  # noqa: E402
from model_upgrade import is_valid_maximum_clique, solve_maximum_clique  # noqa: E402

MIN_CLIQUE_SIZE = 51
NUM_SMALLER_CLIQUES = 4

# (number_of_nodes, difficulty, maximum_clique_size, variant_index)
GENERATION_PLAN: list[tuple[int, float, int, int]] = [
    (298, 0.7, 52, 1),
    (298, 0.7, 55, 2),
    (298, 0.7, 58, 3),
    (298, 0.7, 62, 4),
    (493, 0.8, 51, 1),
    (493, 0.8, 54, 2),
    (493, 0.8, 58, 3),
    (493, 0.8, 62, 4),
    (493, 0.8, 66, 5),
    (493, 0.8, 72, 6),
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


def is_clique(adjacency_list: list[list[int]], nodes: list[int]) -> bool:
    node_set = set(nodes)
    if len(node_set) != len(nodes) or not node_set:
        return False
    node_list = list(node_set)
    for i in range(len(node_list)):
        for j in range(i + 1, len(node_list)):
            if node_list[j] not in adjacency_list[node_list[i]]:
                return False
    return True


def connect_clique(adjacency: list[set[int]], vertices: list[int]) -> None:
    for i in range(len(vertices)):
        for j in range(i + 1, len(vertices)):
            u, v = vertices[i], vertices[j]
            adjacency[u].add(v)
            adjacency[v].add(u)


def pick_smaller_clique_sizes(
    max_size: int,
    rng: random.Random,
    count: int,
) -> list[int]:
    """Pick distinct clique sizes in [5, max_size], all <= maximum."""
    sizes: set[int] = set()
    min_size = max(5, max_size // 8)
    attempts = 0
    while len(sizes) < count and attempts < count * 20:
        attempts += 1
        size = rng.randint(min_size, max_size)
        sizes.add(size)
    if not sizes:
        sizes.add(max(min_size, max_size // 2))
    return sorted(sizes, reverse=True)


def generate_graph_with_cliques(
    number_of_nodes: int,
    max_clique_size: int,
    seed: int,
    num_smaller_cliques: int = NUM_SMALLER_CLIQUES,
) -> tuple[list[list[int]], list[int], list[dict]]:
    """
    Build a graph with one maximum clique and several smaller disjoint cliques.

    Smaller cliques live on separate vertex islands and cannot merge with each other
    or grow the maximum clique beyond max_clique_size.
    """
    if max_clique_size <= 50:
        raise ValueError(f"max_clique_size must be > 50, got {max_clique_size}")
    if max_clique_size >= number_of_nodes:
        raise ValueError("max_clique_size must be smaller than number_of_nodes")

    rng = random.Random(seed)
    adjacency = [set() for _ in range(number_of_nodes)]

    maximum_clique = list(range(max_clique_size))
    connect_clique(adjacency, maximum_clique)

    smaller_sizes = pick_smaller_clique_sizes(max_clique_size, rng, num_smaller_cliques)
    embedded_cliques: list[dict] = [
        {"role": "maximum", "size": max_clique_size, "vertices": list(maximum_clique)},
    ]

    cursor = max_clique_size
    for index, clique_size in enumerate(smaller_sizes):
        if cursor + clique_size > number_of_nodes:
            break

        island = list(range(cursor, cursor + clique_size))
        connect_clique(adjacency, island)

        # Optional sparse links into the maximum clique (never to all members).
        max_links = min(12, max_clique_size - 2)
        for vertex in island:
            link_count = rng.randint(0, max(1, max_links))
            for core_vertex in rng.sample(maximum_clique, link_count):
                adjacency[vertex].add(core_vertex)
                adjacency[core_vertex].add(vertex)

        embedded_cliques.append(
            {
                "role": "smaller",
                "size": clique_size,
                "vertices": island,
                "index": index,
            }
        )
        cursor += clique_size

    # Padding vertices: connect only sparsely to the maximum clique.
    for vertex in range(cursor, number_of_nodes):
        neighbor_count = rng.randint(1, min(max_clique_size - 2, 12))
        for core_vertex in rng.sample(maximum_clique, neighbor_count):
            adjacency[vertex].add(core_vertex)
            adjacency[core_vertex].add(vertex)

    adjacency_list = [sorted(neighbors) for neighbors in adjacency]

    if not is_valid_maximum_clique(adjacency_list, maximum_clique):
        raise RuntimeError("Maximum clique is not valid/maximal after construction")

    for entry in embedded_cliques:
        if not is_clique(adjacency_list, entry["vertices"]):
            raise RuntimeError(f"Embedded clique of size {entry['size']} is not a clique")
        if entry["size"] > max_clique_size:
            raise RuntimeError("Found embedded clique larger than declared maximum")

    return adjacency_list, maximum_clique, embedded_cliques


def shuffle_adjacency_list(
    adjacency_list: list[list[int]],
    seed: int,
) -> tuple[list[list[int]], dict[int, int]]:
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
    return shuffled, vertex_map


def remap_clique(clique: list[int], vertex_map: dict[int, int]) -> list[int]:
    return sorted(vertex_map[vertex] for vertex in clique)


def remap_embedded_cliques(
    embedded_cliques: list[dict],
    vertex_map: dict[int, int],
) -> list[dict]:
    remapped = []
    for entry in embedded_cliques:
        remapped.append(
            {
                **entry,
                "vertices": remap_clique(entry["vertices"], vertex_map),
            }
        )
    return remapped


def build_payload(
    *,
    adjacency_list: list[list[int]],
    difficulty: float,
    max_clique_size: int,
    variant_index: int,
    seed: int,
    shuffle_seed: int,
    maximum_clique: list[int],
    embedded_cliques: list[dict],
    solver_timeout: float,
    solver_elapsed: float,
) -> dict:
    codec = GraphCodec()
    n = len(adjacency_list)
    encoded_matrix = codec.encode_matrix(codec.list_to_matrix(adjacency_list, n))

    payload = copy.deepcopy(SYNAPSE_TEMPLATE)
    payload.update(
        {
            "uuid": str(uuid.uuid4()),
            "number_of_nodes": n,
            "encoded_matrix": encoded_matrix,
            "timeout": 30.0,
            "difficulty": difficulty,
            "maximum_clique_size": max_clique_size,
            "variant_index": variant_index,
            "generation_seed": seed,
            "shuffle_seed": shuffle_seed,
            "maximum_clique": maximum_clique,
            "embedded_cliques": embedded_cliques,
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
    number_of_nodes: int,
    difficulty: float,
    max_clique_size: int,
    variant_index: int,
) -> tuple[Path, Path]:
    seed = number_of_nodes * 17 + int(difficulty * 1000) + max_clique_size * 31 + variant_index
    shuffle_seed = seed + 100_000

    adjacency_list, maximum_clique, embedded_cliques = generate_graph_with_cliques(
        number_of_nodes,
        max_clique_size,
        seed,
    )
    shuffled, vertex_map = shuffle_adjacency_list(adjacency_list, shuffle_seed)
    reference_clique = remap_clique(maximum_clique, vertex_map)
    remapped_cliques = remap_embedded_cliques(embedded_cliques, vertex_map)

    if not is_valid_maximum_clique(shuffled, reference_clique):
        raise RuntimeError("Maximum clique invalid after shuffle")
    if len(reference_clique) <= 50:
        raise RuntimeError(f"Reference clique size {len(reference_clique)} is not > 50")

    for entry in remapped_cliques:
        if not is_clique(shuffled, entry["vertices"]):
            raise RuntimeError(f"Clique size {entry['size']} invalid after shuffle")
        if entry["size"] > max_clique_size:
            raise RuntimeError("Remapped clique exceeds declared maximum size")

    solver_timeout = 30.0
    start = time.perf_counter()
    solved = solve_maximum_clique(
        len(shuffled),
        shuffled,
        time_limit=solver_timeout,
        seed=shuffle_seed,
    )
    elapsed = time.perf_counter() - start

    payload = build_payload(
        adjacency_list=shuffled,
        difficulty=difficulty,
        max_clique_size=max_clique_size,
        variant_index=variant_index,
        seed=seed,
        shuffle_seed=shuffle_seed,
        maximum_clique=reference_clique,
        embedded_cliques=remapped_cliques,
        solver_timeout=solver_timeout,
        solver_elapsed=elapsed,
    )
    payload["reference_solver"]["solver_clique_size"] = len(solved)
    payload["reference_solver"]["solver_valid"] = is_valid_maximum_clique(shuffled, solved)

    difficulty_label = str(difficulty).replace(".", "_")
    filename = (
        f"large_clique_n{number_of_nodes}_d{difficulty_label}_"
        f"c{max_clique_size}_{variant_index:02d}.json"
    )
    test_path = TEST_DATA / filename
    output_path = TEST_OUTPUT / filename

    TEST_DATA.mkdir(parents=True, exist_ok=True)
    TEST_OUTPUT.mkdir(parents=True, exist_ok=True)

    with test_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=4)
        handle.write("\n")

    smaller_sizes = [e["size"] for e in remapped_cliques if e["role"] == "smaller"]
    result = {
        "input_file": str(test_path.resolve()),
        "uuid": payload["uuid"],
        "label": payload["label"],
        "number_of_nodes": payload["number_of_nodes"],
        "difficulty": difficulty,
        "timeout": payload["timeout"],
        "maximum_clique_size": max_clique_size,
        "smaller_clique_sizes": smaller_sizes,
        "reference_clique_size": len(reference_clique),
        "solver_clique_size": len(solved),
        "elapsed_seconds": round(elapsed, 6),
        "valid": True,
        "clique_size": len(reference_clique),
        "maximum_clique": reference_clique,
        "embedded_cliques": remapped_cliques,
    }
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")

    return test_path, output_path


def main() -> None:
    print(
        f"Generating graphs with max clique > {MIN_CLIQUE_SIZE - 1} "
        f"and {NUM_SMALLER_CLIQUES} smaller embedded cliques..."
    )
    print(f"test_data   -> {TEST_DATA}")
    print(f"test_output -> {TEST_OUTPUT}")
    print("-" * 80)

    for number_of_nodes, difficulty, max_clique_size, variant_index in GENERATION_PLAN:
        test_path, output_path = generate_one(
            number_of_nodes,
            difficulty,
            max_clique_size,
            variant_index,
        )
        with test_path.open("r", encoding="utf-8") as handle:
            meta = json.load(handle)
        smaller = [e["size"] for e in meta["embedded_cliques"] if e["role"] == "smaller"]
        print(
            f"{test_path.name:42} | d={difficulty:.1f} | nodes={number_of_nodes:4} | "
            f"max={meta['reference_solver']['clique_size']:3} | "
            f"smaller={smaller} | solver={meta['reference_solver'].get('solver_clique_size', '?'):>3}"
        )
        print(f"{'':42}   saved test   -> {test_path}")
        print(f"{'':42}   saved output -> {output_path}")

    print("-" * 80)
    print("Done.")


if __name__ == "__main__":
    main()
