use std::collections::HashSet;
use std::time::Instant;

use rand::prelude::*;
use rand::rngs::StdRng;

use crate::bitsets::{mask_degree, mask_intersection, BitMask, MAX_BITSET_NODES};

pub fn greedy_clique(neighbor_sets: &[HashSet<usize>], vertex_order: &[usize]) -> Vec<usize> {
    let mut clique: Vec<usize> = Vec::new();
    let mut clique_set: HashSet<usize> = HashSet::new();
    for &vertex in vertex_order {
        if clique_set.is_empty() || clique_set.is_subset(&neighbor_sets[vertex]) {
            clique.push(vertex);
            clique_set.insert(vertex);
        }
    }
    clique
}

pub fn greedy_clique_grasp(
    neighbor_sets: &[HashSet<usize>],
    rng: &mut StdRng,
    start_vertex: Option<usize>,
    rcl_size: usize,
    neighbor_masks: Option<&[BitMask]>,
) -> Vec<usize> {
    let n = neighbor_sets.len();
    let use_masks = neighbor_masks.is_some() && n <= MAX_BITSET_NODES;

    let mut clique: Vec<usize> = Vec::new();
    if let Some(sv) = start_vertex {
        clique.push(sv);
    }

    if use_masks {
        let masks = neighbor_masks.unwrap();
        let mut candidates_mask = if clique.is_empty() {
            BitMask::all(n)
        } else {
            let refs: Vec<BitMask> = clique.iter().map(|&v| masks[v]).collect();
            let mut cm = mask_intersection(&refs);
            for &v in &clique {
                cm.clear(v);
            }
            cm
        };

        while !candidates_mask.is_empty() {
            let candidates = candidates_mask.vertices();
            let mut degrees: Vec<(usize, u32)> = candidates
                .iter()
                .map(|&v| (v, mask_degree(masks[v])))
                .collect();
            degrees.sort_by(|a, b| b.1.cmp(&a.1));
            let top_len = rcl_size.min(degrees.len());
            let top: Vec<usize> = degrees[..top_len].iter().map(|(v, _)| *v).collect();
            let chosen = *top.choose(rng).unwrap();
            clique.push(chosen);
            candidates_mask.and_assign(&masks[chosen]);
            candidates_mask.clear(chosen);
        }
        return clique;
    }

    let mut clique_set: HashSet<usize> = clique.iter().copied().collect();
    let mut candidates: HashSet<usize> = if clique_set.is_empty() {
        (0..n).collect()
    } else {
        clique
            .iter()
            .map(|&v| neighbor_sets[v].clone())
            .reduce(|a, b| a.intersection(&b).copied().collect())
            .unwrap_or_default()
    };

    while !candidates.is_empty() {
        let mut ranked: Vec<usize> = candidates.iter().copied().collect();
        ranked.sort_by_key(|&v| std::cmp::Reverse(neighbor_sets[v].len()));
        let top_len = rcl_size.min(ranked.len());
        let chosen = ranked[rng.random_range(0..top_len)];
        clique.push(chosen);
        clique_set.insert(chosen);
        candidates = candidates
            .intersection(&neighbor_sets[chosen])
            .copied()
            .collect();
        candidates = candidates
            .difference(&clique_set)
            .copied()
            .collect();
    }

    clique
}

