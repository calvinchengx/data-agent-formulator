"""docs/00-plan.md §3 is checked against the installed release, not remembered.

§3 was first written from `main` and was wrong in four ways by the time it met
the pin. The prose is not the guard; this file is. A Data Formulator upgrade
that changes the interface fails here with the difference named, which is the
only way a design document stays true to a dependency that moves.
"""

from __future__ import annotations

from importlib.metadata import version

from data_formulator.data_loader import external_data_loader as edl

PIN = "0.7.0"

# Every abstract member a plugin MUST implement, as of the pin. `auth_instructions`
# is the one §3 missed: it is required, and a loader without it cannot be
# instantiated at all.
ABSTRACT = {
    "__init__",
    "auth_instructions",
    "fetch_data_as_arrow",
    "list_params",
    "list_tables",
}

# Concrete on the base, so the loader inherits them. Named here because the
# design leans on them: `validate_params` carries the `skip_auth_tier` escape
# that §6's identity model needs, and `get_safe_params` is what keeps a
# declared-sensitive param out of stored metadata.
INHERITED = {
    "delegated_login_config",
    "fetch_data_as_dataframe",
    "get_safe_params",
    "ingest_to_workspace",
    "list_tables_tree",
    "ls",
    "test_connection",
    "validate_params",
}


def test_the_installed_release_is_the_pin():
    """The package exposes no `__version__`; the distribution metadata is the truth."""
    installed = version("data_formulator")
    assert installed == PIN, (
        f"docs/00-plan.md §3 was checked against {PIN}; {installed} is installed"
    )


def test_the_abstract_members_are_the_ones_the_plan_documents():
    actual = set(edl.ExternalDataLoader.__abstractmethods__)
    assert actual == ABSTRACT, (
        f"the interface moved: only in the release {sorted(actual - ABSTRACT)}, "
        f"only in the plan {sorted(ABSTRACT - actual)}"
    )


def test_the_members_the_design_leans_on_are_inherited():
    missing = {n for n in INHERITED if not hasattr(edl.ExternalDataLoader, n)}
    assert not missing, f"the design leans on members the release does not have: {sorted(missing)}"


def test_the_helpers_the_plan_names_exist_at_module_level():
    """§3 named `apply_import_projection`, which is a `main`-only helper.

    What the pin actually offers for turning `import_options` into SQL is the
    `build_where_clause` family, which is what the built-in loaders use.
    """
    for name in ("build_where_clause", "build_where_clause_inline", "sanitize_table_name"):
        assert hasattr(edl, name), f"the plan names {name}, the release does not have it"
    assert not hasattr(edl, "apply_import_projection"), (
        "apply_import_projection now exists at the pin; §3's correction can be reverted"
    )


def test_validate_params_can_skip_the_auth_tier():
    """§6 rests on this: a param declared `tier="auth"` is not required up front.

    It is what lets the loader take its bearer from outside Data Formulator's
    own parameter store rather than as a field a person types into a form.
    """
    import inspect

    sig = inspect.signature(edl.ExternalDataLoader.validate_params)
    assert "skip_auth_tier" in sig.parameters, (
        "validate_params no longer offers skip_auth_tier; §6's identity model needs rewriting"
    )
