use std::collections::{HashMap, HashSet};

/// Batagelj-Zaversnik O(n+m) core decomposition.
pub fn core_and_degeneracy(neighbor_sets: &[HashSet<usize>]) -> (Vec<usize>, Vec<usize>) {
    let n = neighbor_sets.len();
    if n == 0 {
        return (vec![], vec![]);
    }

    let degrees: Vec<usize> = neighbor_sets.iter().map(|s| s.len()).collect();
    let max_degree = *degrees.iter().max().unwrap_or(&0);

    let mut bin_start = vec![0usize; max_degree + 2];
    for &d in &degrees {
        bin_start[d] += 1;
    }
    let mut start = 0usize;
    for d in 0..=max_degree {
        let count = bin_start[d];
        bin_start[d] = start;
        start += count;
    }

    let mut position = vec![0usize; n];
    let mut vertices = vec![0usize; n];
    for v in 0..n {
        position[v] = bin_start[degrees[v]];
        vertices[position[v]] = v;
        bin_start[degrees[v]] += 1;
    }

    for d in (1..=max_degree).rev() {
        bin_start[d] = bin_start[d - 1];
    }
    bin_start[0] = 0;

    let mut core = degrees.clone();
    let mut order = Vec::with_capacity(n);

    for i in 0..n {
        let vertex = vertices[i];
        order.push(vertex);
        for &neighbor in &neighbor_sets[vertex] {
            if core[neighbor] > core[vertex] {
                let deg_n = core[neighbor];
                let pos_n = position[neighbor];
                let pos_first = bin_start[deg_n];
                let first = vertices[pos_first];
                if neighbor != first {
                    position[neighbor] = pos_first;
                    vertices[pos_n] = first;
                    position[first] = pos_n;
                    vertices[pos_first] = neighbor;
                }
                bin_start[deg_n] += 1;
                core[neighbor] -= 1;
            }
        }
    }

    (core, order)
}

pub fn build_search_core(
    clique: &[usize],
    neighbor_sets: &[HashSet<usize>],
    core_numbers: &[usize],
) -> Vec<usize> {
    let min_core = clique.len().saturating_sub(1);
    let mut vertices: HashSet<usize> = clique.iter().copied().collect();
    if !clique.is_empty() {
        let common: HashSet<usize> = clique
            .iter()
            .map(|&v| neighbor_sets[v].clone())
            .reduce(|a, b| a.intersection(&b).copied().collect())
            .unwrap_or_default();
        vertices.extend(common);
    }
    let mut out: Vec<usize> = vertices
        .into_iter()
        .filter(|&v| core_numbers[v] >= min_core)
        .collect();
    out.sort_unstable();
    out
}

pub fn extract_subgraph(
    neighbor_sets: &[HashSet<usize>],
    vertices: &[usize],
) -> (Vec<HashSet<usize>>, Vec<usize>) {
    let labels: Vec<usize> = {
        let mut v = vertices.to_vec();
        v.sort_unstable();
        v
    };
    let index_of: HashMap<usize, usize> = labels
        .iter()
        .enumerate()
        .map(|(i, &v)| (v, i))
        .collect();
    let subgraph: Vec<HashSet<usize>> = labels
        .iter()
        .map(|&vertex| {
            neighbor_sets[vertex]
                .iter()
                .filter_map(|&n| index_of.get(&n).copied())
                .collect()
        })
        .collect();
    (subgraph, labels)
}

pub fn map_clique_to_original(clique: &[usize], labels: &[usize]) -> Vec<usize> {
    let mut out: Vec<usize> = clique.iter().map(|&i| labels[i]).collect();
    out.sort_unstable();
    out
}

pub fn adjacency_to_neighbor_sets(adjacency_list: &[Vec<usize>]) -> Vec<HashSet<usize>> {
    adjacency_list
        .iter()
        .map(|neighbors| neighbors.iter().copied().collect())
        .collect()
}

pub fn neighbor_sets_to_adjacency(neighbor_sets: &[HashSet<usize>]) -> Vec<Vec<usize>> {
    neighbor_sets
        .iter()
        .map(|s| {
            let mut v: Vec<usize> = s.iter().copied().collect();
            v.sort_unstable();
            v
        })
        .collect()
}