pub fn random_restarts(
    neighbor_sets: &[HashSet<usize>],
    deadline: Instant,
    rng: &mut StdRng,
    degeneracy: Option<&[usize]>,
    neighbor_masks: Option<&[BitMask]>,
) -> Vec<usize> {
    let n = neighbor_sets.len();
    let degrees: Vec<usize> = neighbor_sets.iter().map(|s| s.len()).collect();
    let mut best: Vec<usize> = Vec::new();

    let mut static_orders: Vec<Vec<usize>> = vec![
        {
            let mut o: Vec<usize> = (0..n).collect();
            o.sort_by_key(|&v| std::cmp::Reverse(degrees[v]));
            o
        },
        {
            let mut o: Vec<usize> = (0..n).collect();
            o.sort_by_key(|&v| degrees[v]);
            o
        },
        {
            let mut o: Vec<usize> = (0..n).collect();
            o.sort_by(|&a, &b| (degrees[b], b).cmp(&(degrees[a], a)));
            o
        },
        {
            let mut o: Vec<usize> = (0..n).collect();
            o.sort_by(|&a, &b| (degrees[a], a).cmp(&(degrees[b], b)));
            o
        },
        (0..n).collect(),
        (0..n).rev().collect(),
    ];

    if let Some(degen) = degeneracy {
        static_orders.push(degen.to_vec());
        static_orders.push(degen.iter().rev().copied().collect());
    }

    for order in &static_orders {
        if Instant::now() >= deadline {
            break;
        }
        let candidate = greedy_clique(neighbor_sets, order);
        if candidate.len() > best.len() {
            best = candidate;
        }
    }

    let mut top_starts: Vec<usize> = (0..n).collect();
    top_starts.sort_by_key(|&v| std::cmp::Reverse(degrees[v]));
    top_starts.truncate(16.min(n));

    for &start in &top_starts {
        if Instant::now() >= deadline {
            break;
        }
        let candidate = greedy_clique_grasp(
            neighbor_sets,
            rng,
            Some(start),
            4,
            neighbor_masks,
        );
        if candidate.len() > best.len() {
            best = candidate;
        }
    }

    while Instant::now() < deadline {
        let candidate = if rng.random_bool(0.5) && !top_starts.is_empty() {
            let start = *top_starts.choose(rng).unwrap();
            let rcl = rng.random_range(3..=6);
            greedy_clique_grasp(neighbor_sets, rng, Some(start), rcl, neighbor_masks)
        } else {
            let mut order: Vec<usize> = (0..n).collect();
            order.shuffle(rng);
            greedy_clique(neighbor_sets, &order)
        };
        if candidate.len() > best.len() {
            best = candidate;
        }
    }

    best
}

fn swap_candidates(
    neighbor_sets: &[HashSet<usize>],
    base_set: &HashSet<usize>,
    n: usize,
) -> Vec<usize> {
    (0..n)
        .filter(|&vertex| {
            !base_set.contains(&vertex) && base_set.is_subset(&neighbor_sets[vertex])
        })
        .collect()
}

