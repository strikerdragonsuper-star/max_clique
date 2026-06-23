import random
import time

from model_upgrade.bitsets import (
    MAX_BITSET_NODES,
    mask_degree,
    mask_intersection,
    mask_vertices,
    neighbor_sets_to_masks,
)


def _iter_bits(mask: int):
    while mask:
        low = mask & -mask
        yield low.bit_length() - 1
        mask &= ~low


def greedy_clique(
    neighbor_sets: list[set[int]],
    vertex_order: list[int],
) -> list[int]:
    """Build a clique by scanning vertices in the given order."""
    clique: list[int] = []
    clique_set: set[int] = set()
    for vertex in vertex_order:
        if not clique_set or clique_set.issubset(neighbor_sets[vertex]):
            clique.append(vertex)
            clique_set.add(vertex)
    return clique


def greedy_clique_grasp(
    neighbor_sets: list[set[int]],
    rng: random.Random,
    start_vertex: int | None = None,
    rcl_size: int = 4,
    neighbor_masks: list[int] | None = None,
) -> list[int]:
    """GRASP: repeatedly pick from the top-degree restricted candidate list."""
    n = len(neighbor_sets)
    use_masks = neighbor_masks is not None and n <= MAX_BITSET_NODES

    clique: list[int] = []
    if start_vertex is not None:
        clique = [start_vertex]

    if use_masks:
        assert neighbor_masks is not None
        if not clique:
            candidates_mask = (1 << n) - 1
        else:
            candidates_mask = mask_intersection(*[neighbor_masks[v] for v in clique])
            for v in clique:
                candidates_mask &= ~(1 << v)

        while candidates_mask:
            candidates = mask_vertices(candidates_mask)
            degrees = [(v, mask_degree(neighbor_masks[v])) for v in candidates]
            degrees.sort(key=lambda item: item[1], reverse=True)
            top = [v for v, _ in degrees[: min(rcl_size, len(degrees))]]
            chosen = rng.choice(top)
            clique.append(chosen)
            candidates_mask &= neighbor_masks[chosen]
            candidates_mask &= ~(1 << chosen)
        return clique

    clique_set = set(clique)
    if not clique_set:
        candidates = set(range(n))
    else:
        candidates = set.intersection(*(neighbor_sets[v] for v in clique_set))

    while candidates:
        ranked = sorted(candidates, key=lambda v: len(neighbor_sets[v]), reverse=True)
        top = ranked[: min(rcl_size, len(ranked))]
        chosen = rng.choice(top)
        clique.append(chosen)
        clique_set.add(chosen)
        candidates = candidates & neighbor_sets[chosen]
        candidates -= clique_set

    return clique


def random_restarts(
    neighbor_sets: list[set[int]],
    deadline: float,
    rng: random.Random,
    degeneracy: list[int] | None = None,
    neighbor_masks: list[int] | None = None,
) -> list[int]:
    """Run greedy construction with varied vertex orderings until the deadline."""
    n = len(neighbor_sets)
    degrees = [len(neighbors) for neighbors in neighbor_sets]
    best: list[int] = []

    static_orders = [
        sorted(range(n), key=lambda v: degrees[v], reverse=True),
        sorted(range(n), key=lambda v: degrees[v]),
        sorted(range(n), key=lambda v: (degrees[v], v), reverse=True),
        sorted(range(n), key=lambda v: (-degrees[v], v)),
        list(range(n)),
        list(reversed(range(n))),
    ]
    if degeneracy:
        static_orders.append(list(degeneracy))
        static_orders.append(list(reversed(degeneracy)))

    for order in static_orders:
        if time.perf_counter() >= deadline:
            break
        candidate = greedy_clique(neighbor_sets, order)
        if len(candidate) > len(best):
            best = candidate

    top_starts = sorted(range(n), key=lambda v: degrees[v], reverse=True)[: min(16, n)]
    for start in top_starts:
        if time.perf_counter() >= deadline:
            break
        candidate = greedy_clique_grasp(
            neighbor_sets,
            rng,
            start_vertex=start,
            neighbor_masks=neighbor_masks,
        )
        if len(candidate) > len(best):
            best = candidate

    while time.perf_counter() < deadline:
        if rng.random() < 0.5 and top_starts:
            start = rng.choice(top_starts)
            candidate = greedy_clique_grasp(
                neighbor_sets,
                rng,
                start_vertex=start,
                rcl_size=rng.randint(3, 6),
                neighbor_masks=neighbor_masks,
            )
        else:
            order = list(range(n))
            rng.shuffle(order)
            candidate = greedy_clique(neighbor_sets, order)
        if len(candidate) > len(best):
            best = candidate

    return best


def _swap_candidates(
    neighbor_sets: list[set[int]],
    base_set: set[int],
    n: int,
) -> list[int]:
    return [
        vertex
        for vertex in range(n)
        if vertex not in base_set and base_set.issubset(neighbor_sets[vertex])
    ]


