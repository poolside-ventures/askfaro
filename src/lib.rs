//! Native extension bundled into the `askfaro` Python package, imported as
//! `faro._core`. Exposes ONLY the open-source free-tool surface from
//! `faro-core-free`: version info, free-tool execution, and the canonical
//! envelope builders. The gate, continuation tokens, and cloud client are NOT
//! compiled in (they live in the private superset crate).
//!
//! String-in/string-out (JSON) at the boundary, so no Rust types cross the FFI
//! seam.

use ::faro_core_free as core;
use pyo3::prelude::*;

/// Version of the embedded Rust core.
#[pyfunction]
fn version() -> String {
    core::version().to_string()
}

/// Version of the output-envelope schema (Spec 1).
#[pyfunction]
fn envelope_version() -> String {
    core::envelope::ENVELOPE_VERSION.to_string()
}

/// Names of the free tools available in this build.
#[pyfunction]
fn free_tools() -> Vec<String> {
    core::free_tools::available().into_iter().map(String::from).collect()
}

/// Execute a free tool by name with JSON-string params; returns the normalized
/// envelope as a JSON string. Never raises — tool errors come back as an envelope
/// with `status: "failed"`.
#[pyfunction]
fn execute_free_tool(name: &str, params_json: &str) -> String {
    core::execute_free_tool_json(name, params_json)
}

/// Wrap a raw tool/skill payload into the canonical envelope JSON (the same builder
/// the backend uses), so a locally produced result is shape-identical to a remote one.
#[pyfunction]
#[pyo3(signature = (skill, payload_json, summary=None, meta_json="{}", id=None, idempotency_key=None))]
fn wrap_tool_response(
    skill: &str,
    payload_json: &str,
    summary: Option<&str>,
    meta_json: &str,
    id: Option<&str>,
    idempotency_key: Option<&str>,
) -> String {
    core::wrap_tool_response_json(skill, payload_json, summary, meta_json, id, idempotency_key)
}

/// Build a buyer-safe error envelope JSON (shared error shape).
#[pyfunction]
#[pyo3(signature = (skill, code, message, retryable, meta_json="{}", id=None, idempotency_key=None))]
fn build_error(
    skill: &str,
    code: &str,
    message: &str,
    retryable: bool,
    meta_json: &str,
    id: Option<&str>,
    idempotency_key: Option<&str>,
) -> String {
    core::build_error_json(skill, code, message, retryable, meta_json, id, idempotency_key)
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", core::version())?;
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(envelope_version, m)?)?;
    m.add_function(wrap_pyfunction!(free_tools, m)?)?;
    m.add_function(wrap_pyfunction!(execute_free_tool, m)?)?;
    m.add_function(wrap_pyfunction!(wrap_tool_response, m)?)?;
    m.add_function(wrap_pyfunction!(build_error, m)?)?;
    Ok(())
}
