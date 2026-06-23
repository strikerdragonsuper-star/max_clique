"""Dense lambda graphs: max-clique via max independent set on the complement."""

import random
import time

from model_upgrade.bitsets import (
    MAX_BITSET_NODES,
    mask_degree,
    mask_intersection,
    mask_vertices,
    neighbor_sets_to_masks,
)
from model_upgrade.graph_utils import core_and_degeneracy
from model_upgrade.validation import extend_to_maximal_clique, is_valid_maximum_clique

# Validator lambda graphs: complement search from ~70% edge density upward.
DENSE_DEGREE_RATIO = 0.70


def is_dense_graph(
    neighbor_sets: list[set[int]],
    threshold: float = DENSE_DEGREE_RATIO,
) -> bool:
    """True when the graph is a dense lambda instance (complement is sparse)."""
    n = len(neighbor_sets)
    if n <= 1:
        return False
    avg_degree = sum(len(neighbors) for neighbors in neighbor_sets) / n
    return avg_degree / (n - 1) >= threshold


def complement_neighbor_sets(neighbor_sets: list[set[int]]) -> list[set[int]]:
    """Non-neighbors in G (neighbors in the complement graph)."""
    n = len(neighbor_sets)
    universe = set(range(n))
    return [universe - {vertex} - neighbor_sets[vertex] for vertex in range(n)]


def _iter_bits(mask: int):
    while mask:
        low = mask & -mask
        yield low.bit_length() - 1
        mask &= ~low


def greedy_mis(
    comp_neighbors: list[set[int]],
    vertex_order: list[int],
) -> list[int]:
    """Greedy independent set on the complement graph."""
    mis: list[int] = []
    blocked: set[int] = set()
    for vertex in vertex_order:
        if vertex in blocked:
            continue
        mis.append(vertex)
        blocked.add(vertex)
        blocked.update(comp_neighbors[vertex])
    return mis


def greedy_mis_grasp(
    comp_neighbors: list[set[int]],
    rng: random.Random,
    start_vertex: int | None = None,
    rcl_size: int = 5,
    comp_masks: list[int] | None = None,
) -> list[int]:
    """GRASP independent-set construction (low complement-degree first)."""
    n = len(comp_neighbors)
    use_masks = comp_masks is not None and n <= MAX_BITSET_NODES

    mis: list[int] = []
    if start_vertex is not None:
        mis = [start_vertex]

    if use_masks:
        assert comp_masks is not None
        blocked_mask = 0
        for vertex in mis:
            blocked_mask |= (1 << vertex) | comp_masks[vertex]

        while True:
            available_mask = ((1 << n) - 1) & ~blocked_mask
            if not available_mask:
                break
            candidates = mask_vertices(available_mask)
            ranked = sorted(
                candidates,
                key=lambda v: mask_degree(comp_masks[v] & available_mask),
            )
            top = ranked[: min(rcl_size, len(ranked))]
            chosen = rng.choice(top)
            mis.append(chosen)
            blocked_mask |= (1 << chosen) | comp_masks[chosen]
        return mis

    blocked: set[int] = set()
    for vertex in mis:
        blocked.add(vertex)
        blocked.update(comp_neighbors[vertex])

    while True:
        available = set(range(n)) - blocked
        if not available:
            break
        ranked = sorted(
            available,
            key=lambda v: len(comp_neighbors[v] & available),
        )
        top = ranked[: min(rcl_size, len(ranked))]
        chosen = rng.choice(top)
        mis.append(chosen)
        blocked.add(chosen)
        blocked.update(comp_neighbors[chosen])
    return mis


