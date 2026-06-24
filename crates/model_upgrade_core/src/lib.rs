pub mod bitsets;
pub mod branch_bound;
pub mod dense;
pub mod graph_utils;
pub mod heuristics;
pub mod solver;
pub mod validation;

pub use solver::{fallback_maximum_clique, search_budget, solve_maximum_clique};
pub use validation::{extend_to_maximal_clique, is_valid_maximum_clique};
