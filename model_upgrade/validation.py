"""Clique validation helpers matching validator scoring rules."""


def extend_to_maximal_clique(adjacency_list: list[list[int]], clique: list[int]) -> list[int]:
    """Greedily extend a clique until no vertex can be added."""
    clique_set = set(clique)
    n = len(adjacency_list)
    changed = True
    while changed:
        changed = False
        for vertex in range(n):
            if vertex in clique_set:
                continue
            if clique_set.issubset(adjacency_list[vertex]):
                clique_set.add(vertex)
                changed = True
                break
    return sorted(clique_set)


def is_valid_maximum_clique(adjacency_list: list[list[int]], nodes: list[int]) -> bool:
    """Return True if nodes form a valid maximal clique."""
    node_set = set(nodes)
    if len(node_set) == 0:
        return False
    if len(node_set) != len(nodes):
        return False
    if not node_set.issubset(range(len(adjacency_list))):
        return False

    node_list = list(node_set)
    for i in range(len(node_list)):
        for j in range(i + 1, len(node_list)):
            if node_list[j] not in adjacency_list[node_list[i]]:
                return False

    for candidate in set(range(len(adjacency_list))) - node_set:
        if node_set.issubset(adjacency_list[candidate]):
            return False

    return True