def mis_random_restarts(
    comp_neighbors: list[set[int]],
    deadline: float,
    rng: random.Random,
    comp_masks: list[int] | None = None,
) -> list[int]:
    """Multi-start greedy / GRASP independent-set construction."""
    n = len(comp_neighbors)
    comp_degrees = [len(neighbors) for neighbors in comp_neighbors]
    best: list[int] = []

    static_orders = [
        sorted(range(n), key=lambda v: comp_degrees[v]),
        sorted(range(n), key=lambda v: comp_degrees[v], reverse=True),
        sorted(range(n), key=lambda v: (comp_degrees[v], v)),
        list(range(n)),
        list(reversed(range(n))),
    ]
    _, degeneracy = core_and_degeneracy(comp_neighbors)
    static_orders.append(list(degeneracy))
    static_orders.append(list(reversed(degeneracy)))

    for order in static_orders:
        if time.perf_counter() >= deadline:
            break
        candidate = greedy_mis(comp_neighbors, order)
        if len(candidate) > len(best):
            best = candidate

    sparse_starts = sorted(range(n), key=lambda v: comp_degrees[v])[: min(24, n)]
    for start in sparse_starts:
        if time.perf_counter() >= deadline:
            break
        candidate = greedy_mis_grasp(
            comp_neighbors,
            rng,
            start_vertex=start,
            comp_masks=comp_masks,
        )
        if len(candidate) > len(best):
            best = candidate

    while time.perf_counter() < deadline:
        if rng.random() < 0.55 and sparse_starts:
            start = rng.choice(sparse_starts)
            candidate = greedy_mis_grasp(
                comp_neighbors,
                rng,
                start_vertex=start,
                rcl_size=rng.randint(4, 8),
                comp_masks=comp_masks,
            )
        else:
            order = list(range(n))
            rng.shuffle(order)
            candidate = greedy_mis(comp_neighbors, order)
        if len(candidate) > len(best):
            best = candidate

    return best


def _mis_compatible(comp_neighbors: list[set[int]], mis_set: set[int], vertex: int) -> bool:
    return not (mis_set & comp_neighbors[vertex])


def mis_local_search(
    comp_neighbors: list[set[int]],
    mis: list[int],
    deadline: float,
    rng: random.Random,
) -> list[int]:
    """1-swap and (1,2)-add plateau search on the complement (clique in G)."""
    best = list(mis)
    best_set = set(best)
    n = len(comp_neighbors)

    while time.perf_counter() < deadline:
        if not best:
            break

        remove_vertices: list[int]
        if rng.random() < 0.2 and len(best) >= 2:
            ranked = sorted(best, key=lambda v: len(comp_neighbors[v]))
            remove_vertices = ranked[:2]
        elif rng.random() < 0.75:
            remove_vertices = [min(best, key=lambda v: len(comp_neighbors[v]))]
        else:
            remove_vertices = [rng.choice(best)]

        reduced = best_set - set(remove_vertices)
        candidates = [
            vertex
            for vertex in range(n)
            if vertex not in reduced and _mis_compatible(comp_neighbors, reduced, vertex)
        ]
        if not candidates:
            continue

        improved = False

        if len(remove_vertices) == 1:
            add_vertex = min(candidates, key=lambda v: len(comp_neighbors[v]))
            trial = sorted(reduced | {add_vertex})
            if len(trial) >= len(best):
                best = trial
                best_set = set(best)
                improved = True

            if not improved and len(best) >= 2 and rng.random() < 0.4:
                for i, u in enumerate(candidates):
                    for v in candidates[i + 1 :]:
                        if v not in comp_neighbors[u]:
                            pair_trial = sorted(reduced | {u, v})
                            if len(pair_trial) > len(best):
                                best = pair_trial
                                best_set = set(best)
                                improved = True
                                break
                    if improved:
                        break

        if not improved and len(remove_vertices) == 1:
            add_vertex = rng.choice(candidates)
            trial = sorted(reduced | {add_vertex})
            if len(trial) == len(best):
                best = trial
                best_set = set(best)

    return best


