use model_upgrade_core::{
    extend_to_maximal_clique, fallback_maximum_clique, is_valid_maximum_clique,
    solve_maximum_clique as core_solve,
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

#[pyfunction]
#[pyo3(signature = (number_of_nodes, adjacency_list, time_limit=30.0, seed=None, problem_id=None))]
fn solve_maximum_clique(
    number_of_nodes: usize,
    adjacency_list: Vec<Vec<usize>>,
    time_limit: f64,
    seed: Option<u64>,
    problem_id: Option<String>,
) -> PyResult<Vec<usize>> {
    core_solve(
        number_of_nodes,
        &adjacency_list,
        time_limit,
        seed,
        problem_id.as_deref(),
    )
    .map_err(PyValueError::new_err)
}

#[pyfunction]
fn fallback_maximum_clique_py(adjacency_list: Vec<Vec<usize>>) -> Vec<usize> {
    fallback_maximum_clique(&adjacency_list)
}

#[pyfunction]
fn extend_to_maximal_clique_py(
    adjacency_list: Vec<Vec<usize>>,
    clique: Vec<usize>,
) -> Vec<usize> {
    extend_to_maximal_clique(&adjacency_list, &clique)
}

#[pyfunction]
fn is_valid_maximum_clique_py(adjacency_list: Vec<Vec<usize>>, nodes: Vec<usize>) -> bool {
    is_valid_maximum_clique(&adjacency_list, &nodes)
}

#[pymodule]
fn model_upgrade_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(solve_maximum_clique, m)?)?;
    m.add_function(wrap_pyfunction!(fallback_maximum_clique_py, m)?)?;
    m.add_function(wrap_pyfunction!(extend_to_maximal_clique_py, m)?)?;
    m.add_function(wrap_pyfunction!(is_valid_maximum_clique_py, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
