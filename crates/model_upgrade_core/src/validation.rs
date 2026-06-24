use std::collections::HashSet;

/// Greedily extend a clique, preferring highest-degree vertices first.
pub fn extend_to_maximal_clique(adjacency_list: &[Vec<usize>], clique: &[usize]) -> Vec<usize> {
    let mut clique_set: HashSet<usize> = clique.iter().copied().collect();
    let n = adjacency_list.len();

    loop {
        let mut best_vertex: Option<usize> = None;
        let mut best_degree = isize::MIN;
        for vertex in 0..n {
            if clique_set.contains(&vertex) {
                continue;
            }
            if clique_is_subset_of_neighbors(&clique_set, &adjacency_list[vertex]) {
                let degree = adjacency_list[vertex].len() as isize;
                if degree > best_degree {
                    best_degree = degree;
                    best_vertex = Some(vertex);
                }
            }
        }
        match best_vertex {
            None => break,
            Some(v) => {
                clique_set.insert(v);
            }
        }
    }

    let mut out: Vec<usize> = clique_set.into_iter().collect();
    out.sort_unstable();
    out
}

fn clique_is_subset_of_neighbors(clique: &HashSet<usize>, neighbors: &[usize]) -> bool {
    if clique.is_empty() {
        return true;
    }
    let neighbor_set: HashSet<usize> = neighbors.iter().copied().collect();
    clique.is_subset(&neighbor_set)
}

/// Return true if nodes form a valid maximal clique.
pub fn is_valid_maximum_clique(adjacency_list: &[Vec<usize>], nodes: &[usize]) -> bool {
    let node_set: HashSet<usize> = nodes.iter().copied().collect();
    if node_set.is_empty() {
        return false;
    }
    if node_set.len() != nodes.len() {
        return false;
    }
    if !node_set.iter().all(|&v| v < adjacency_list.len()) {
        return false;
    }

    let node_list: Vec<usize> = node_set.iter().copied().collect();
    for i in 0..node_list.len() {
        for j in (i + 1)..node_list.len() {
            let u = node_list[i];
            let v = node_list[j];
            if !adjacency_list[u].contains(&v) {
                return false;
            }
        }
    }

    for candidate in 0..adjacency_list.len() {
        if node_set.contains(&candidate) {
            continue;
        }
        if clique_is_subset_of_neighbors(&node_set, &adjacency_list[candidate]) {
            return false;
        }
    }

    true
}
