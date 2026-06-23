import time


def _greedy_color_order(
    vertices: list[int],
    neighbor_sets: list[set[int]],
) -> tuple[list[int], int]:
    """Greedy coloring; returns vertices sorted by color and the color count."""
    if not vertices:
        return [], 0

    vertex_set = set(vertices)
    ordered_by_degree = sorted(
        vertices,
        key=lambda v: len(neighbor_sets[v] & vertex_set),
        reverse=True,
    )
    color_of: dict[int, int] = {}
    max_color = 0

    for vertex in ordered_by_degree:
        used = {color_of[neighbor] for neighbor in neighbor_sets[vertex] if neighbor in color_of}
        color = 0
        while color in used:
            color += 1
        color_of[vertex] = color
        max_color = max(max_color, color)

    sorted_vertices = sorted(vertices, key=lambda v: color_of[v], reverse=True)
    return sorted_vertices, max_color + 1


def branch_and_bound_max_clique(
    neighbor_sets: list[set[int]],
    lower_bound: list[int],
    deadline: float,
) -> list[int]:
    """
    Time-limited branch-and-bound with greedy-coloring upper bound (Tomita-style).
    """
    n = len(neighbor_sets)
    if n == 0:
        return []

    best = list(lower_bound)
    best_size = len(best)

    candidates = [v for v in range(n) if len(neighbor_sets[v]) >= best_size - 1]
    if len(candidates) > 280:
        candidates = sorted(
            candidates,
            key=lambda v: len(neighbor_sets[v]),
            reverse=True,
        )[:280]

    def search(remaining: list[int], current: list[int], current_set: set[int]) -> None:
        nonlocal best, best_size

        if time.perf_counter() >= deadline:
            return

        if not remaining:
            if len(current) > best_size:
                best = list(current)
                best_size = len(current)
            return

        ordered, color_bound = _greedy_color_order(remaining, neighbor_sets)
        if len(current) + color_bound <= best_size:
            return

        vertex = ordered[0]
        rest = [v for v in ordered if v != vertex]

        if not current_set or current_set.issubset(neighbor_sets[vertex]):
            new_current = current + [vertex]
            new_set = current_set | {vertex}
            new_remaining = [u for u in rest if u in neighbor_sets[vertex]]
            search(new_remaining, new_current, new_set)

        search(rest, current, current_set)

    search(candidates, [], set())
    return best
