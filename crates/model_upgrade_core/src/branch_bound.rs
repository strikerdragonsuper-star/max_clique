use std::collections::HashSet;
use std::time::Instant;

use crate::bitsets::{neighbor_sets_to_masks, BitMask};

const TIME_CHECK_INTERVAL: u64 = 2048;

pub fn branch_and_bound_max_clique(
    neighbor_sets: &[HashSet<usize>],
    lower_bound: &[usize],
    deadline: Instant,
) -> Vec<usize> {
    let n = neighbor_sets.len();
    if n == 0 {
        return vec![];
    }

    let masks = neighbor_sets_to_masks(
        &neighbor_sets
            .iter()
            .map(|s| {
                let mut v: Vec<usize> = s.iter().copied().collect();
                v.sort_unstable();
                v
            })
            .collect::<Vec<_>>(),
    );

    let mut best = lower_bound.to_vec();
    let mut best_size = best.len();

    let mut candidate_mask = BitMask::empty();
    for v in 0..n {
        if neighbor_sets[v].len() >= best_size.saturating_sub(1) {
            candidate_mask.set(v);
        }
    }

    struct SearchState<'a> {
        masks: &'a [BitMask],
        deadline: Instant,
        best: &'a mut Vec<usize>,
        best_size: &'a mut usize,
        counter: u64,
        timed_out: bool,
    }

    fn expand(state: &mut SearchState<'_>, r_list: &mut Vec<usize>, r_size: usize, mut candidates: BitMask) {
        if state.timed_out {
            return;
        }

        state.counter += 1;
        if state.counter >= TIME_CHECK_INTERVAL {
            state.counter = 0;
            if Instant::now() >= state.deadline {
                state.timed_out = true;
                return;
            }
        }

        let mut order: Vec<usize> = Vec::new();
        let mut color_of: Vec<usize> = Vec::new();
        let mut uncolored = candidates;
        let mut color = 0usize;

        while !uncolored.is_empty() {
            color += 1;
            let mut available = uncolored;
            while !available.is_empty() {
                let vertex = available.lowest_bit().unwrap();
                order.push(vertex);
                color_of.push(color);
                uncolored.clear(vertex);
                available.clear(vertex);
                available.and_not_assign(&state.masks[vertex]);
            }
        }

        for i in (0..order.len()).rev() {
            if state.timed_out {
                return;
            }
            if r_size + color_of[i] <= *state.best_size {
                return;
            }

            let vertex = order[i];
            let new_size = r_size + 1;
            if new_size > *state.best_size {
                *state.best = r_list.iter().copied().chain(std::iter::once(vertex)).collect();
                *state.best_size = new_size;
            }

            let next_candidates = candidates.and(state.masks[vertex]);
            if !next_candidates.is_empty() {
                r_list.push(vertex);
                expand(state, r_list, new_size, next_candidates);
                r_list.pop();
            }

            candidates.clear(vertex);
        }
    }

    let mut r_list = Vec::new();
    let mut state = SearchState {
        masks: &masks,
        deadline,
        best: &mut best,
        best_size: &mut best_size,
        counter: 0,
        timed_out: false,
    };
    expand(&mut state, &mut r_list, 0, candidate_mask);
    best
}

/// Maximum independent set via Tomita-style branch-and-bound with greedy coloring bound.
pub fn branch_and_bound_max_independent_set(
    neighbor_sets: &[HashSet<usize>],
    lower_bound: &[usize],
    deadline: Instant,
) -> Vec<usize> {
    let n = neighbor_sets.len();
    if n == 0 {
        return vec![];
    }

    let masks = neighbor_sets_to_masks(
        &neighbor_sets
            .iter()
            .map(|s| {
                let mut v: Vec<usize> = s.iter().copied().collect();
                v.sort_unstable();
                v
            })
            .collect::<Vec<_>>(),
    );

    let mut best = lower_bound.to_vec();
    let mut best_size = best.len();

    let mut candidate_mask = BitMask::all(n);
    for v in 0..n {
        if neighbor_sets[v].len() > n.saturating_sub(best_size) {
            candidate_mask.clear(v);
        }
    }

    struct SearchState<'a> {
        masks: &'a [BitMask],
        deadline: Instant,
        best: &'a mut Vec<usize>,
        best_size: &'a mut usize,
        counter: u64,
        timed_out: bool,
    }

    fn expand(state: &mut SearchState<'_>, r_list: &mut Vec<usize>, r_size: usize, mut candidates: BitMask) {
        if state.timed_out {
            return;
        }

        state.counter += 1;
        if state.counter >= TIME_CHECK_INTERVAL {
            state.counter = 0;
            if Instant::now() >= state.deadline {
                state.timed_out = true;
                return;
            }
        }

        let mut order: Vec<usize> = Vec::new();
        let mut color_of: Vec<usize> = Vec::new();
        let mut uncolored = candidates;
        let mut color = 0usize;

        while !uncolored.is_empty() {
            color += 1;
            let mut available = uncolored;
            while !available.is_empty() {
                let vertex = available.lowest_bit().unwrap();
                order.push(vertex);
                color_of.push(color);
                uncolored.clear(vertex);
                available.clear(vertex);
                available.and_not_assign(&state.masks[vertex]);
            }
        }

        for i in (0..order.len()).rev() {
            if state.timed_out {
                return;
            }
            if r_size + color_of[i] <= *state.best_size {
                return;
            }

            let vertex = order[i];
            let new_size = r_size + 1;
            if new_size > *state.best_size {
                *state.best = r_list.iter().copied().chain(std::iter::once(vertex)).collect();
                *state.best_size = new_size;
            }

            let mut next_candidates = candidates;
            next_candidates.clear(vertex);
            next_candidates.and_not_assign(&state.masks[vertex]);
            if !next_candidates.is_empty() {
                r_list.push(vertex);
                expand(state, r_list, new_size, next_candidates);
                r_list.pop();
            }

            candidates.clear(vertex);
        }
    }

    let mut r_list = Vec::new();
    let mut state = SearchState {
        masks: &masks,
        deadline,
        best: &mut best,
        best_size: &mut best_size,
        counter: 0,
        timed_out: false,
    };
    expand(&mut state, &mut r_list, 0, candidate_mask);
    best
}
