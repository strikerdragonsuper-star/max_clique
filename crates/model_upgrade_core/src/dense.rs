use std::collections::HashSet;
use std::time::Instant;

use rand::prelude::*;
use rand::rngs::StdRng;

use crate::bitsets::{mask_degree, neighbor_sets_to_masks, BitMask, MAX_BITSET_NODES};
use crate::graph_utils::core_and_degeneracy;
use crate::validation::{extend_to_maximal_clique, is_valid_maximum_clique};

pub const DENSE_DEGREE_RATIO: f64 = 0.70;

pub fn is_dense_graph(neighbor_sets: &[HashSet<usize>], threshold: f64) -> bool {
    let n = neighbor_sets.len();
    if n <= 1 {
        return false;
    }
    let avg_degree: f64 = neighbor_sets.iter().map(|s| s.len()).sum::<usize>() as f64 / n as f64;
    avg_degree / (n - 1) as f64 >= threshold
}

pub fn complement_neighbor_sets(neighbor_sets: &[HashSet<usize>]) -> Vec<HashSet<usize>> {
    let n = neighbor_sets.len();
    let universe: HashSet<usize> = (0..n).collect();
    (0..n)
        .map(|vertex| {
            let mut comp = universe.clone();
            comp.remove(&vertex);
            comp = comp
                .difference(&neighbor_sets[vertex])
                .copied()
                .collect();
            comp
        })
        .collect()
}

pub fn greedy_mis(comp_neighbors: &[HashSet<usize>], vertex_order: &[usize]) -> Vec<usize> {
    let mut mis: Vec<usize> = Vec::new();
    let mut blocked: HashSet<usize> = HashSet::new();
    for &vertex in vertex_order {
        if blocked.contains(&vertex) {
            continue;
        }
        mis.push(vertex);
        blocked.insert(vertex);
        blocked.extend(comp_neighbors[vertex].iter().copied());
    }
    mis
}

pub fn greedy_mis_grasp(
    comp_neighbors: &[HashSet<usize>],
    rng: &mut StdRng,
    start_vertex: Option<usize>,
    rcl_size: usize,
    comp_masks: Option<&[BitMask]>,
) -> Vec<usize> {
    let n = comp_neighbors.len();
    let use_masks = comp_masks.is_some() && n <= MAX_BITSET_NODES;

    let mut mis: Vec<usize> = Vec::new();
    if let Some(sv) = start_vertex {
        mis.push(sv);
    }

    if use_masks {
        let masks = comp_masks.unwrap();
        let mut blocked_mask = BitMask::empty();
        for &vertex in &mis {
            blocked_mask.set(vertex);
            blocked_mask.or_assign(&masks[vertex]);
        }

        loop {
            let mut available_mask = BitMask::all(n);
            available_mask.and_not_assign(&blocked_mask);
            if available_mask.is_empty() {
                break;
            }
            let candidates = available_mask.vertices();
            let mut ranked = candidates.clone();
            ranked.sort_by_key(|&v| mask_degree(masks[v].and(available_mask)));
            let top_len = rcl_size.min(ranked.len());
            let chosen = ranked[rng.random_range(0..top_len)];
            mis.push(chosen);
            blocked_mask.set(chosen);
            blocked_mask.or_assign(&masks[chosen]);
        }
        return mis;
    }

    let mut blocked: HashSet<usize> = HashSet::new();
    for &vertex in &mis {
        blocked.insert(vertex);
        blocked.extend(comp_neighbors[vertex].iter().copied());
    }

    loop {
        let available: HashSet<usize> = (0..n).filter(|v| !blocked.contains(v)).collect();
        if available.is_empty() {
            break;
        }
        let mut ranked: Vec<usize> = available.iter().copied().collect();
        ranked.sort_by_key(|&v| {
            comp_neighbors[v]
                .intersection(&available)
                .count()
        });
        let top_len = rcl_size.min(ranked.len());
        let chosen = ranked[rng.random_range(0..top_len)];
        mis.push(chosen);
        blocked.insert(chosen);
        blocked.extend(comp_neighbors[chosen].iter().copied());
    }
    mis
}

