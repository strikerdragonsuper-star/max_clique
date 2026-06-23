import time

from model_upgrade.bitsets import neighbor_sets_to_masks

# Check the wall clock every this many expand() calls (perf_counter is not free).
_TIME_CHECK_INTERVAL = 2048


def branch_and_bound_max_clique(
    neighbor_sets: list[set[int]],
    lower_bound: list[int],
    deadline: float,
) -> list[int]:
    """
    Time-limited bitset branch-and-bound (Tomita MCS-style).

    Operates on integer bitmasks with a greedy-coloring upper bound, branching
    vertices in non-increasing color order so the first prune cuts the tail.
    """
    n = len(neighbor_sets)
    if n == 0:
        return []

    masks = neighbor_sets_to_masks(neighbor_sets)
    best = list(lower_bound)
    best_size = len(best)

    candidate_mask = 0
    for v in range(n):
        if len(neighbor_sets[v]) >= best_size - 1:
            candidate_mask |= 1 << v

    counter = [0]
    timed_out = [False]

    def expand(r_list: list[int], r_size: int, candidates: int) -> None:
        if timed_out[0]:
            return

        counter[0] += 1
        if counter[0] >= _TIME_CHECK_INTERVAL:
            counter[0] = 0
            if time.perf_counter() >= deadline:
                timed_out[0] = True
                return

        # Greedy coloring of `candidates`; produce vertices in color order.
        order: list[int] = []
        color_of: list[int] = []
        uncolored = candidates
        color = 0
        while uncolored:
            color += 1
            available = uncolored
            while available:
                low = available & -available
                vertex = low.bit_length() - 1
                order.append(vertex)
                color_of.append(color)
                uncolored &= ~low
                available &= ~low
                available &= ~masks[vertex]

        nonlocal best, best_size
        for i in range(len(order) - 1, -1, -1):
            if timed_out[0]:
                return
            if r_size + color_of[i] <= best_size:
                return

            vertex = order[i]
            new_size = r_size + 1
            if new_size > best_size:
                best = r_list + [vertex]
                best_size = new_size

            next_candidates = candidates & masks[vertex]
            if next_candidates:
                expand(r_list + [vertex], new_size, next_candidates)

            candidates &= ~(1 << vertex)

    expand([], 0, candidate_mask)
    return best
