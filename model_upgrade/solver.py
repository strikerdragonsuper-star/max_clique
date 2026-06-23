import os
import random
import time
from concurrent.futures import ProcessPoolExecutor

from model_upgrade.bitsets import MAX_BITSET_NODES, neighbor_sets_to_masks
from model_upgrade.branch_bound import branch_and_bound_max_clique
from model_upgrade.graph_utils import (
    build_search_core,
    core_and_degeneracy,
    extract_subgraph,
    map_clique_to_original,
)
from model_upgrade.heuristics import (
    bitset_local_search,
    local_search,
    random_restarts,
)
from model_upgrade.validation import extend_to_maximal_clique, is_valid_maximum_clique

# Seconds reserved before validator timeout for decode/encode/network overhead.
TIME_HEADROOM_SECONDS = 0.7
MIN_SEARCH_SECONDS = 0.5
CORE_EXACT_THRESHOLD = 230
CORE_SEARCH_THRESHOLD = 320
PORTFOLIO_PARALLEL_MIN_TIMEOUT = 10.0
PORTFOLIO_WORKERS = 3
PORTFOLIO_RUNS = 3
BURST_RESTART_SECONDS = 0.10
BURST_LOCAL_SECONDS = 0.20

# Diversified portfolio strategies: phase weights + BB aggressiveness.
STRATEGIES: list[dict[str, float]] = [
    {"heuristic": 0.12, "local": 0.20, "bb": 0.45},   # exact-heavy
    {"heuristic": 0.15, "local": 0.55, "bb": 0.05},   # local-search-heavy
    {"heuristic": 0.35, "local": 0.30, "bb": 0.15},   # construction-heavy
]


def search_budget(validator_timeout: float) -> float:
    """Search seconds available before the validator timeout."""
    return max(MIN_SEARCH_SECONDS, validator_timeout - TIME_HEADROOM_SECONDS)


def _subgraph_adjacency(sub_neighbor_sets: list[set[int]]) -> list[list[int]]:
    return [sorted(neighbors) for neighbors in sub_neighbor_sets]


def _local_search_best(
    neighbor_sets: list[set[int]],
    neighbor_masks: list[int] | None,
    n: int,
    clique: list[int],
    deadline: float,
    rng: random.Random,
    penalties: list[int] | None,
) -> list[int]:
    if neighbor_masks is not None:
        return bitset_local_search(
            neighbor_masks,
            n,
            clique,
            deadline,
            rng,
            penalties=penalties,
        )
    return local_search(neighbor_sets, clique, deadline, rng)


def _refine_on_core(
    best: list[int],
    neighbor_sets: list[set[int]],
    adjacency_list: list[list[int]],
    core_numbers: list[int],
    neighbor_masks: list[int] | None,
    deadline: float,
    bb_seconds: float,
    rng: random.Random,
) -> list[int]:
    if time.perf_counter() >= deadline:
        return best

    core_vertices = build_search_core(best, neighbor_sets, core_numbers)
    if len(core_vertices) <= len(best):
        return best

    if len(core_vertices) > CORE_SEARCH_THRESHOLD:
        extra = sorted(
            (v for v in range(len(neighbor_sets)) if core_numbers[v] >= len(best) - 1),
            key=lambda v: len(neighbor_sets[v]),
            reverse=True,
        )[:CORE_SEARCH_THRESHOLD]
        core_vertices = sorted(set(best) | set(extra))

    subgraph, labels = extract_subgraph(neighbor_sets, core_vertices)
    if len(subgraph) <= len(best):
        return best

    sub_adj = _subgraph_adjacency(subgraph)
    sub_n = len(subgraph)
    sub_masks = neighbor_sets_to_masks(subgraph) if sub_n <= MAX_BITSET_NODES else None
    _, sub_degeneracy = core_and_degeneracy(subgraph)
    sub_penalties = [0] * sub_n

    remaining = max(0.0, deadline - time.perf_counter())
    search_deadline = time.perf_counter() + min(remaining, max(0.15, remaining * 0.45))

    sub_best = random_restarts(
        subgraph,
        search_deadline,
        rng,
        degeneracy=sub_degeneracy,
        neighbor_masks=sub_masks,
    )
    sub_best = extend_to_maximal_clique(sub_adj, sub_best)

    if time.perf_counter() < search_deadline:
        sub_best = _local_search_best(
            subgraph,
            sub_masks,
            sub_n,
            sub_best,
            search_deadline,
            rng,
            sub_penalties,
        )
        sub_best = extend_to_maximal_clique(sub_adj, sub_best)

    if sub_n <= CORE_EXACT_THRESHOLD and time.perf_counter() < deadline:
        bb_deadline = min(deadline, time.perf_counter() + min(bb_seconds, 3.0))
        exact = branch_and_bound_max_clique(subgraph, sub_best, bb_deadline)
        if len(exact) > len(sub_best):
            sub_best = exact
        sub_best = extend_to_maximal_clique(sub_adj, sub_best)

    mapped = map_clique_to_original(sub_best, labels)
    mapped = extend_to_maximal_clique(adjacency_list, mapped)
    if len(mapped) > len(best):
        return mapped
    return best