pub fn mis_random_restarts(
    comp_neighbors: &[HashSet<usize>],
    deadline: Instant,
    rng: &mut StdRng,
    comp_masks: Option<&[BitMask]>,
) -> Vec<usize> {
    let n = comp_neighbors.len();
    let comp_degrees: Vec<usize> = comp_neighbors.iter().map(|s| s.len()).collect();
    let mut best: Vec<usize> = Vec::new();

    let (_, degeneracy) = core_and_degeneracy(comp_neighbors);
    let static_orders: Vec<Vec<usize>> = vec![
        {
            let mut o: Vec<usize> = (0..n).collect();
            o.sort_by_key(|&v| comp_degrees[v]);
            o
        },
        {
            let mut o: Vec<usize> = (0..n).collect();
            o.sort_by_key(|&v| std::cmp::Reverse(comp_degrees[v]));
            o
        },
        {
            let mut o: Vec<usize> = (0..n).collect();
            o.sort_by(|&a, &b| (comp_degrees[a], a).cmp(&(comp_degrees[b], b)));
            o
        },
        (0..n).collect(),
        (0..n).rev().collect(),
        degeneracy.clone(),
        degeneracy.iter().rev().copied().collect(),
    ];

    for order in &static_orders {
        if Instant::now() >= deadline {
            break;
        }
        let candidate = greedy_mis(comp_neighbors, order);
        if candidate.len() > best.len() {
            best = candidate;
        }
    }

    let mut sparse_starts: Vec<usize> = (0..n).collect();
    sparse_starts.sort_by_key(|&v| comp_degrees[v]);
    sparse_starts.truncate(24.min(n));

    for &start in &sparse_starts {
        if Instant::now() >= deadline {
            break;
        }
        let candidate = greedy_mis_grasp(comp_neighbors, rng, Some(start), 5, comp_masks);
        if candidate.len() > best.len() {
            best = candidate;
        }
    }

    while Instant::now() < deadline {
        let candidate = if rng.random_bool(0.55) && !sparse_starts.is_empty() {
            let start = sparse_starts[rng.random_range(0..sparse_starts.len())];
            let rcl = rng.random_range(4..=8);
            greedy_mis_grasp(comp_neighbors, rng, Some(start), rcl, comp_masks)
        } else {
            let mut order: Vec<usize> = (0..n).collect();
            order.shuffle(rng);
            greedy_mis(comp_neighbors, &order)
        };
        if candidate.len() > best.len() {
            best = candidate;
        }
    }

    best
}

fn mis_compatible(comp_neighbors: &[HashSet<usize>], mis_set: &HashSet<usize>, vertex: usize) -> bool {
    mis_set.intersection(&comp_neighbors[vertex]).next().is_none()
}

pub fn mis_local_search(
    comp_neighbors: &[HashSet<usize>],
    mis: &[usize],
    deadline: Instant,
    rng: &mut StdRng,
) -> Vec<usize> {
    let mut best: Vec<usize> = mis.to_vec();
    let mut best_set: HashSet<usize> = best.iter().copied().collect();
    let n = comp_neighbors.len();

    while Instant::now() < deadline {
        if best.is_empty() {
            break;
        }

        let remove_vertices: Vec<usize> = if rng.random_bool(0.2) && best.len() >= 2 {
            let mut ranked = best.clone();
            ranked.sort_by_key(|&v| comp_neighbors[v].len());
            ranked[..2].to_vec()
        } else if rng.random_bool(0.75) {
            let v = *best
                .iter()
                .min_by_key(|&&v| comp_neighbors[v].len())
                .unwrap();
            vec![v]
        } else {
            vec![*best.choose(rng).unwrap()]
        };

        let reduced: HashSet<usize> = best_set
            .difference(&remove_vertices.iter().copied().collect())
            .copied()
            .collect();
        let candidates: Vec<usize> = (0..n)
            .filter(|&vertex| {
                !reduced.contains(&vertex) && mis_compatible(comp_neighbors, &reduced, vertex)
            })
            .collect();
        if candidates.is_empty() {
            continue;
        }

        let mut improved = false;

        if remove_vertices.len() == 1 {
            let add_vertex = *candidates
                .iter()
                .min_by_key(|&&v| comp_neighbors[v].len())
                .unwrap();
            let mut trial: Vec<usize> = reduced.iter().copied().collect();
            trial.push(add_vertex);
            trial.sort_unstable();
            if trial.len() >= best.len() {
                best = trial;
                best_set = best.iter().copied().collect();
                improved = true;
            }

            if !improved && best.len() >= 2 && rng.random_bool(0.4) {
                'outer: for (i, &u) in candidates.iter().enumerate() {
                    for &v in &candidates[i + 1..] {
                        if !comp_neighbors[u].contains(&v) {
                            let mut pair_trial: Vec<usize> = reduced.iter().copied().collect();
                            pair_trial.push(u);
                            pair_trial.push(v);
                            pair_trial.sort_unstable();
                            if pair_trial.len() > best.len() {
                                best = pair_trial;
                                best_set = best.iter().copied().collect();
                                improved = true;
                                break 'outer;
                            }
                        }
                    }
                }
            }
        }

        if !improved && remove_vertices.len() == 1 {
            let add_vertex = *candidates.choose(rng).unwrap();
            let mut trial: Vec<usize> = reduced.iter().copied().collect();
            trial.push(add_vertex);
            trial.sort_unstable();
            if trial.len() == best.len() {
                best = trial;
                best_set = best.iter().copied().collect();
            }
        }
    }

    best
}

