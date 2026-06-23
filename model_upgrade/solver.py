import hashlib
import os
import random
import time
from concurrent.futures import ProcessPoolExecutor, wait

from model_upgrade.bitsets import MAX_BITSET_NODES, neighbor_sets_to_masks
from model_upgrade.branch_bound import branch_and_bound_max_clique
from model_upgrade.graph_utils import (
    build_search_core,
    core_and_degeneracy,
    extract_subgraph,
    map_clique_to_original,
)
from model_upgrade.dense import is_dense_graph, solve_dense_complement
from model_upgrade.heuristics import (
    bitset_local_search,
    local_search,
    random_restarts,
)
from model_upgrade.validation import extend_to_maximal_clique, is_valid_maximum_clique

# Seconds reserved before validator timeout for decode/encode/network overhead.
TIME_HEADROOM_SECONDS = 0.9
MIN_SEARCH_SECONDS = 0.5
CORE_EXACT_THRESHOLD = 280
CORE_SEARCH_THRESHOLD = 320
PORTFOLIO_PARALLEL_MIN_TIMEOUT = 7.5
DENSE_PARALLEL_MIN_TIMEOUT = 10.0
PORTFOLIO_WORKERS = 3
PORTFOLIO_RUNS = 3
BURST_RESTART_SECONDS = 0.10
BURST_LOCAL_SECONDS = 0.20
DENSE_POLISH_FRACTION = 0.40
SEED_ALT_OFFSET = 999983

# Diversified portfolio strategies: phase weights + BB aggressiveness.
STRATEGIES: list[dict[str, float]] = [
    {"heuristic": 0.12, "local": 0.20, "bb": 0.45},   # exact-heavy
    {"heuristic": 0.15, "local": 0.55, "bb": 0.05},   # local-search-heavy
    {"heuristic": 0.35, "local": 0.30, "bb": 0.15},   # construction-heavy
]


def search_budget(validator_timeout: float) -> float:
    """Search seconds available before the validator timeout."""
    return max(MIN_SEARCH_SECONDS, validator_timeout - TIME_HEADROOM_SECONDS)


def _resolve_seed(
    seed: int | None,
    problem_id: str | None,
    number_of_nodes: int,
    adjacency_list: list[list[int]],
) -> int:
    """Stable RNG seed: explicit > problem uuid > compact graph fingerprint."""
    if seed is not None:
        return seed

    if problem_id:
        digest = hashlib.sha256(problem_id.strip().encode()).digest()
        return int.from_bytes(digest[:8], "big") ^ number_of_nodes

    hasher = hashlib.sha256()
    hasher.update(number_of_nodes.to_bytes(4, "little"))
    edge_count = sum(len(row) for row in adjacency_list)
    hasher.update(edge_count.to_bytes(4, "little"))
    for vertex in range(min(number_of_nodes, 64)):
        hasher.update(len(adjacency_list[vertex]).to_bytes(2, "little"))
        for neighbor in adjacency_list[vertex][:8]:
            hasher.update(neighbor.to_bytes(2, "little"))
    return int.from_bytes(hasher.digest()[:8], "big")


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


def _dense_portfolio_worker(
    args: tuple[list[list[int]], float, int, float],
) -> list[int]:
    adjacency_list, budget_seconds, seed, deadline = args
    return solve_dense_complement(
        adjacency_list,
        budget_seconds,
        seed,
        deadline=deadline,
    )


def _run_portfolio_parallel(
    standard_tasks: list[tuple[int, list[list[int]], float, int, dict[str, float], float]],
    dense_tasks: list[tuple[list[list[int]], float, int, float]],
    outer_deadline: float,
) -> list[list[int]]:
    """Run portfolio workers with a hard wall-clock cap (avoids pool.map hangs)."""
    remaining = outer_deadline - time.perf_counter()
    if remaining <= 0:
        return []

    pool = ProcessPoolExecutor(max_workers=PORTFOLIO_WORKERS)
    futures: list = []
    try:
        for task in standard_tasks:
            futures.append(pool.submit(_portfolio_worker, task))
        for task in dense_tasks:
            futures.append(pool.submit(_dense_portfolio_worker, task))
        done, not_done = wait(futures, timeout=remaining)
        results: list[list[int]] = []
        for future in done:
            try:
                results.append(future.result())
            except Exception:
                continue
        for future in not_done:
            future.cancel()
        return results
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def fallback_maximum_clique(adjacency_list: list[list[int]]) -> list[int]:
    """Fast valid maximal clique used when the main search exceeds its budget."""
    if not adjacency_list:
        return []
    neighbor_sets = [set(neighbors) for neighbors in adjacency_list]
    seed_vertex = max(range(len(neighbor_sets)), key=lambda v: len(neighbor_sets[v]))
    return extend_to_maximal_clique(adjacency_list, [seed_vertex])


