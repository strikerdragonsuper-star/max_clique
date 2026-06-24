use std::collections::HashSet;
use std::time::{Duration, Instant};

use rand::rngs::StdRng;
use rand::SeedableRng;
use rayon::prelude::*;
use sha2::{Digest, Sha256};

use crate::bitsets::{neighbor_sets_to_masks, BitMask, MAX_BITSET_NODES};
use crate::branch_bound::branch_and_bound_max_clique;
use crate::dense::{exact_complement_clique, is_dense_graph, solve_dense_complement, DENSE_DEGREE_RATIO};
use crate::graph_utils::{
    adjacency_to_neighbor_sets, build_search_core_with_slack, core_and_degeneracy, expand_core_vertices,
    extract_subgraph, map_clique_to_original, neighbor_sets_to_adjacency,
};
use crate::heuristics::{bitset_local_search, local_search, merge_clique_candidates, random_restarts};
use crate::validation::{extend_to_maximal_clique, is_valid_maximum_clique};

pub const MIN_SEARCH_SECONDS: f64 = 0.5;
const CORE_SEARCH_THRESHOLD: usize = 320;
const PORTFOLIO_PARALLEL_MIN_TIMEOUT: f64 = 7.5;
const DENSE_PARALLEL_MIN_TIMEOUT: f64 = 10.0;
const DENSE_SHORT_TIMEOUT_FRACTION: f64 = 0.38;
const DENSE_POLISH_FRACTION: f64 = 0.40;
const SEED_ALT_OFFSET: u64 = 999_983;
const SEED_BB_OFFSET: u64 = 555_557;

#[derive(Clone, Copy)]
struct Strategy {
    heuristic: f64,
    local: f64,
    bb: f64,
}

const STRATEGIES: [Strategy; 5] = [
    Strategy {
        heuristic: 0.12,
        local: 0.20,
        bb: 0.45,
    },
    Strategy {
        heuristic: 0.15,
        local: 0.55,
        bb: 0.05,
    },
    Strategy {
        heuristic: 0.35,
        local: 0.30,
        bb: 0.15,
    },
    Strategy {
        heuristic: 0.10,
        local: 0.15,
        bb: 0.60,
    },
    Strategy {
        heuristic: 0.20,
        local: 0.65,
        bb: 0.03,
    },
];

/// Adaptive headroom before validator timeout (decode/network margin).
pub fn time_headroom(validator_timeout: f64) -> f64 {
    if validator_timeout >= 25.0 {
        0.50
    } else if validator_timeout >= 12.0 {
        0.65
    } else if validator_timeout >= 8.0 {
        0.75
    } else {
        0.85
    }
}

pub fn search_budget(validator_timeout: f64) -> f64 {
    (validator_timeout - time_headroom(validator_timeout)).max(MIN_SEARCH_SECONDS)
}

fn core_exact_threshold(time_limit: f64) -> usize {
    if time_limit >= 25.0 {
        320
    } else if time_limit >= 12.0 {
        300
    } else {
        280
    }
}

fn bb_seconds_cap(time_limit: f64, budget: f64, strategy_bb: f64) -> f64 {
    let base = (budget * strategy_bb).max(0.5);
    if time_limit >= 25.0 {
        base.max(6.0).min(14.0)
    } else if time_limit >= 12.0 {
        base.max(3.0).min(8.0)
    } else {
        base.min(3.5)
    }
}

fn adaptive_burst_seconds(remaining: f64) -> (f64, f64) {
    if remaining >= 8.0 {
        (0.15, 0.35)
    } else if remaining >= 3.0 {
        (0.10, 0.22)
    } else {
        (0.06, 0.12)
    }
}

fn portfolio_worker_count(time_limit: f64, cpu_count: usize) -> usize {
    if time_limit >= 25.0 {
        cpu_count.min(5).max(3)
    } else if time_limit >= 12.0 {
        cpu_count.min(4).max(3)
    } else {
        cpu_count.min(3).max(2)
    }
}

