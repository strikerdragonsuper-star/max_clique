import time


def branch_and_bound_max_clique(
    neighbor_sets: list[set[int]],
    lower_bound: list[int],
    deadline: float,
) -> list[int]:
    """
    Time-limited branch-and-bound search for the maximum clique.

    Uses a degree-based vertex ordering and simple upper-bound pruning.
    """
    n = len(neighbor_sets)
    if n == 0:
        return []

    order = sorted(range(n), key=lambda v: len(neighbor_sets[v]), reverse=True)
    best = list(lower_bound)
    best_size = len(best)

    def upper_bound(candidate_size: int, remaining_count: int) -> int:
        return candidate_size + remaining_count

    def search(index: int, current: list[int], current_set: set[int]) -> None:
        nonlocal best, best_size

        if time.perf_counter() >= deadline:
            return

        remaining = n - index
        if upper_bound(len(current), remaining) <= best_size:
            return

        if index == n:
            if len(current) > best_size:
                best = list(current)
                best_size = len(current)
            return

        vertex = order[index]

        # Branch: include vertex if it connects to the current clique.
        if not current_set or current_set.issubset(neighbor_sets[vertex]):
            current.append(vertex)
            current_set.add(vertex)
            search(index + 1, current, current_set)
            current.pop()
            current_set.remove(vertex)

        # Branch: exclude vertex.
        search(index + 1, current, current_set)

    search(0, [], set())
    return best