def mis_bitset_local_search(
    comp_masks: list[int],
    n: int,
    init_mis: list[int],
    deadline: float,
    rng: random.Random,
    penalties: list[int] | None = None,
) -> list[int]:
    """Bitset local search on sparse complement adjacency."""
    mis = list(init_mis)
    mis_mask = 0
    for vertex in mis:
        mis_mask |= 1 << vertex

    best = list(mis)
    best_size = len(mis)
    if penalties is None:
        penalties = [0] * n

    full_mask = (1 << n) - 1

    def available_mask() -> int:
        blocked = mis_mask
        for vertex in mis:
            blocked |= comp_masks[vertex]
        return full_mask & ~blocked

    avail = available_mask()
    check_counter = 0

    while True:
        check_counter += 1
        if check_counter >= 256:
            check_counter = 0
            if time.perf_counter() >= deadline:
                break

        if avail:
            if rng.random() < 0.65:
                chosen = -1
                chosen_score = None
                for vertex in _iter_bits(avail):
                    score = (comp_masks[vertex] & avail).bit_count() - penalties[vertex]
                    if chosen_score is None or score < chosen_score:
                        chosen_score = score
                        chosen = vertex
            else:
                chosen = rng.choice(list(_iter_bits(avail)))

            mis.append(chosen)
            mis_mask |= 1 << chosen
            avail = available_mask()

            if len(mis) > best_size:
                best = list(mis)
                best_size = len(mis)
            continue

        if not mis:
            break

        improved = False
        for _ in range(min(len(mis), 4)):
            pivot = rng.choice(mis)
            reduced_mask = mis_mask & ~(1 << pivot)
            mask = full_mask & ~reduced_mask
            for vertex in mis:
                if vertex != pivot:
                    mask &= ~comp_masks[vertex]
            mask &= ~reduced_mask

            pair = None
            for first in _iter_bits(mask):
                rest = mask & ~comp_masks[first] & ~(1 << first)
                if rest:
                    second = (rest & -rest).bit_length() - 1
                    pair = (first, second)
                    break

            if pair is not None:
                first, second = pair
                mis.remove(pivot)
                mis_mask &= ~(1 << pivot)
                mis.extend((first, second))
                mis_mask |= (1 << first) | (1 << second)
                avail = available_mask()
                if len(mis) > best_size:
                    best = list(mis)
                    best_size = len(mis)
                improved = True
                break

        if not improved:
            for vertex in mis:
                penalties[vertex] += 1
            drop = max(mis, key=lambda u: (penalties[u], rng.random()))
            mis.remove(drop)
            mis_mask &= ~(1 << drop)
            avail = available_mask()

    return best


def solve_dense_complement(
    adjacency_list: list[list[int]],
    budget_seconds: float,
    seed: int,
    deadline: float | None = None,
) -> list[int]:
    """
    Find a large maximal clique on dense lambda graphs via complement MIS.

    Max clique in G equals max independent set in the complement of G.
    """
    neighbor_sets = [set(neighbors) for neighbors in adjacency_list]
    n = len(neighbor_sets)
    if n == 0:
        return []

    comp_neighbors = complement_neighbor_sets(neighbor_sets)
    comp_masks = neighbor_sets_to_masks(comp_neighbors) if n <= MAX_BITSET_NODES else None
    penalties = [0] * n
    rng = random.Random(seed)

    start = time.perf_counter()
    if deadline is None:
        deadline = start + budget_seconds
    else:
        deadline = min(deadline, start + budget_seconds)

    heuristic_deadline = start + max(0.08, budget_seconds * 0.35)
    local_deadline = start + max(0.15, budget_seconds * 0.65)

    mis = mis_random_restarts(
        comp_neighbors,
        min(heuristic_deadline, deadline),
        rng,
        comp_masks=comp_masks,
    )
    clique = extend_to_maximal_clique(adjacency_list, sorted(mis))

    if time.perf_counter() < local_deadline:
        mis = mis_local_search(
            comp_neighbors,
            clique,
            min(local_deadline, deadline),
            rng,
        )
        clique = extend_to_maximal_clique(adjacency_list, sorted(mis))

    if comp_masks is not None and time.perf_counter() < deadline:
        mis = mis_bitset_local_search(
            comp_masks,
            n,
            clique,
            deadline,
            rng,
            penalties=penalties,
        )
        clique = extend_to_maximal_clique(adjacency_list, sorted(mis))

    while time.perf_counter() < deadline:
        burst = min(deadline, time.perf_counter() + 0.08)
        mis = mis_random_restarts(comp_neighbors, burst, rng, comp_masks=comp_masks)
        candidate = extend_to_maximal_clique(adjacency_list, sorted(mis))
        burst = min(deadline, time.perf_counter() + 0.12)
        candidate = mis_local_search(comp_neighbors, candidate, burst, rng)
        candidate = extend_to_maximal_clique(adjacency_list, sorted(candidate))
        if len(candidate) > len(clique):
            clique = candidate

    if not is_valid_maximum_clique(adjacency_list, clique):
        seed_vertex = min(range(n), key=lambda v: len(comp_neighbors[v]))
        clique = extend_to_maximal_clique(adjacency_list, [seed_vertex])

    return sorted(clique)