fn select_strategies(time_limit: f64, dense: bool, workers: usize) -> Vec<Strategy> {
    let mut picks = Vec::with_capacity(workers);
    if time_limit >= 25.0 {
        picks.extend([STRATEGIES[3], STRATEGIES[0], STRATEGIES[2], STRATEGIES[4], STRATEGIES[1]]);
    } else if dense {
        picks.extend([STRATEGIES[4], STRATEGIES[1], STRATEGIES[2], STRATEGIES[0], STRATEGIES[3]]);
    } else if time_limit >= 12.0 {
        picks.extend([STRATEGIES[0], STRATEGIES[1], STRATEGIES[3], STRATEGIES[2], STRATEGIES[4]]);
    } else {
        picks.extend([STRATEGIES[4], STRATEGIES[1], STRATEGIES[0], STRATEGIES[2], STRATEGIES[3]]);
    }
    picks.truncate(workers);
    picks
}

fn resolve_seed(
    seed: Option<u64>,
    problem_id: Option<&str>,
    number_of_nodes: usize,
    adjacency_list: &[Vec<usize>],
) -> u64 {
    if let Some(s) = seed {
        return s;
    }

    if let Some(pid) = problem_id {
        let digest = Sha256::digest(pid.trim().as_bytes());
        let bytes: [u8; 8] = digest[..8].try_into().unwrap();
        return u64::from_be_bytes(bytes) ^ number_of_nodes as u64;
    }

    let mut hasher = Sha256::new();
    hasher.update((number_of_nodes as u32).to_le_bytes());
    let edge_count: u32 = adjacency_list.iter().map(|row| row.len() as u32).sum();
    hasher.update(edge_count.to_le_bytes());
    for vertex in 0..number_of_nodes.min(64) {
        hasher.update((adjacency_list[vertex].len() as u16).to_le_bytes());
        for &neighbor in adjacency_list[vertex].iter().take(8) {
            hasher.update((neighbor as u16).to_le_bytes());
        }
    }
    let digest = hasher.finalize();
    let bytes: [u8; 8] = digest[..8].try_into().unwrap();
    u64::from_be_bytes(bytes)
}

fn local_search_best(
    neighbor_sets: &[HashSet<usize>],
    neighbor_masks: Option<&[BitMask]>,
    n: usize,
    clique: &[usize],
    deadline: Instant,
    rng: &mut StdRng,
    penalties: &mut [i32],
) -> Vec<usize> {
    if let Some(masks) = neighbor_masks {
        return bitset_local_search(masks, n, clique, deadline, rng, penalties, 8);
    }
    local_search(neighbor_sets, clique, deadline, rng)
}

fn run_bb_on_core(
    neighbor_sets: &[HashSet<usize>],
    adjacency_list: &[Vec<usize>],
    core_vertices: &[usize],
    lower_bound: &[usize],
    deadline: Instant,
    bb_seconds: f64,
    exact_threshold: usize,
) -> Vec<usize> {
    if core_vertices.len() <= lower_bound.len() || Instant::now() >= deadline {
        return lower_bound.to_vec();
    }

    let (subgraph, labels) = extract_subgraph(neighbor_sets, core_vertices);
    if subgraph.len() <= lower_bound.len() {
        return lower_bound.to_vec();
    }

    let sub_adj = neighbor_sets_to_adjacency(&subgraph);
    let sub_lb: Vec<usize> = lower_bound
        .iter()
        .filter_map(|&v| labels.iter().position(|&l| l == v))
        .collect();
    let mut sub_best = if sub_lb.is_empty() {
        lower_bound.to_vec()
    } else {
        sub_lb.clone()
    };

    if subgraph.len() <= exact_threshold {
        let bb_deadline =
            deadline.min(Instant::now() + Duration::from_secs_f64(bb_seconds.max(0.15)));
        let exact = branch_and_bound_max_clique(&subgraph, &sub_best, bb_deadline);
        if exact.len() > sub_best.len() {
            sub_best = exact;
        }
    }

    sub_best = extend_to_maximal_clique(&sub_adj, &sub_best);
    let mut mapped = map_clique_to_original(&sub_best, &labels);
    mapped = extend_to_maximal_clique(adjacency_list, &mapped);
    if mapped.len() > lower_bound.len() {
        mapped
    } else {
        lower_bound.to_vec()
    }
}

