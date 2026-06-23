"""Graph preprocessing: k-core, degeneracy order, induced subgraphs."""


def k_core_numbers(neighbor_sets: list[set[int]]) -> list[int]:
    """Return the core number of each vertex."""
    n = len(neighbor_sets)
    if n == 0:
        return []

    degrees = [len(neighbor_sets[v]) for v in range(n)]
    core = degrees[:]
    remaining = [True] * n
    remaining_count = n

    while remaining_count > 0:
        min_vertex = min(
            (v for v in range(n) if remaining[v]),
            key=lambda v: core[v],
        )
        min_core = core[min_vertex]
        stack = [min_vertex]
        remaining[min_vertex] = False
        remaining_count -= 1

        while stack:
            vertex = stack.pop()
            for neighbor in neighbor_sets[vertex]:
                if not remaining[neighbor]:
                    continue
                if core[neighbor] > min_core:
                    core[neighbor] -= 1
                    if core[neighbor] == min_core:
                        stack.append(neighbor)
                        remaining[neighbor] = False
                        remaining_count -= 1

    return core


def degeneracy_order(neighbor_sets: list[set[int]]) -> list[int]:
    """Vertices in degeneracy order (minimum degree removal)."""
    n = len(neighbor_sets)
    if n == 0:
        return []

    degrees = [len(neighbor_sets[v]) for v in range(n)]
    removed = [False] * n
    order: list[int] = []

    for _ in range(n):
        vertex = min((v for v in range(n) if not removed[v]), key=lambda v: degrees[v])
        order.append(vertex)
        removed[vertex] = True
        for neighbor in neighbor_sets[vertex]:
            if not removed[neighbor]:
                degrees[neighbor] -= 1

    return order


def build_search_core(
    clique: list[int],
    neighbor_sets: list[set[int]],
    core_numbers: list[int],
) -> list[int]:
    """Vertices that can still host a clique extending the current best."""
    min_core = max(0, len(clique) - 1)
    vertices = set(clique)
    if clique:
        vertices |= set.intersection(*(neighbor_sets[v] for v in clique))
    return sorted(v for v in vertices if core_numbers[v] >= min_core)


def extract_subgraph(
    neighbor_sets: list[set[int]],
    vertices: list[int],
) -> tuple[list[set[int]], list[int]]:
    """Build induced subgraph; local index i maps to labels[i]."""
    labels = sorted(vertices)
    index_of = {vertex: index for index, vertex in enumerate(labels)}
    subgraph = [
        {index_of[neighbor] for neighbor in neighbor_sets[vertex] if neighbor in index_of}
        for vertex in labels
    ]
    return subgraph, labels


def map_clique_to_original(clique: list[int], labels: list[int]) -> list[int]:
    return sorted(labels[vertex] for vertex in clique)
