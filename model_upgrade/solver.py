import random
import time

from model_upgrade.branch_bound import branch_and_bound_max_clique
from model_upgrade.components import (
    extract_subgraph,
    find_connected_components,
    map_clique_to_original,
)
from model_upgrade.heuristics import local_search, random_restarts
from model_upgrade.validation import extend_to_maximal_clique, is_valid_maximum_clique

# Reserve a fraction of the validator timeout for decode/encode/network overhead.
TIME_BUDGET_FRACTION = 0.92
HEURISTIC_FRACTION = 0.25
BRANCH_BOUND_NODE_THRESHOLD = 420
MIN_COMPONENT_TIME = 0.05


def solve_maximum_clique(
    number_of_nodes: int,
    adjacency_list: list[list[int]],
    time_limit: float = 30.0,
    seed: int | None = None,
) -> list[int]:
    """
    Find a large maximal clique within the validator time budget.

    Splits the graph into connected components first, solves each component
    with a proportional time share, and returns the best clique overall.
    """
    if number_of_nodes != len(adjacency_list):
        raise ValueError(
            f"number_of_nodes ({number_of_nodes}) does not match adjacency_list length ({len(adjacency_list)})"
        )

    if number_of_nodes == 0:
        return []

    rng = random.Random(seed)
    start = time.perf_counter()
    deadline = start + max(0.1, time_limit * TIME_BUDGET_FRACTION)

    components = find_connected_components(adjacency_list)
    best: list[int] = []

    for index, component in enumerate(components):
        if time.perf_counter() >= deadline:
            break

        remaining = components[index:]
        remaining_nodes = sum(len(comp) for comp in remaining)
        time_left = max(0.0, deadline - time.perf_counter())
        if remaining_nodes == 0 or time_left <= 0:
            break

        component_time = max(
            MIN_COMPONENT_TIME,
            time_left * len(component) / remaining_nodes,
        )

        if len(component) == 1:
            candidate = component
        else:
            subgraph, labels = extract_subgraph(adjacency_list, component)
            sub_seed = rng.randint(0, 2**31 - 1)
            sub_clique = _solve_component(
                len(subgraph),
                subgraph,
                time_limit=component_time,
                seed=sub_seed,
                rng=rng,
            )
            candidate = map_clique_to_original(sub_clique, labels)

        candidate = extend_to_maximal_clique(adjacency_list, candidate)
        if len(candidate) > len(best):
            best = candidate

    if not best and components:
        largest = components[0]
        best = [max(largest, key=lambda v: len(adjacency_list[v]))]
        best = extend_to_maximal_clique(adjacency_list, best)

    if not is_valid_maximum_clique(adjacency_list, best):
        neighbor_sets = [set(neighbors) for neighbors in adjacency_list]
        best = [max(range(number_of_nodes), key=lambda v: len(neighbor_sets[v]))]
        best = extend_to_maximal_clique(adjacency_list, best)

    return sorted(best)


def _solve_component(
    number_of_nodes: int,
    adjacency_list: list[list[int]],
    time_limit: float,
    seed: int,
    rng: random.Random,
) -> list[int]:
    """Run the heuristic + branch-and-bound pipeline on one connected component."""
    if number_of_nodes == 0:
        return []

    neighbor_sets = [set(neighbors) for neighbors in adjacency_list]
    start = time.perf_counter()
    deadline = start + max(0.05, time_limit * TIME_BUDGET_FRACTION)
    heuristic_deadline = start + max(0.02, time_limit * HEURISTIC_FRACTION)

    best = random_restarts(neighbor_sets, heuristic_deadline, rng)
    best = extend_to_maximal_clique(adjacency_list, best)

    best = local_search(neighbor_sets, best, deadline, rng)
    best = extend_to_maximal_clique(adjacency_list, best)

    if number_of_nodes <= BRANCH_BOUND_NODE_THRESHOLD and time.perf_counter() < deadline:
        exact = branch_and_bound_max_clique(neighbor_sets, best, deadline)
        if len(exact) > len(best):
            best = exact
        best = extend_to_maximal_clique(adjacency_list, best)
        if number_of_nodes <= 64:
            return sorted(best)

    stagnation = 0
    while time.perf_counter() < deadline:
        burst_deadline = min(deadline, time.perf_counter() + 0.05)
        candidate = random_restarts(neighbor_sets, burst_deadline, rng)
        candidate = extend_to_maximal_clique(adjacency_list, candidate)
        if len(candidate) > len(best):
            best = candidate
            stagnation = 0
        else:
            stagnation += 1
            if stagnation >= 20:
                break

    if not is_valid_maximum_clique(adjacency_list, best):
        best = [max(range(number_of_nodes), key=lambda v: len(neighbor_sets[v]))]
        best = extend_to_maximal_clique(adjacency_list, best)

    return sorted(best)
