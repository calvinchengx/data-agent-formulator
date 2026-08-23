"""§8 phase 2: tables that are released metrics, not warehouse tables.

The claim `data_agent` cannot make is that the wrong derivation is
*unavailable*. This loader can: its columns are metrics the warehouse computed
from a released statement, and there is no rawer column beside them.

These checks are about that property and about the two ways the loader could
quietly cheat — guessing a slot value, or guessing an aggregate's type.
"""

from __future__ import annotations

import decimal
import pathlib
import sys

import pyarrow as pa
import pytest

from e2e import upstream

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "plugin"
CANDIDATES = ROOT.parent / "data-agent-service" / "promoter" / "candidates.json"


@pytest.fixture(scope="module")
def mod():
    """Import as Data Formulator does: the plugin directory on the path."""
    sys.path.insert(0, str(PLUGIN_DIR))
    try:
        import data_agent_metrics_data_loader as module
    finally:
        sys.path.remove(str(PLUGIN_DIR))
    return module


@pytest.fixture(scope="module")
def cfg():
    cfg = upstream.config()
    why = upstream.stack_is_up(cfg)
    if why:
        pytest.skip(f"{why}; run `make up` in ../data-agent-service")
    if not CANDIDATES.exists():
        pytest.skip(f"no promoter output at {CANDIDATES}; run the promoter in data-agent-service")
    return cfg


def _loader(cfg, mod, who="carol"):
    loader = mod.DataAgentMetricsDataLoader(
        {
            "gateway": cfg["DAF_APIM_BASE"],
            "executor_path": cfg["DAF_WAREHOUSE_REST_PATH"],
            "source": "contoso_warehouse",
            "tls_insecure": cfg.get("DAF_TLS_INSECURE", ""),
            "max_rows": "200",
            "candidates": str(CANDIDATES),
        }
    )
    token = upstream.token_for(f"{who}@entraemulator.dev", cfg)
    loader.agent._token = lambda: token
    return loader


# ------------------------------------------------------- typing, offline


def test_an_aggregate_is_typed_from_what_it_aggregates(mod):
    """T-SQL widens SUM and AVG over decimal(p, s) to decimal(38, s)."""
    types = {"revenue_usd": "decimal(19,4)", "units": "bigint(19,0)"}
    assert mod.measure_type("sum(t0.revenue_usd)", types) == pa.decimal128(38, 4)
    assert mod.measure_type("avg(t0.revenue_usd)", types) == pa.decimal128(38, 4)
    assert mod.measure_type("count(*)", types) == pa.int64()
    assert mod.measure_type("max(t0.units)", types) == pa.int64()


def test_an_untypeable_measure_is_refused_rather_than_guessed(mod):
    with pytest.raises(mod.ConnectorError, match="nothing declares the type"):
        mod.measure_type("sum(t0.mystery)", {"revenue_usd": "decimal(19,4)"})
    with pytest.raises(mod.ConnectorError, match="not an aggregate"):
        mod.measure_type("t0.revenue_usd * 2", {"revenue_usd": "decimal(19,4)"})


def test_a_missing_candidates_file_says_what_to_run(mod):
    loader = mod.DataAgentMetricsDataLoader({"candidates": "/nowhere/candidates.json"})
    with pytest.raises(mod.ConnectorError, match="run the promoter"):
        loader.released()


# ----------------------------------------------------------- against the stack


@pytest.fixture(scope="module")
def tables(cfg, mod):
    return _loader(cfg, mod).list_tables()


def test_every_slot_value_is_its_own_table_rather_than_a_default(tables):
    """Binding a slot for the person would be exactly the quiet decision to avoid."""
    assert tables, "no released metrics"
    bindings = [t["metadata"]["binding"] for t in tables]
    assert all(bindings), "a table was offered with an unbound slot"
    values = {tuple(sorted(b.items())) for b in bindings}
    assert len(values) == len(bindings), "the same binding was offered twice"
    for table in tables:
        for key, value in table["metadata"]["binding"].items():
            assert f"{key}={value}" in table["name"], (
                f"the bound value is not visible in the name: {table['name']}"
            )


def test_the_columns_are_the_metric_and_its_dimensions_only(tables):
    """The property `data_agent` cannot offer: no rawer column to derive from."""
    columns = {c["name"] for c in tables[0]["metadata"]["columns"]}
    assert "c1" in columns, "the released measure is not a column"
    assert "revenue_usd" not in columns, (
        "the raw column is offered beside the metric, which is the situation this loader avoids"
    )


def test_a_degraded_title_is_passed_on_rather_than_smoothed(tables):
    """The promoter says when the catalog was too thin to name the columns."""
    described = tables[0]["metadata"]["description"]
    assert "released template" in described.lower()
    assert "degraded" in described.lower(), described


def test_the_metric_arrives_as_a_decimal_computed_by_the_warehouse(cfg, mod, tables):
    table = _loader(cfg, mod).fetch_data_as_arrow(tables[0]["name"])
    assert table.schema.field("c1").type == pa.decimal128(38, 4)
    values = table.column("c1").to_pylist()
    assert values and all(isinstance(v, decimal.Decimal) for v in values)
    assert table.num_rows > 0, "the released template returned nothing; the binding is wrong"


def test_the_bound_statement_still_runs_as_the_caller(cfg, mod, tables):
    """A released template is not a way around the executor's decision."""
    with pytest.raises(mod.ExecutorRefusal) as caught:
        _loader(cfg, mod, who="bob").fetch_data_as_arrow(tables[0]["name"])
    assert caught.value.status == 403