def _improve_until_deadline(
    best: list[int],
    neighbor_sets: list[set[int]],
    adjacency_list: list[list[int]],
    core_numbers: list[int],
    degeneracy: list[int],
    neighbor_masks: list[int] | None,
    deadline: float,
    bb_seconds: float,
    rng: random.Random,
    penalties: list[int],
) -> list[int]:
    n = len(neighbor_sets)
    while time.perf_counter() < deadline:
        burst_deadline = min(deadline, time.perf_counter() + BURST_RESTART_SECONDS)
        candidate = random_restarts(
            neighbor_sets,
            burst_deadline,
            rng,
            degeneracy=degeneracy,
            neighbor_masks=neighbor_masks,
        )
        candidate = extend_to_maximal_clique(adjacency_list, candidate)

        burst_deadline = min(deadline, time.perf_counter() + BURST_LOCAL_SECONDS)
        candidate = _local_search_best(
            neighbor_sets,
            neighbor_masks,
            n,
            candidate,
            burst_deadline,
            rng,
            penalties,
        )
        candidate = extend_to_maximal_clique(adjacency_list, candidate)

        if len(candidate) > len(best):
            best = candidate
            best = _refine_on_core(
                best,
                neighbor_sets,
                adjacency_list,
                core_numbers,
                neighbor_masks,
                deadline,
                bb_seconds * 0.5,
                rng,
            )

    return best


def _solve_single(
    number_of_nodes: int,
    adjacency_list: list[list[int]],
    budget_seconds: float,
    seed: int,
    strategy: dict[str, float],
    deadline: float | None = None,
) -> list[int]:
    rng = random.Random(seed)
    neighbor_sets = [set(neighbors) for neighbors in adjacency_list]
    core_numbers, degeneracy = core_and_degeneracy(neighbor_sets)
    neighbor_masks = (
        neighbor_sets_to_masks(neighbor_sets)
        if number_of_nodes <= MAX_BITSET_NODES
        else None
    )
    penalties = [0] * number_of_nodes

    start = time.perf_counter()
    if deadline is None:
        deadline = start + budget_seconds
    else:
        deadline = min(deadline, start + budget_seconds)

    heuristic_deadline = start + max(0.05, budget_seconds * strategy["heuristic"])
    local_deadline = start + max(0.1, budget_seconds * strategy["local"])
    bb_seconds = max(0.5, budget_seconds * strategy["bb"])

    best = random_restarts(
        neighbor_sets,
        min(heuristic_deadline, deadline),
        rng,
        degeneracy=degeneracy,
        neighbor_masks=neighbor_masks,
    )
    best = extend_to_maximal_clique(adjacency_list, best)

    best = _local_search_best(
        neighbor_sets,
        neighbor_masks,
        number_of_nodes,
        best,
        min(local_deadline, deadline),
        rng,
        penalties,
    )
    best = extend_to_maximal_clique(adjacency_list, best)

    best = _refine_on_core(
        best,
        neighbor_sets,
        adjacency_list,
        core_numbers,
        neighbor_masks,
        deadline,
        bb_seconds,
        rng,
    )

    if time.perf_counter() < deadline:
        bb_deadline = min(deadline, time.perf_counter() + min(bb_seconds, 2.0))
        exact = branch_and_bound_max_clique(neighbor_sets, best, bb_deadline)
        if len(exact) > len(best):
            best = exact
        best = extend_to_maximal_clique(adjacency_list, best)

    best = _improve_until_deadline(
        best,
        neighbor_sets,
        adjacency_list,
        core_numbers,
        degeneracy,
        neighbor_masks,
        deadline,
        bb_seconds,
        rng,
        penalties,
    )

    if not is_valid_maximum_clique(adjacency_list, best):
        best = [max(range(number_of_nodes), key=lambda v: len(neighbor_sets[v]))]
        best = extend_to_maximal_clique(adjacency_list, best)

    return sorted(best)