pub fn mis_bitset_local_search(
    comp_masks: &[BitMask],
    n: usize,
    init_mis: &[usize],
    deadline: Instant,
    rng: &mut StdRng,
    penalties: &mut [i32],
) -> Vec<usize> {
    let mut mis: Vec<usize> = init_mis.to_vec();
    let mut mis_mask = BitMask::empty();
    for &vertex in &mis {
        mis_mask.set(vertex);
    }

    let mut best = mis.clone();
    let mut best_size = mis.len();
    let full_mask = BitMask::all(n);

    let mut avail = {
        let mut blocked = mis_mask;
        for &vertex in &mis {
            blocked.or_assign(&comp_masks[vertex]);
        }
        let mut a = full_mask;
        a.and_not_assign(&blocked);
        a
    };

    let mut check_counter = 0u32;

    loop {
        check_counter += 1;
        if check_counter >= 256 {
            check_counter = 0;
            if Instant::now() >= deadline {
                break;
            }
        }

        if !avail.is_empty() {
            let chosen = if rng.random_bool(0.65) {
                let mut best_vertex = 0usize;
                let mut best_score = i32::MAX;
                let mut first = true;
                for vertex in avail.iter_bits() {
                    let score =
                        (comp_masks[vertex].and(avail).count() as i32) - penalties[vertex];
                    if first || score < best_score {
                        best_score = score;
                        best_vertex = vertex;
                        first = false;
                    }
                }
                best_vertex
            } else {
                let candidates: Vec<usize> = avail.vertices();
                *candidates.choose(rng).unwrap()
            };

            mis.push(chosen);
            mis_mask.set(chosen);
            {
                let mut blocked = mis_mask;
                for &vertex in &mis {
                    blocked.or_assign(&comp_masks[vertex]);
                }
                avail = full_mask;
                avail.and_not_assign(&blocked);
            }

            if mis.len() > best_size {
                best = mis.clone();
                best_size = mis.len();
            }
            continue;
        }

        if mis.is_empty() {
            break;
        }

        let mut improved = false;
        for _ in 0..mis.len().min(4) {
            let pivot = *mis.choose(rng).unwrap();
            let reduced_mask = {
                let mut m = mis_mask;
                m.clear(pivot);
                m
            };
            let mut mask = full_mask;
            mask.and_not_assign(&reduced_mask);
            for &vertex in &mis {
                if vertex != pivot {
                    mask.and_not_assign(&comp_masks[vertex]);
                }
            }
            mask.and_not_assign(&reduced_mask);

            let mut pair: Option<(usize, usize)> = None;
            for first in mask.iter_bits() {
                let mut rest = mask;
                rest.and_not_assign(&comp_masks[first]);
                rest.clear(first);
                if let Some(second) = rest.lowest_bit() {
                    pair = Some((first, second));
                    break;
                }
            }

            if let Some((first, second)) = pair {
                mis.retain(|&v| v != pivot);
                mis_mask.clear(pivot);
                mis.push(first);
                mis.push(second);
                mis_mask.set(first);
                mis_mask.set(second);
                {
                    let mut blocked = mis_mask;
                    for &vertex in &mis {
                        blocked.or_assign(&comp_masks[vertex]);
                    }
                    avail = full_mask;
                    avail.and_not_assign(&blocked);
                }
                if mis.len() > best_size {
                    best = mis.clone();
                    best_size = mis.len();
                }
                improved = true;
                break;
            }
        }

        if !improved {
            for &vertex in &mis {
                penalties[vertex] += 1;
            }
            let drop = *mis
                .iter()
                .max_by(|&&a, &&b| {
                    penalties[a]
                        .cmp(&penalties[b])
                        .then_with(|| rng.random::<u32>().cmp(&rng.random()))
                })
                .unwrap();
            mis.retain(|&v| v != drop);
            mis_mask.clear(drop);
            {
                let mut blocked = mis_mask;
                for &vertex in &mis {
                    blocked.or_assign(&comp_masks[vertex]);
                }
                avail = full_mask;
                avail.and_not_assign(&blocked);
            }
        }
    }

    best
}

