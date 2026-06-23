"""Connected-component decomposition for graph preprocessing."""


def find_connected_components(adjacency_list: list[list[int]]) -> list[list[int]]:
    """Return vertex sets for each connected component, largest first."""
    n = len(adjacency_list)
    visited = [False] * n
    components: list[list[int]] = []

    for start in range(n):
        if visited[start]:
            continue

        stack = [start]
        component: list[int] = []
        visited[start] = True

        while stack:
            vertex = stack.pop()
            component.append(vertex)
            for neighbor in adjacency_list[vertex]:
                if not visited[neighbor]:
                    visited[neighbor] = True
                    stack.append(neighbor)

        components.append(sorted(component))

    components.sort(key=len, reverse=True)
    return components


def extract_subgraph(
    adjacency_list: list[list[int]],
    vertices: list[int],
) -> tuple[list[list[int]], list[int]]:
    """
    Build an induced subgraph on `vertices`.

    Returns (subgraph_adjacency_list, original_vertex_labels) where
    subgraph index i maps to original_vertex_labels[i].
    """
    labels = sorted(vertices)
    index_of = {vertex: index for index, vertex in enumerate(labels)}
    subgraph = [[] for _ in range(len(labels))]

    for new_index, old_vertex in enumerate(labels):
        neighbors = [
            index_of[neighbor]
            for neighbor in adjacency_list[old_vertex]
            if neighbor in index_of
        ]
        subgraph[new_index] = sorted(neighbors)

    return subgraph, labels


def map_clique_to_original(clique: list[int], original_labels: list[int]) -> list[int]:
    return sorted(original_labels[vertex] for vertex in clique)
