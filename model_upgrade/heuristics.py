import random
import time
from typing import Callable


def _to_neighbor_sets(adjacency_list: list[list[int]]) -> list[set[int]]:
    return [set(neighbors) for neighbors in adjacency_list]


def greedy_clique(
    neighbor_sets: list[set[int]],
    vertex_order: list[int],
) -> list[int]:
    """Build a clique by scanning vertices in the given order."""
    clique: list[int] = []
    clique_set: set[int] = set()
    for vertex in vertex_order:
        if not clique_set or clique_set.issubset(neighbor_sets[vertex]):
            clique.append(vertex)
            clique_set.add(vertex)
    return clique


def random_restarts(
    neighbor_sets: list[set[int]],
    deadline: float,
    rng: random.Random,
) -> list[int]:
    """Run greedy construction with varied vertex orderings until the deadline."""
    n = len(neighbor_sets)
    degrees = [len(neighbors) for neighbors in neighbor_sets]
    best: list[int] = []

    static_orders = [
        sorted(range(n), key=lambda v: degrees[v], reverse=True),
        sorted(range(n), key=lambda v: degrees[v]),
        sorted(range(n), key=lambda v: (degrees[v], v), reverse=True),
        list(range(n)),
        list(reversed(range(n))),
    ]

    for order in static_orders:
        if time.perf_counter() >= deadline:
            break
        candidate = greedy_clique(neighbor_sets, order)
        if len(candidate) > len(best):
            best = candidate

    while time.perf_counter() < deadline:
        order = list(range(n))
        rng.shuffle(order)
        candidate = greedy_clique(neighbor_sets, order)
        if len(candidate) > len(best):
            best = candidate

    return best


def local_search(
    neighbor_sets: list[set[int]],
    clique: list[int],
    deadline: float,
    rng: random.Random,
) -> list[int]:
    """Try single-vertex swaps that preserve or grow clique size."""
    best = list(clique)
    best_set = set(best)
    n = len(neighbor_sets)

    while time.perf_counter() < deadline:
        if not best:
            break

        remove_vertex = rng.choice(best)
        reduced = best_set - {remove_vertex}
        candidates = [
            vertex
            for vertex in range(n)
            if vertex not in reduced and reduced.issubset(neighbor_sets[vertex])
        ]
        if not candidates:
            continue

        add_vertex = rng.choice(candidates)
        trial = sorted(reduced | {add_vertex})
        if len(trial) >= len(best):
            best = trial
            best_set = set(best)

    return best
