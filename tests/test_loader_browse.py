"""Phase 1: the loader is discovered, connects, and browses as the caller.

Two different claims here, and they need different machinery.

*Discovery* is Data Formulator's, so it is checked by running Data Formulator's
own registry in a subprocess with `DF_PLUGIN_DIR` set — importing the registry
in-process would test whatever import order the rest of the suite happened to
produce.

*Browsing* is this loader's, and it is checked against a live stack under two
seeded identities, because "browses as the caller" is not a claim one identity
can make.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest

from e2e import upstream

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin" / "data_agent_data_loader.py"


def _loader_class():
    """Load the plugin by path, the way Data Formulator loads it."""
    spec = importlib.util.spec_from_file_location("data_agent_data_loader", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DataAgentDataLoader, module


def test_data_formulator_discovers_the_plugin_from_its_own_registry():
    """No fork, no patched file: one file in `DF_PLUGIN_DIR` and it is there.

    Run out of process so the assertion is about Data Formulator's scan and not
    about this suite's import order.
    """
    probe = (
        "from data_formulator.data_loader import DATA_LOADERS, PLUGIN_LOADERS, PLUGIN_ERRORS;"
        "import json;"
        "print(json.dumps({'keys': sorted(DATA_LOADERS), 'plugins': sorted(PLUGIN_LOADERS),"
        " 'errors': [str(e) for e in PLUGIN_ERRORS]}))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "DF_PLUGIN_DIR": str(ROOT / "plugin"), "HOME": str(ROOT)},
        check=False,
    )
    assert out.returncode == 0, f"the registry did not load: {out.stderr[-1500:]}"
    found = json.loads(out.stdout.strip().splitlines()[-1])
    assert "data_agent" in found["keys"], (
        f"Data Formulator did not register the plugin; errors={found['errors']}, "
        f"plugins={found['plugins']}"
    )
    assert "data_agent" in found["plugins"], "registered, but not as a plugin"


def test_the_loader_declares_no_connection_string_and_no_secret():
    """§6's central claim, as a property of `list_params()` rather than prose."""
    cls, _ = _loader_class()
    params = cls.list_params()
    names = {p["name"] for p in params}
    forbidden = {"password", "connection_string", "dsn", "secret", "client_secret", "token"}
    assert not (names & forbidden), f"a credential is declared as a parameter: {names & forbidden}"
    assert not any(p.get("sensitive") for p in params), (
        "a parameter is marked sensitive, which means one is expected to hold a secret"
    )
    assert cls.auth_instructions().strip(), "the fifth abstract member returns nothing"


@pytest.fixture(scope="module")
def cfg():
    cfg = upstream.config()
    why = upstream.stack_is_up(cfg)
    if why:
        pytest.skip(f"{why}; run `make up` in ../data-agent-service")
    return cfg


def _loader_for(who: str, cfg, monkeypatch=None):
    cls, _ = _loader_class()
    token = upstream.token_for(f"{who}@entraemulator.dev", cfg)
    loader = cls(
        {
            "gateway": cfg["DAF_APIM_BASE"],
            "executor_path": cfg["DAF_WAREHOUSE_REST_PATH"],
            "source": "contoso_warehouse",
            "tls_insecure": cfg.get("DAF_TLS_INSECURE", ""),
            "max_rows": cfg.get("DAF_MAX_ROWS", "100"),
        }
    )
    loader._token = lambda: token  # the broker's job, supplied directly
    return loader


def test_it_connects(cfg):
    assert _loader_for("alice", cfg).test_connection() is True


def test_it_lists_tables_with_columns_and_the_tier(cfg):
    tables = _loader_for("carol", cfg).list_tables()
    assert tables, "no tables for a role that may read them"
    by_name = {t["name"]: t for t in tables}
    customer = next(t for n, t in by_name.items() if n.endswith("dbo.dim_customer"))
    assert customer["metadata"]["columns"], "a table with no columns"
    assert customer["metadata"]["authz_tier"] == "user", (
        "contoso_warehouse is a user-tier source and the listing must say so"
    )
    assert all(t.get("table_key") for t in tables), "ensure_table_keys left a record without one"
    assert "row_count" not in customer["metadata"], (
        "row_count is deliberately absent (§4); reporting one means a COUNT(*) per table"
    )


def test_the_columns_a_caller_may_not_read_are_not_in_the_listing(cfg):
    """The claim that makes this loader different from a connection string.

    The model that writes transformations reads this metadata. A column the
    access rules deny must not be in it — otherwise the model can propose a
    chart that can only ever be refused.
    """

    def columns_for(who: str) -> set[str]:
        tables = _loader_for(who, cfg).list_tables(table_filter="dim_customer")
        entry = next(t for t in tables if t["name"].endswith("dbo.dim_customer"))
        return {c["name"] for c in entry["metadata"]["columns"]}

    analyst, finance = columns_for("alice"), columns_for("carol")
    assert "email" in finance, "the finance role may read email and the listing hid it"
    assert "email" not in analyst, (
        "the analyst is denied dbo.dim_customer.email but the listing offered it"
    )
    assert analyst < finance, f"expected the analyst to see fewer columns: {analyst} vs {finance}"


def test_fetching_is_honest_about_not_being_built(cfg):
    """Phase 1 does not fetch, and says so rather than returning an empty table."""
    with pytest.raises(NotImplementedError, match="phase 2"):
        _loader_for("carol", cfg).fetch_data_as_arrow("contoso_warehouse.dbo.dim_customer")