def local_search(
    neighbor_sets: list[set[int]],
    clique: list[int],
    deadline: float,
    rng: random.Random,
) -> list[int]:
    """1-swap, (1,2)-add, (2,3)-add, and plateau moves."""
    best = list(clique)
    best_set = set(best)
    n = len(neighbor_sets)

    while time.perf_counter() < deadline:
        if not best:
            break

        remove_vertices: list[int]
        if rng.random() < 0.2 and len(best) >= 2:
            ranked = sorted(best, key=lambda v: len(neighbor_sets[v]))
            remove_vertices = ranked[:2]
        elif rng.random() < 0.75:
            remove_vertices = [min(best, key=lambda v: len(neighbor_sets[v]))]
        else:
            remove_vertices = [rng.choice(best)]

        reduced = best_set - set(remove_vertices)
        candidates = _swap_candidates(neighbor_sets, reduced, n)
        if not candidates:
            continue

        improved = False

        if len(remove_vertices) == 1:
            add_vertex = max(candidates, key=lambda v: len(neighbor_sets[v]))
            trial = sorted(reduced | {add_vertex})
            if len(trial) >= len(best):
                best = trial
                best_set = set(best)
                improved = True

            if not improved and len(best) >= 2 and rng.random() < 0.35:
                for i, u in enumerate(candidates):
                    for v in candidates[i + 1 :]:
                        if v in neighbor_sets[u]:
                            pair_trial = sorted(reduced | {u, v})
                            if len(pair_trial) > len(best):
                                best = pair_trial
                                best_set = set(best)
                                improved = True
                                break
                    if improved:
                        break

        if not improved and len(remove_vertices) == 2 and len(candidates) >= 3:
            for i, u in enumerate(candidates):
                for j in range(i + 1, len(candidates)):
                    v = candidates[j]
                    if v not in neighbor_sets[u]:
                        continue
                    for w in candidates[j + 1 :]:
                        if w in neighbor_sets[u] and w in neighbor_sets[v]:
                            triple = sorted(reduced | {u, v, w})
                            if len(triple) > len(best):
                                best = triple
                                best_set = set(best)
                                improved = True
                                break
                    if improved:
                        break
                if improved:
                    break

        if not improved and len(remove_vertices) == 1:
            add_vertex = rng.choice(candidates)
            trial = sorted(reduced | {add_vertex})
            if len(trial) == len(best):
                best = trial
                best_set = set(best)

    return best


def bitset_local_search(
    masks: list[int],
    n: int,
    init_clique: list[int],
    deadline: float,
    rng: random.Random,
    penalties: list[int] | None = None,
    restart_no_improve: int = 0,
) -> list[int]:
    """
    Incremental bitmask local search with penalty-guided escape (DLS-MC style).

    Grows the clique greedily; when maximal, attempts a (1,2)-swap, otherwise
    penalizes current members and drops one to diversify.
    """
    clique = list(init_clique)
    clique_mask = 0
    for vertex in clique:
        clique_mask |= 1 << vertex

    best = list(clique)
    best_size = len(clique)
    if penalties is None:
        penalties = [0] * n

    full_mask = (1 << n) - 1

    def add_set() -> int:
        mask = full_mask
        for vertex in clique:
            mask &= masks[vertex]
        return mask

    add_mask = add_set()
    no_improve = 0
    check_counter = 0

    while True:
        check_counter += 1
        if check_counter >= 256:
            check_counter = 0
            if time.perf_counter() >= deadline:
                break

        if add_mask:
            if rng.random() < 0.7:
                chosen = -1
                chosen_score = None
                for vertex in _iter_bits(add_mask):
                    score = (masks[vertex] & add_mask).bit_count() - penalties[vertex]
                    if chosen_score is None or score > chosen_score:
                        chosen_score = score
                        chosen = vertex
            else:
                candidates = list(_iter_bits(add_mask))
                chosen = rng.choice(candidates)

            clique.append(chosen)
            clique_mask |= 1 << chosen
            add_mask &= masks[chosen]

            if len(clique) > best_size:
                best = list(clique)
                best_size = len(clique)
                no_improve = 0
            continue

        no_improve += 1
        improved = False

        if clique:
            for _ in range(min(len(clique), 4)):
                pivot = rng.choice(clique)
                mask = full_mask
                for vertex in clique:
                    if vertex != pivot:
                        mask &= masks[vertex]
                mask &= ~clique_mask

                pair = None
                for first in _iter_bits(mask):
                    rest = masks[first] & mask & ~(1 << first)
                    if rest:
                        second = (rest & -rest).bit_length() - 1
                        pair = (first, second)
                        break

                if pair is not None:
                    first, second = pair
                    clique.remove(pivot)
                    clique_mask &= ~(1 << pivot)
                    clique.extend((first, second))
                    clique_mask |= (1 << first) | (1 << second)
                    add_mask = add_set()
                    if len(clique) > best_size:
                        best = list(clique)
                        best_size = len(clique)
                        no_improve = 0
                    improved = True
                    break

        if not improved and clique:
            for vertex in clique:
                penalties[vertex] += 1
            drop = max(clique, key=lambda u: (penalties[u], rng.random()))
            clique.remove(drop)
            clique_mask &= ~(1 << drop)
            add_mask = add_set()

        if restart_no_improve and no_improve >= restart_no_improve:
            clique = list(best)
            clique_mask = 0
            for vertex in clique:
                clique_mask |= 1 << vertex
            add_mask = add_set()
            no_improve = 0

    return best
