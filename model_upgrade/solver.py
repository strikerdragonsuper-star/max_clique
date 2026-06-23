import random
import time

from model_upgrade.branch_bound import branch_and_bound_max_clique
from model_upgrade.heuristics import local_search, random_restarts
from model_upgrade.validation import extend_to_maximal_clique, is_valid_maximum_clique

# Reserve a fraction of the validator timeout for decode/encode/network overhead.
TIME_BUDGET_FRACTION = 0.92
HEURISTIC_FRACTION = 0.25
LOCAL_FRACTION = 0.33
BRANCH_BOUND_NODE_THRESHOLD = 420


def solve_maximum_clique(
    number_of_nodes: int,
    adjacency_list: list[list[int]],
    time_limit: float = 30.0,
    seed: int | None = None,
) -> list[int]:
    """
    Find a large maximal clique within the validator time budget.

    Strategy:
    1. Fast multi-start greedy heuristics
    2. Local search improvements
    3. Branch-and-bound on medium graphs when time remains
    4. Final maximality extension and validation
    """
    if number_of_nodes != len(adjacency_list):
        raise ValueError(
            f"number_of_nodes ({number_of_nodes}) does not match adjacency_list length ({len(adjacency_list)})"
        )

    if number_of_nodes == 0:
        return []

    if seed is None:
        seed = int(time.perf_counter() * 1_000_000)

    rng = random.Random(seed)
    neighbor_sets = [set(neighbors) for neighbors in adjacency_list]
    start = time.perf_counter()
    deadline = start + max(0.1, time_limit * TIME_BUDGET_FRACTION)
    heuristic_deadline = start + max(0.05, time_limit * HEURISTIC_FRACTION)
    local_deadline = start + max(0.1, time_limit * LOCAL_FRACTION)

    best = random_restarts(neighbor_sets, heuristic_deadline, rng)
    best = extend_to_maximal_clique(adjacency_list, best)

    best = local_search(neighbor_sets, best, local_deadline, rng)
    best = extend_to_maximal_clique(adjacency_list, best)

    if number_of_nodes <= BRANCH_BOUND_NODE_THRESHOLD and time.perf_counter() < deadline:
        exact = branch_and_bound_max_clique(neighbor_sets, best, deadline)
        if len(exact) > len(best):
            best = exact
        best = extend_to_maximal_clique(adjacency_list, best)
        if number_of_nodes <= 64:
            return sorted(best)

#    stagnation = 0
    while time.perf_counter() < deadline:
        burst_deadline = min(deadline, time.perf_counter() + 0.05)
        candidate = random_restarts(neighbor_sets, burst_deadline, rng)
        candidate = extend_to_maximal_clique(adjacency_list, candidate)
        burst_deadline = min(deadline, time.perf_counter() + 0.05)
        candidate = local_search(neighbor_sets, candidate, burst_deadline, rng)
        candidate = extend_to_maximal_clique(adjacency_list, candidate)
        if len(candidate) > len(best):
            best = candidate
#            stagnation = 0
#        else:
#            stagnation += 1
#            if stagnation >= 20:
#                break

    if not is_valid_maximum_clique(adjacency_list, best):
        best = [max(range(number_of_nodes), key=lambda v: len(neighbor_sets[v]))]
        best = extend_to_maximal_clique(adjacency_list, best)

    return sorted(best)