def _maybe_dense_complement(
    adjacency_list: list[list[int]],
    best: list[int],
    seed: int,
    outer_deadline: float,
) -> list[int]:
    """Run complement search on remaining budget and keep the larger clique."""
    remaining = outer_deadline - time.perf_counter()
    if remaining <= 0.15:
        return best
    candidate = solve_dense_complement(
        adjacency_list,
        remaining,
        seed,
        deadline=outer_deadline,
    )
    if len(candidate) > len(best):
        return candidate
    return best


def solve_maximum_clique(
    number_of_nodes: int,
    adjacency_list: list[list[int]],
    time_limit: float = 30.0,
    seed: int | None = None,
    problem_id: str | None = None,
) -> list[int]:
    """
    Find a large maximal clique within the validator time budget.

    Diversified portfolio of bitset heuristics, penalty local search, and
    coloring branch-and-bound. Leaves TIME_HEADROOM_SECONDS before timeout.

    When ``seed`` is omitted, RNG is seeded from ``problem_id`` (validator uuid)
    or a compact graph fingerprint so repeated queries are reproducible.
    """
    if number_of_nodes != len(adjacency_list):
        raise ValueError(
            f"number_of_nodes ({number_of_nodes}) does not match adjacency_list length ({len(adjacency_list)})"
        )

    if number_of_nodes == 0:
        return []

    seed = _resolve_seed(seed, problem_id, number_of_nodes, adjacency_list)

    budget = search_budget(time_limit)
    outer_start = time.perf_counter()
    outer_deadline = outer_start + budget
    cpu_count = os.cpu_count() or 1
    neighbor_sets = [set(neighbors) for neighbors in adjacency_list]
    complement = is_dense_graph(neighbor_sets)
    use_parallel = time_limit >= PORTFOLIO_PARALLEL_MIN_TIMEOUT and cpu_count >= 4

    best: list[int] = []
    worker_deadline = outer_deadline
    dense_deadline = outer_deadline
    if complement and use_parallel:
        dense_fraction = DENSE_POLISH_FRACTION if time_limit >= DENSE_PARALLEL_MIN_TIMEOUT else 0.35
        dense_slice = max(0.4, budget * dense_fraction)
        worker_deadline = outer_start + max(0.5, budget - dense_slice)

    if use_parallel:
        standard_tasks = [
            (
                number_of_nodes,
                adjacency_list,
                budget,
                seed + i * 7919,
                STRATEGIES[i % len(STRATEGIES)],
                worker_deadline,
            )
            for i in range(PORTFOLIO_WORKERS)
        ]
        results = _run_portfolio_parallel(standard_tasks, [], worker_deadline)
        if results:
            best = max(results, key=len)
        if complement and time.perf_counter() < dense_deadline:
            dense_candidate = solve_dense_complement(
                adjacency_list,
                dense_deadline - time.perf_counter(),
                seed + 2 * 7919,
                deadline=dense_deadline,
            )
            if len(dense_candidate) > len(best):
                best = dense_candidate
    else:
        if complement:
            run_budget = budget / PORTFOLIO_RUNS
            for run in range(PORTFOLIO_RUNS):
                if time.perf_counter() >= outer_deadline:
                    break
                if run == PORTFOLIO_RUNS - 1:
                    candidate = solve_dense_complement(
                        adjacency_list,
                        run_budget,
                        seed + run * 7919,
                        deadline=outer_deadline,
                    )
                else:
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
        else:
            run_budget = budget / PORTFOLIO_RUNS
            for run in range(PORTFOLIO_RUNS):
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
        core_numbers, degeneracy = core_and_degeneracy(neighbor_sets)
        neighbor_masks = (
            neighbor_sets_to_masks(neighbor_sets)
            if number_of_nodes <= MAX_BITSET_NODES
            else None
        )
        penalties = [0] * number_of_nodes
        rng = random.Random(seed + 424242)
        bb_seconds = max(0.5, budget * 0.2)
        polish_deadline = worker_deadline if complement else outer_deadline
        if complement and time.perf_counter() < polish_deadline:
            polish_deadline = min(
                polish_deadline,
                time.perf_counter() + max(0.15, (polish_deadline - time.perf_counter()) * 0.45),
            )
        elif complement and time_limit >= DENSE_PARALLEL_MIN_TIMEOUT:
            polish_deadline = time.perf_counter()
        best = _improve_until_deadline(
            best,
            neighbor_sets,
            adjacency_list,
            core_numbers,
            degeneracy,
            neighbor_masks,
            polish_deadline,
            bb_seconds,
            rng,
            penalties,
        )

    if complement and time.perf_counter() < outer_deadline:
        best = _maybe_dense_complement(
            adjacency_list,
            best,
            seed + SEED_ALT_OFFSET,
            outer_deadline,
        )

    if not best or not is_valid_maximum_clique(adjacency_list, best):
        best = fallback_maximum_clique(adjacency_list)

    return sorted(best)