pub fn local_search(
    neighbor_sets: &[HashSet<usize>],
    clique: &[usize],
    deadline: Instant,
    rng: &mut StdRng,
) -> Vec<usize> {
    let mut best: Vec<usize> = clique.to_vec();
    let mut best_set: HashSet<usize> = best.iter().copied().collect();
    let n = neighbor_sets.len();

    while Instant::now() < deadline {
        if best.is_empty() {
            break;
        }

        let remove_vertices: Vec<usize> = if rng.random_bool(0.2) && best.len() >= 2 {
            let mut ranked = best.clone();
            ranked.sort_by_key(|&v| neighbor_sets[v].len());
            ranked[..2].to_vec()
        } else if rng.random_bool(0.75) {
            let v = *best
                .iter()
                .min_by_key(|&&v| neighbor_sets[v].len())
                .unwrap();
            vec![v]
        } else {
            vec![*best.choose(rng).unwrap()]
        };

        let reduced: HashSet<usize> = best_set
            .difference(&remove_vertices.iter().copied().collect())
            .copied()
            .collect();
        let candidates = swap_candidates(neighbor_sets, &reduced, n);
        if candidates.is_empty() {
            continue;
        }

        let mut improved = false;

        if remove_vertices.len() == 1 {
            let add_vertex = *candidates
                .iter()
                .max_by_key(|&&v| neighbor_sets[v].len())
                .unwrap();
            let mut trial: Vec<usize> = reduced.iter().copied().collect();
            trial.push(add_vertex);
            trial.sort_unstable();
            if trial.len() >= best.len() {
                best = trial;
                best_set = best.iter().copied().collect();
                improved = true;
            }

            if !improved && best.len() >= 2 && rng.random_bool(0.35) {
                'outer: for (i, &u) in candidates.iter().enumerate() {
                    for &v in &candidates[i + 1..] {
                        if neighbor_sets[u].contains(&v) {
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

        if !improved && remove_vertices.len() == 2 && candidates.len() >= 3 {
            'outer2: for (i, &u) in candidates.iter().enumerate() {
                for (j, &v) in candidates[i + 1..].iter().enumerate() {
                    let j = i + 1 + j;
                    if !neighbor_sets[u].contains(&v) {
                        continue;
                    }
                    for &w in &candidates[j + 1..] {
                        if neighbor_sets[u].contains(&w) && neighbor_sets[v].contains(&w) {
                            let mut triple: Vec<usize> = reduced.iter().copied().collect();
                            triple.extend([u, v, w]);
                            triple.sort_unstable();
                            if triple.len() > best.len() {
                                best = triple;
                                best_set = best.iter().copied().collect();
                                improved = true;
                                break 'outer2;
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

pub fn bitset_local_search(
    masks: &[BitMask],
    n: usize,
    init_clique: &[usize],
    deadline: Instant,
    rng: &mut StdRng,
    penalties: &mut [i32],
    restart_no_improve: usize,
) -> Vec<usize> {
    let mut clique: Vec<usize> = init_clique.to_vec();
    let mut clique_mask = BitMask::empty();
    for &vertex in &clique {
        clique_mask.set(vertex);
    }

    let mut best = clique.clone();
    let mut best_size = clique.len();
    let full_mask = BitMask::all(n);

    let mut add_mask = {
        let mut mask = full_mask;
        for &vertex in &clique {
            mask.and_assign(&masks[vertex]);
        }
        mask
    };

    let mut no_improve = 0usize;
    let mut check_counter = 0u32;

    loop {
        check_counter += 1;
        if check_counter >= 256 {
            check_counter = 0;
            if Instant::now() >= deadline {
                break;
            }
        }

        if !add_mask.is_empty() {
            let chosen = if rng.random_bool(0.7) {
                let mut best_vertex = 0usize;
                let mut best_score = i32::MIN;
                let mut first = true;
                for vertex in add_mask.iter_bits() {
                    let score = (masks[vertex].and(add_mask).count() as i32) - penalties[vertex];
                    if first || score > best_score {
                        best_score = score;
                        best_vertex = vertex;
                        first = false;
                    }
                }
                best_vertex
            } else {
                let candidates: Vec<usize> = add_mask.vertices();
                *candidates.choose(rng).unwrap()
            };

            clique.push(chosen);
            clique_mask.set(chosen);
            add_mask.and_assign(&masks[chosen]);

            if clique.len() > best_size {
                best = clique.clone();
                best_size = clique.len();
                no_improve = 0;
            }
            continue;
        }

        no_improve += 1;
        let mut improved = false;

        if !clique.is_empty() {
            for _ in 0..clique.len().min(4) {
                let pivot = *clique.choose(rng).unwrap();
                let mut mask = full_mask;
                for &vertex in &clique {
                    if vertex != pivot {
                        mask.and_assign(&masks[vertex]);
                    }
                }
                mask.and_not_assign(&clique_mask);

                let mut pair: Option<(usize, usize)> = None;
                for first in mask.iter_bits() {
                    let mut rest = masks[first].and(mask);
                    rest.clear(first);
                    if let Some(second) = rest.lowest_bit() {
                        pair = Some((first, second));
                        break;
                    }
                }

                if let Some((first, second)) = pair {
                    clique.retain(|&v| v != pivot);
                    clique_mask.clear(pivot);
                    clique.push(first);
                    clique.push(second);
                    clique_mask.set(first);
                    clique_mask.set(second);
                    add_mask = {
                        let mut m = full_mask;
                        for &vertex in &clique {
                            m.and_assign(&masks[vertex]);
                        }
                        m
                    };
                    if clique.len() > best_size {
                        best = clique.clone();
                        best_size = clique.len();
                        no_improve = 0;
                    }
                    improved = true;
                    break;
                }
            }
        }

        if !improved && !clique.is_empty() {
            for &vertex in &clique {
                penalties[vertex] += 1;
            }
            let drop = *clique
                .iter()
                .max_by(|&&a, &&b| {
                    penalties[a]
                        .cmp(&penalties[b])
                        .then_with(|| rng.random::<u32>().cmp(&rng.random()))
                })
                .unwrap();
            clique.retain(|&v| v != drop);
            clique_mask.clear(drop);
            add_mask = {
                let mut m = full_mask;
                for &vertex in &clique {
                    m.and_assign(&masks[vertex]);
                }
                m
            };
        }

        if restart_no_improve > 0 && no_improve >= restart_no_improve {
            clique = best.clone();
            clique_mask = BitMask::empty();
            for &vertex in &clique {
                clique_mask.set(vertex);
            }
            add_mask = {
                let mut m = full_mask;
                for &vertex in &clique {
                    m.and_assign(&masks[vertex]);
                }
                m
            };
            no_improve = 0;
        }
    }

    best
}