fn refine_on_core(
    best: &[usize],
    neighbor_sets: &[HashSet<usize>],
    adjacency_list: &[Vec<usize>],
    core_numbers: &[usize],
    neighbor_masks: Option<&[BitMask]>,
    deadline: Instant,
    bb_seconds: f64,
    exact_threshold: usize,
    rng: &mut StdRng,
) -> Vec<usize> {
    if Instant::now() >= deadline {
        return best.to_vec();
    }

    let mut core_vertices = build_search_core_with_slack(best, neighbor_sets, core_numbers, 2);
    if core_vertices.len() <= best.len() {
        return best.to_vec();
    }

    if core_vertices.len() > CORE_SEARCH_THRESHOLD {
        core_vertices = expand_core_vertices(
            &core_vertices,
            neighbor_sets,
            core_numbers,
            best.len(),
            CORE_SEARCH_THRESHOLD,
            24,
        );
    }

    let (subgraph, labels) = extract_subgraph(neighbor_sets, &core_vertices);
    if subgraph.len() <= best.len() {
        return best.to_vec();
    }

    let sub_adj = neighbor_sets_to_adjacency(&subgraph);
    let sub_n = subgraph.len();
    let sub_masks = if sub_n <= MAX_BITSET_NODES {
        Some(neighbor_sets_to_masks(
            &subgraph
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
    let (_, sub_degeneracy) = core_and_degeneracy(&subgraph);
    let mut sub_penalties = vec![0i32; sub_n];

    let remaining = (deadline - Instant::now()).as_secs_f64().max(0.0);
    let search_deadline =
        Instant::now() + Duration::from_secs_f64(remaining.min(remaining * 0.45).max(0.15));

    let mut sub_best = random_restarts(
        &subgraph,
        search_deadline,
        rng,
        Some(&sub_degeneracy),
        sub_masks.as_deref(),
    );
    sub_best = extend_to_maximal_clique(&sub_adj, &sub_best);

    if Instant::now() < search_deadline {
        sub_best = local_search_best(
            &subgraph,
            sub_masks.as_deref(),
            sub_n,
            &sub_best,
            search_deadline,
            rng,
            &mut sub_penalties,
        );
        sub_best = extend_to_maximal_clique(&sub_adj, &sub_best);
    }

    let mut mapped = map_clique_to_original(&sub_best, &labels);
    mapped = extend_to_maximal_clique(adjacency_list, &mapped);
    let mut best_out = if mapped.len() > best.len() { mapped } else { best.to_vec() };

    best_out = run_bb_on_core(
        neighbor_sets,
        adjacency_list,
        &core_vertices,
        &best_out,
        deadline,
        bb_seconds,
        exact_threshold,
    );

    if best_out.len() == best.len() {
        let expanded = expand_core_vertices(
            &core_vertices,
            neighbor_sets,
            core_numbers,
            best.len(),
            CORE_SEARCH_THRESHOLD + 20,
            20,
        );
        if expanded.len() > core_vertices.len() {
            best_out = run_bb_on_core(
                neighbor_sets,
                adjacency_list,
                &expanded,
                &best_out,
                deadline,
                bb_seconds * 0.6,
                exact_threshold,
            );
        }
    }

    best_out
}

fn improve_until_deadline(
    best: &[usize],
    neighbor_sets: &[HashSet<usize>],
    adjacency_list: &[Vec<usize>],
    core_numbers: &[usize],
    degeneracy: &[usize],
    neighbor_masks: Option<&[BitMask]>,
    deadline: Instant,
    bb_seconds: f64,
    exact_threshold: usize,
    rng: &mut StdRng,
    penalties: &mut [i32],
) -> Vec<usize> {
    let n = neighbor_sets.len();
    let mut best = best.to_vec();
    while Instant::now() < deadline {
        let remaining = (deadline - Instant::now()).as_secs_f64();
        let (burst_restart, burst_local) = adaptive_burst_seconds(remaining);
        let burst_deadline =
            deadline.min(Instant::now() + Duration::from_secs_f64(burst_restart));
        let mut candidate = random_restarts(
            neighbor_sets,
            burst_deadline,
            rng,
            Some(degeneracy),
            neighbor_masks,
        );
        candidate = extend_to_maximal_clique(adjacency_list, &candidate);

        let burst_deadline =
            deadline.min(Instant::now() + Duration::from_secs_f64(burst_local));
        candidate = local_search_best(
            neighbor_sets,
            neighbor_masks,
            n,
            &candidate,
            burst_deadline,
            rng,
            penalties,
        );
        candidate = extend_to_maximal_clique(adjacency_list, &candidate);

        if candidate.len() > best.len() {
            best = candidate;
            best = refine_on_core(
                &best,
                neighbor_sets,
                adjacency_list,
                core_numbers,
                neighbor_masks,
                deadline,
                bb_seconds * 0.5,
                exact_threshold,
                rng,
            );
        }
    }
    best
}

fn solve_single(
    number_of_nodes: usize,
    adjacency_list: &[Vec<usize>],
    budget_seconds: f64,
    time_limit: f64,
    seed: u64,
    strategy: Strategy,
    deadline: Option<Instant>,
) -> Vec<usize> {
    let mut rng = StdRng::seed_from_u64(seed);
    let neighbor_sets = adjacency_to_neighbor_sets(adjacency_list);
    let (core_numbers, degeneracy) = core_and_degeneracy(&neighbor_sets);
    let exact_threshold = core_exact_threshold(time_limit);
    let neighbor_masks = if number_of_nodes <= MAX_BITSET_NODES {
        Some(neighbor_sets_to_masks(
            &neighbor_sets
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
    let mut penalties = vec![0i32; number_of_nodes];

    let start = Instant::now();
    let deadline = match deadline {
        Some(d) => d.min(start + Duration::from_secs_f64(budget_seconds)),
        None => start + Duration::from_secs_f64(budget_seconds),
    };

    let heuristic_deadline =
        start + Duration::from_secs_f64((budget_seconds * strategy.heuristic).max(0.05));
    let local_deadline =
        start + Duration::from_secs_f64((budget_seconds * strategy.local).max(0.1));
    let bb_seconds = bb_seconds_cap(time_limit, budget_seconds, strategy.bb);

    let mut best = random_restarts(
        &neighbor_sets,
        heuristic_deadline.min(deadline),
        &mut rng,
        Some(&degeneracy),
        neighbor_masks.as_deref(),
    );
    best = extend_to_maximal_clique(adjacency_list, &best);

    best = local_search_best(
        &neighbor_sets,
        neighbor_masks.as_deref(),
        number_of_nodes,
        &best,
        local_deadline.min(deadline),
        &mut rng,
        &mut penalties,
    );
    best = extend_to_maximal_clique(adjacency_list, &best);

    best = refine_on_core(
        &best,
        &neighbor_sets,
        adjacency_list,
        &core_numbers,
        neighbor_masks.as_deref(),
        deadline,
        bb_seconds,
        exact_threshold,
        &mut rng,
    );

    if number_of_nodes <= exact_threshold && Instant::now() < deadline {
        let bb_deadline = deadline.min(Instant::now() + Duration::from_secs_f64(bb_seconds));
        let exact = branch_and_bound_max_clique(&neighbor_sets, &best, bb_deadline);
        if exact.len() > best.len() {
            best = exact;
        }
        best = extend_to_maximal_clique(adjacency_list, &best);
    }

    best = improve_until_deadline(
        &best,
        &neighbor_sets,
        adjacency_list,
        &core_numbers,
        &degeneracy,
        neighbor_masks.as_deref(),
        deadline,
        bb_seconds,
        exact_threshold,
        &mut rng,
        &mut penalties,
    );

    if !is_valid_maximum_clique(adjacency_list, &best) {
        let seed_vertex = (0..number_of_nodes)
            .max_by_key(|&v| neighbor_sets[v].len())
            .unwrap();
        best = extend_to_maximal_clique(adjacency_list, &[seed_vertex]);
    }

    best.sort_unstable();
    best
}

struct PortfolioTask {
    number_of_nodes: usize,
    adjacency_list: Vec<Vec<usize>>,
    budget_seconds: f64,
    time_limit: f64,
    seed: u64,
    strategy: Strategy,
    deadline: Instant,
}

pub fn fallback_maximum_clique(adjacency_list: &[Vec<usize>]) -> Vec<usize> {
    if adjacency_list.is_empty() {
        return vec![];
    }
    let neighbor_sets = adjacency_to_neighbor_sets(adjacency_list);
    let seed_vertex = (0..neighbor_sets.len())
        .max_by_key(|&v| neighbor_sets[v].len())
        .unwrap();
    extend_to_maximal_clique(adjacency_list, &[seed_vertex])
}

fn maybe_dense_complement(
    adjacency_list: &[Vec<usize>],
    best: &[usize],
    seed: u64,
    outer_deadline: Instant,
) -> Vec<usize> {
    let remaining = (outer_deadline - Instant::now()).as_secs_f64();
    if remaining <= 0.15 {
        return best.to_vec();
    }
    let candidate = solve_dense_complement(adjacency_list, remaining, seed, Some(outer_deadline));
    if candidate.len() > best.len() {
        candidate
    } else {
        best.to_vec()
    }
}

fn final_leftover_polish(
    best: &[usize],
    neighbor_sets: &[HashSet<usize>],
    adjacency_list: &[Vec<usize>],
    time_limit: f64,
    complement: bool,
    outer_deadline: Instant,
    _seed: u64,
) -> Vec<usize> {
    let remaining = (outer_deadline - Instant::now()).as_secs_f64();
    if remaining < 0.20 {
        return best.to_vec();
    }

    let exact_threshold = core_exact_threshold(time_limit);
    let bb_seconds = (remaining * 0.55).min(4.0).max(0.25);
    let bb_deadline = outer_deadline.min(Instant::now() + Duration::from_secs_f64(bb_seconds));
    let (core_numbers, _) = core_and_degeneracy(neighbor_sets);

    let mut core_vertices = build_search_core_with_slack(best, neighbor_sets, &core_numbers, 2);
    if core_vertices.len() > CORE_SEARCH_THRESHOLD {
        core_vertices = expand_core_vertices(
            &core_vertices,
            neighbor_sets,
            &core_numbers,
            best.len(),
            CORE_SEARCH_THRESHOLD,
            16,
        );
    }

    let mut polished = run_bb_on_core(
        neighbor_sets,
        adjacency_list,
        &core_vertices,
        best,
        bb_deadline,
        bb_seconds,
        exact_threshold,
    );

    if complement {
        let dense_deadline = outer_deadline;
        let dense = exact_complement_clique(adjacency_list, &polished, dense_deadline);
        if dense.len() > polished.len() {
            polished = dense;
        }
    }

    if polished.len() > best.len() {
        polished
    } else {
        best.to_vec()
    }
}

pub fn solve_maximum_clique(
    number_of_nodes: usize,
    adjacency_list: &[Vec<usize>],
    time_limit: f64,
    seed: Option<u64>,
    problem_id: Option<&str>,
) -> Result<Vec<usize>, String> {
    if number_of_nodes != adjacency_list.len() {
        return Err(format!(
            "number_of_nodes ({number_of_nodes}) does not match adjacency_list length ({})",
            adjacency_list.len()
        ));
    }

    if number_of_nodes == 0 {
        return Ok(vec![]);
    }

    let seed = resolve_seed(seed, problem_id, number_of_nodes, adjacency_list);
    let budget = search_budget(time_limit);
    let outer_start = Instant::now();
    let outer_deadline = outer_start + Duration::from_secs_f64(budget);
    let cpu_count = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1);
    let neighbor_sets = adjacency_to_neighbor_sets(adjacency_list);
    let complement = is_dense_graph(&neighbor_sets, DENSE_DEGREE_RATIO);
    let use_parallel = time_limit >= PORTFOLIO_PARALLEL_MIN_TIMEOUT && cpu_count >= 4;
    let workers = portfolio_worker_count(time_limit, cpu_count);
    let strategies = select_strategies(time_limit, complement, workers);

    let mut best: Vec<usize> = Vec::new();
    let dense_deadline = outer_deadline;
    let mut worker_deadline = outer_deadline;
    if complement && use_parallel {
        let dense_fraction = if time_limit >= DENSE_PARALLEL_MIN_TIMEOUT {
            DENSE_POLISH_FRACTION
        } else {
            DENSE_SHORT_TIMEOUT_FRACTION
        };
        let dense_slice = (budget * dense_fraction).max(0.4);
        worker_deadline = outer_start + Duration::from_secs_f64((budget - dense_slice).max(0.5));
    }

    if use_parallel {
        let standard_tasks: Vec<PortfolioTask> = (0..workers)
            .map(|i| PortfolioTask {
                number_of_nodes,
                adjacency_list: adjacency_list.to_vec(),
                budget_seconds: budget,
                time_limit,
                seed: seed.wrapping_add((i as u64).wrapping_mul(7919)),
                strategy: strategies[i],
                deadline: worker_deadline,
            })
            .collect();

        let results: Vec<Vec<usize>> = standard_tasks
            .par_iter()
            .filter_map(|task| {
                if Instant::now() >= task.deadline {
                    return None;
                }
                Some(solve_single(
                    task.number_of_nodes,
                    &task.adjacency_list,
                    task.budget_seconds,
                    task.time_limit,
                    task.seed,
                    task.strategy,
                    Some(task.deadline),
                ))
            })
            .collect();

        if !results.is_empty() {
            best = merge_clique_candidates(&neighbor_sets, &results);
            if let Some(largest) = results.iter().max_by_key(|r| r.len()) {
                if largest.len() > best.len() {
                    best = largest.clone();
                }
            }
        }

        if complement && Instant::now() < dense_deadline {
            let remaining = (dense_deadline - Instant::now()).as_secs_f64();
            let dense_candidate = solve_dense_complement(
                adjacency_list,
                remaining,
                seed.wrapping_add(2 * 7919),
                Some(dense_deadline),
            );
            if dense_candidate.len() > best.len() {
                best = dense_candidate;
            }
        }
    } else {
        let run_budget = budget / strategies.len() as f64;
        for (run, &strategy) in strategies.iter().enumerate() {
            if Instant::now() >= outer_deadline {
                break;
            }
            let candidate = if complement && run == strategies.len() - 1 {
                solve_dense_complement(
                    adjacency_list,
                    run_budget,
                    seed.wrapping_add((run as u64).wrapping_mul(7919)),
                    Some(outer_deadline),
                )
            } else {
                solve_single(
                    number_of_nodes,
                    adjacency_list,
                    run_budget,
                    time_limit,
                    seed.wrapping_add((run as u64).wrapping_mul(7919)),
                    strategy,
                    Some(outer_deadline),
                )
            };
            if candidate.len() > best.len() {
                best = candidate;
            }
        }
    }

    if !best.is_empty() && Instant::now() < outer_deadline {
        let (core_numbers, degeneracy) = core_and_degeneracy(&neighbor_sets);
        let neighbor_masks = if number_of_nodes <= MAX_BITSET_NODES {
            Some(neighbor_sets_to_masks(
                &neighbor_sets
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
        let mut penalties = vec![0i32; number_of_nodes];
        let mut rng = StdRng::seed_from_u64(seed.wrapping_add(424242));
        let bb_seconds = bb_seconds_cap(time_limit, budget, 0.20);
        let exact_threshold = core_exact_threshold(time_limit);
        let mut polish_deadline = if complement {
            worker_deadline
        } else {
            outer_deadline
        };
        if complement && Instant::now() < polish_deadline {
            let remaining = (polish_deadline - Instant::now()).as_secs_f64();
            polish_deadline = polish_deadline.min(
                Instant::now() + Duration::from_secs_f64(remaining.max(0.15) * 0.50),
            );
        } else if complement && time_limit >= DENSE_PARALLEL_MIN_TIMEOUT {
            polish_deadline = Instant::now();
        }
        best = improve_until_deadline(
            &best,
            &neighbor_sets,
            adjacency_list,
            &core_numbers,
            &degeneracy,
            neighbor_masks.as_deref(),
            polish_deadline,
            bb_seconds,
            exact_threshold,
            &mut rng,
            &mut penalties,
        );
    }

    if complement && Instant::now() < outer_deadline {
        best = maybe_dense_complement(
            adjacency_list,
            &best,
            seed.wrapping_add(SEED_ALT_OFFSET),
            outer_deadline,
        );
    }

    if Instant::now() < outer_deadline {
        best = final_leftover_polish(
            &best,
            &neighbor_sets,
            adjacency_list,
            time_limit,
            complement,
            outer_deadline,
            seed.wrapping_add(SEED_BB_OFFSET),
        );
    }

    if best.is_empty() || !is_valid_maximum_clique(adjacency_list, &best) {
        best = fallback_maximum_clique(adjacency_list);
    }

    best.sort_unstable();
    Ok(best)
}
