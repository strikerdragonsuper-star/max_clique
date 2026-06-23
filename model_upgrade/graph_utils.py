"""Graph preprocessing: k-core, degeneracy order, induced subgraphs."""


def core_and_degeneracy(
    neighbor_sets: list[set[int]],
) -> tuple[list[int], list[int]]:
    """
    Batagelj-Zaversnik O(n+m) core decomposition.

    Returns (core_numbers, degeneracy_order). The removal order is the
    degeneracy order; the core number is each vertex's value at removal.
    """
    n = len(neighbor_sets)
    if n == 0:
        return [], []

    degrees = [len(neighbor_sets[v]) for v in range(n)]
    max_degree = max(degrees)

    # Bin-sort vertices by current degree.
    bin_start = [0] * (max_degree + 2)
    for v in range(n):
        bin_start[degrees[v]] += 1
    start = 0
    for d in range(max_degree + 1):
        count = bin_start[d]
        bin_start[d] = start
        start += count

    position = [0] * n
    vertices = [0] * n
    for v in range(n):
        position[v] = bin_start[degrees[v]]
        vertices[position[v]] = v
        bin_start[degrees[v]] += 1

    # Restore bin starts.
    for d in range(max_degree + 1, 0, -1):
        bin_start[d] = bin_start[d - 1]
    bin_start[0] = 0

    core = degrees[:]
    order: list[int] = []

    for i in range(n):
        vertex = vertices[i]
        order.append(vertex)
        for neighbor in neighbor_sets[vertex]:
            if core[neighbor] > core[vertex]:
                deg_n = core[neighbor]
                pos_n = position[neighbor]
                pos_first = bin_start[deg_n]
                first = vertices[pos_first]
                if neighbor != first:
                    position[neighbor] = pos_first
                    vertices[pos_n] = first
                    position[first] = pos_n
                    vertices[pos_first] = neighbor
                bin_start[deg_n] += 1
                core[neighbor] -= 1

    return core, order


def k_core_numbers(neighbor_sets: list[set[int]]) -> list[int]:
    """Return the core number of each vertex."""
    core, _ = core_and_degeneracy(neighbor_sets)
    return core


def degeneracy_order(neighbor_sets: list[set[int]]) -> list[int]:
    """Vertices in degeneracy order (minimum-degree removal)."""
    _, order = core_and_degeneracy(neighbor_sets)
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