pub fn solve_dense_complement(
    adjacency_list: &[Vec<usize>],
    budget_seconds: f64,
    seed: u64,
    deadline: Option<Instant>,
) -> Vec<usize> {
    let neighbor_sets: Vec<HashSet<usize>> = adjacency_list
        .iter()
        .map(|n| n.iter().copied().collect())
        .collect();
    let n = neighbor_sets.len();
    if n == 0 {
        return vec![];
    }

    let comp_neighbors = complement_neighbor_sets(&neighbor_sets);
    let comp_masks = if n <= MAX_BITSET_NODES {
        Some(neighbor_sets_to_masks(
            &comp_neighbors
                .iter()
                .map(|s| {
                    let mut v: Vec<usize> = s.iter().copied().collect();
                    v.sort_unstable();
                    v
                })
                .collect::<Vec<_>>(),
        ))
    } else {
        None
    };
    let mut penalties = vec![0i32; n];
    let mut rng = StdRng::seed_from_u64(seed);

    let start = Instant::now();
    let deadline = match deadline {
        Some(d) => d.min(start + std::time::Duration::from_secs_f64(budget_seconds)),
        None => start + std::time::Duration::from_secs_f64(budget_seconds),
    };

    let heuristic_deadline = start
        + std::time::Duration::from_secs_f64(budget_seconds * 0.35f64.max(0.08));
    let local_deadline = start
        + std::time::Duration::from_secs_f64(budget_seconds * 0.65f64.max(0.15));

    let mis = mis_random_restarts(
        &comp_neighbors,
        heuristic_deadline.min(deadline),
        &mut rng,
        comp_masks.as_deref(),
    );
    let mut clique = extend_to_maximal_clique(adjacency_list, &mis);

    if Instant::now() < local_deadline {
        let mis = mis_local_search(
            &comp_neighbors,
            &clique,
            local_deadline.min(deadline),
            &mut rng,
        );
        clique = extend_to_maximal_clique(adjacency_list, &mis);
    }

    if comp_masks.is_some() && Instant::now() < deadline {
        let mis = mis_bitset_local_search(
            comp_masks.as_ref().unwrap(),
            n,
            &clique,
            deadline,
            &mut rng,
            &mut penalties,
        );
        clique = extend_to_maximal_clique(adjacency_list, &mis);
    }

    while Instant::now() < deadline {
        let burst = deadline.min(Instant::now() + std::time::Duration::from_secs_f64(0.08));
        let mis = mis_random_restarts(&comp_neighbors, burst, &mut rng, comp_masks.as_deref());
        let mut candidate = extend_to_maximal_clique(adjacency_list, &mis);
        let burst = deadline.min(Instant::now() + std::time::Duration::from_secs_f64(0.12));
        let mis = mis_local_search(&comp_neighbors, &candidate, burst, &mut rng);
        candidate = extend_to_maximal_clique(adjacency_list, &mis);
        if candidate.len() > clique.len() {
            clique = candidate;
        }
    }

    if !is_valid_maximum_clique(adjacency_list, &clique) {
        let seed_vertex = (0..n)
            .min_by_key(|&v| comp_neighbors[v].len())
            .unwrap();
        clique = extend_to_maximal_clique(adjacency_list, &[seed_vertex]);
    }

    clique.sort_unstable();
    clique
}
