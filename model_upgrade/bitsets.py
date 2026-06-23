"""Bitmask adjacency for fast set intersections (n <= 1024)."""

MAX_BITSET_NODES = 1024


def neighbor_sets_to_masks(neighbor_sets: list[set[int]]) -> list[int]:
    masks: list[int] = []
    for neighbors in neighbor_sets:
        mask = 0
        for vertex in neighbors:
            mask |= 1 << vertex
        masks.append(mask)
    return masks


def mask_neighbors(mask: int, vertex: int) -> bool:
    return bool(mask & (1 << vertex))


def mask_intersection(*masks: int) -> int:
    result = masks[0]
    for mask in masks[1:]:
        result &= mask
    return result


def mask_vertices(mask: int) -> list[int]:
    vertices: list[int] = []
    bit = 0
    while mask:
        if mask & 1:
            vertices.append(bit)
        mask >>= 1
        bit += 1
    return vertices


def mask_degree(mask: int) -> int:
    return mask.bit_count()