def _portfolio_worker(
    args: tuple[int, list[list[int]], float, int, dict[str, float], float],
) -> list[int]:
    number_of_nodes, adjacency_list, budget_seconds, seed, strategy, deadline = args
    return _solve_single(
        number_of_nodes,
        adjacency_list,
        budget_seconds,
        seed,
        strategy,
        deadline=deadline,
    )


def solve_maximum_clique(
    number_of_nodes: int,
    adjacency_list: list[list[int]],
    time_limit: float = 30.0,
    seed: int | None = None,
) -> list[int]:
    """
    Find a large maximal clique within the validator time budget.

    Diversified portfolio of bitset heuristics, penalty local search, and
    coloring branch-and-bound. Leaves TIME_HEADROOM_SECONDS before timeout.
    """
    if number_of_nodes != len(adjacency_list):
        raise ValueError(
            f"number_of_nodes ({number_of_nodes}) does not match adjacency_list length ({len(adjacency_list)})"
        )

    if number_of_nodes == 0:
        return []

    if seed is None:
        seed = int(time.perf_counter() * 1_000_000)

    budget = search_budget(time_limit)
    outer_start = time.perf_counter()
    outer_deadline = outer_start + budget
    cpu_count = os.cpu_count() or 1

    best: list[int] = []

    if time_limit >= PORTFOLIO_PARALLEL_MIN_TIMEOUT and cpu_count >= 4:
        tasks = [
            (
                number_of_nodes,
                adjacency_list,
                budget,
                seed + i * 7919,
                STRATEGIES[i % len(STRATEGIES)],
                outer_deadline,
            )
            for i in range(PORTFOLIO_WORKERS)
        ]
        with ProcessPoolExecutor(max_workers=PORTFOLIO_WORKERS) as pool:
            results = list(pool.map(_portfolio_worker, tasks))
        best = max(results, key=len)
    elif time_limit <= 6.5:
        best = _solve_single(
            number_of_nodes,
            adjacency_list,
            budget,
            seed,
            STRATEGIES[0],
            deadline=outer_deadline,
        )
    else:
        run_budget = budget / 2 if time_limit < 15.0 else budget / PORTFOLIO_RUNS
        runs = 2 if time_limit < 15.0 else PORTFOLIO_RUNS
        for run in range(runs):
            if time.perf_counter() >= outer_deadline:
                break
            candidate = _solve_single(
                number_of_nodes,
                adjacency_list,
                run_budget,
                seed + run * 7919,
                STRATEGIES[run % len(STRATEGIES)],
                deadline=outer_deadline,
            )
            if len(candidate) > len(best):
                best = candidate

    if best and time.perf_counter() < outer_deadline:
        neighbor_sets = [set(neighbors) for neighbors in adjacency_list]
        core_numbers, degeneracy = core_and_degeneracy(neighbor_sets)
        neighbor_masks = (
            neighbor_sets_to_masks(neighbor_sets)
            if number_of_nodes <= MAX_BITSET_NODES
            else None
        )
        penalties = [0] * number_of_nodes
        rng = random.Random(seed + 424242)
        bb_seconds = max(0.5, budget * 0.2)
        best = _improve_until_deadline(
            best,
            neighbor_sets,
            adjacency_list,
            core_numbers,
            degeneracy,
            neighbor_masks,
            outer_deadline,
            bb_seconds,
            rng,
            penalties,
        )

    if not best or not is_valid_maximum_clique(adjacency_list, best):
        neighbor_sets = [set(neighbors) for neighbors in adjacency_list]
        best = [max(range(number_of_nodes), key=lambda v: len(neighbor_sets[v]))]
        best = extend_to_maximal_clique(adjacency_list, best)

    return sorted(best)
