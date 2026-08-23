"""Phase 2: fetching, and the three ways it could quietly be wrong.

The hazards in docs/00-plan.md §7, each with a check that fails for its own
reason: a decimal that becomes a double, a refusal that becomes an empty
table, and generated SQL the executor's guard will not accept.
"""

from __future__ import annotations

import decimal
import importlib.util
import pathlib

import pyarrow as pa
import pytest

from e2e import upstream

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin" / "data_agent_data_loader.py"

REVENUE = "contoso_warehouse.dbo.fct_daily_revenue"


def _module():
    spec = importlib.util.spec_from_file_location("data_agent_data_loader", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _module()


@pytest.fixture(scope="module")
def cfg():
    cfg = upstream.config()
    why = upstream.stack_is_up(cfg)
    if why:
        pytest.skip(f"{why}; run `make up` in ../data-agent-service")
    return cfg


def _loader(who: str, cfg, mod, source="contoso_warehouse", max_rows="50"):
    loader = mod.DataAgentDataLoader(
        {
            "gateway": cfg["DAF_APIM_BASE"],
            "executor_path": cfg["DAF_WAREHOUSE_REST_PATH"],
            "source": source,
            "tls_insecure": cfg.get("DAF_TLS_INSECURE", ""),
            "max_rows": max_rows,
        }
    )
    token = upstream.token_for(f"{who}@entraemulator.dev", cfg)
    loader._token = lambda: token
    return loader


# ------------------------------------------------------ the type map, offline


def test_a_decimal_type_maps_to_a_decimal_not_a_double(mod):
    assert mod.arrow_type_for("decimal(19,4)", "revenue") == pa.decimal128(19, 4)
    assert mod.arrow_type_for("numeric(10,2)", "x") == pa.decimal128(10, 2)
    # int(10,0) also carries precision and scale; only the decimal family is a decimal.
    assert mod.arrow_type_for("int(10,0)", "n") == pa.int32()
    assert mod.arrow_type_for("bigint(19,0)", "n") == pa.int64()


def test_an_unmappable_type_is_refused_rather_than_guessed(mod):
    """§7: a silent cast is the failure this loader exists to prevent."""
    with pytest.raises(mod.UnmappedColumnType, match="Refusing to guess"):
        mod.arrow_type_for("geography", "shape")


# ------------------------------------------------------- the decimal witness


@pytest.fixture(scope="module")
def revenue(cfg, mod):
    return _loader("carol", cfg, mod).fetch_data_as_arrow(REVENUE, {"size": 5})


def test_a_decimal_column_arrives_as_a_decimal(revenue):
    assert revenue.schema.field("revenue").type == pa.decimal128(19, 4)
    values = revenue.column("revenue").to_pylist()
    assert values and all(isinstance(v, decimal.Decimal) for v in values), (
        f"expected Decimals, got {[type(v).__name__ for v in values[:3]]}"
    )


def test_inference_would_have_got_it_wrong(revenue):
    """The check that makes the one above non-vacuous.

    If Arrow inferred from the rows instead of the declared types, this is the
    schema it would have produced. G8 upstream was exactly this: a decimal read
    as a double, misattributed twice before anyone measured it.
    """
    inferred = pa.Table.from_pylist(
        [
            {k: float(v) if isinstance(v, decimal.Decimal) else v for k, v in row.items()}
            for row in revenue.to_pylist()
        ]
    )
    assert inferred.schema.field("revenue").type == pa.float64()
    assert inferred.schema.field("revenue").type != revenue.schema.field("revenue").type


def test_the_row_ceiling_is_applied(cfg, mod):
    table = _loader("carol", cfg, mod).fetch_data_as_arrow(REVENUE, {"size": 3})
    assert table.num_rows <= 3, f"asked for 3 rows, got {table.num_rows}"


# ------------------------------------------------------------- the refusals


def test_a_refusal_is_raised_not_returned_as_an_empty_table(cfg, mod):
    """Bob holds no role. An empty table here would render as 'nothing matched'."""
    with pytest.raises(mod.ExecutorRefusal) as caught:
        _loader("bob", cfg, mod).fetch_data_as_arrow(REVENUE, {"size": 1})
    assert caught.value.status == 403
    assert "no role" in caught.value.detail, caught.value.detail


def test_a_missing_token_is_a_refusal_that_says_what_to_do(cfg, mod):
    loader = mod.DataAgentDataLoader(
        {
            "gateway": cfg["DAF_APIM_BASE"],
            "executor_path": cfg["DAF_WAREHOUSE_REST_PATH"],
            "source": "contoso_warehouse",
            "token_file": "/nonexistent/.token",
        }
    )
    with pytest.raises(mod.ExecutorRefusal, match="make login"):
        loader.list_tables()


def test_a_denied_column_never_enters_the_statement(cfg, mod):
    """Alice may not read `dbo.dim_customer.email`.

    The projection is built from what the executor described for HER, so the
    column is absent from the SQL text rather than being sent and refused.
    """
    loader = _loader("alice", cfg, mod)
    columns = loader._columns_for("contoso_warehouse", "dbo.dim_customer")
    sql = loader._statement("dbo.dim_customer", columns, "tsql", {"size": 5})
    assert "email" not in sql.lower(), sql
    assert "*" not in sql, f"SELECT * leaves the column set to the engine: {sql}"
    table = loader.fetch_data_as_arrow("contoso_warehouse.dbo.dim_customer", {"size": 5})
    assert "email" not in table.schema.names


# -------------------------------------------------- the import_options corpus


IMPORT_OPTIONS = [
    pytest.param({}, id="nothing"),
    pytest.param({"size": 2}, id="size"),
    pytest.param({"columns": ["country", "revenue"]}, id="projection"),
    pytest.param({"sort_columns": ["revenue"], "sort_order": "desc"}, id="sort-desc"),
    pytest.param({"sort_columns": ["country"], "sort_order": "asc"}, id="sort-asc"),
    pytest.param(
        {"conditions": [{"column": "country", "operator": "=", "value": "GB"}]}, id="condition"
    ),
    pytest.param(
        {
            "size": 3,
            "columns": ["country", "revenue"],
            "sort_columns": ["revenue"],
            "sort_order": "desc",
        },
        id="combined",
    ),
]


@pytest.mark.parametrize("options", IMPORT_OPTIONS)
def test_every_import_options_shape_produces_sql_the_guard_accepts(cfg, mod, options):
    """The executor's guard parses rather than pattern-matches.

    Anything this loader generates has to survive that. A refusal here is a
    defect in the generator, not a permission decision — Carol may read this
    table, as the other checks in this file rely on.
    """
    table = _loader("carol", cfg, mod).fetch_data_as_arrow(REVENUE, options)
    assert table.num_rows >= 0
    if "columns" in options:
        assert table.schema.names == options["columns"]


def test_the_other_dialect_is_generated_differently(cfg, mod):
    """`contoso_support` is PostgreSQL. T-SQL's `TOP` would be a syntax error there."""
    loader = _loader("carol", cfg, mod, source="contoso_support")
    assert loader._dialect_of("contoso_support") == "postgres"
    columns = loader._columns_for("contoso_support", "support.tickets")
    sql = loader._statement("support.tickets", columns, "postgres", {"size": 4})
    assert sql.rstrip().endswith("LIMIT 4"), sql
    assert "TOP" not in sql.upper(), sql
    assert loader.fetch_data_as_arrow("contoso_support.support.tickets", {"size": 4}).num_rows <= 4
