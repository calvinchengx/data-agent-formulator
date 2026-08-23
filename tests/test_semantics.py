"""Phase 3: does the metadata carry enough that the wrong winner is avoidable?

`data-agent-service`'s README opens on a measurement — inferring *resolution
time* from wall-clock elapsed time names the wrong support team. This file
asks two separate questions about it, and they are separate on purpose:

1. **Is the reversal real on this data, through this loader?** Measured, not
   quoted.
2. **Does the metadata this loader hands the model state the difference?**
   That is what §8 phase 1 buys, and it is the most that can be claimed
   without a model in the loop.

Neither is "Data Formulator got it right". That needs a browser, an API key
and a person, and docs/parity.md keeps it as its own red row.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

from e2e import upstream

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin" / "data_agent_data_loader.py"
TICKETS = "contoso_support.support.tickets"


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


def _loader(cfg, mod, who="carol", source="contoso_support", catalog="om_catalog_api"):
    loader = mod.DataAgentDataLoader(
        {
            "gateway": cfg["DAF_APIM_BASE"],
            "executor_path": cfg["DAF_WAREHOUSE_REST_PATH"],
            "source": source,
            "catalog_source": catalog,
            "tls_insecure": cfg.get("DAF_TLS_INSECURE", ""),
            "max_rows": "500",
        }
    )
    token = upstream.token_for(f"{who}@entraemulator.dev", cfg)
    loader._token = lambda: token
    return loader


@pytest.fixture(scope="module")
def ticket_columns(cfg, mod):
    tables = _loader(cfg, mod).list_tables(table_filter="tickets")
    entry = next(t for t in tables if t["name"].endswith("support.tickets"))
    return entry, {c["name"]: c for c in entry["metadata"]["columns"]}


def test_the_column_definitions_reach_the_metadata_the_model_reads(ticket_columns):
    _entry, columns = ticket_columns
    described = {n for n, c in columns.items() if c.get("description")}
    assert described, "no column carries a definition; §8 phase 1 is not wired"
    assert {"elapsed_minutes", "resolution_minutes"} <= described


def test_the_definition_warns_against_the_derivation_that_gets_it_wrong(ticket_columns):
    """The one sentence the whole of §8 phase 1 exists to deliver."""
    _entry, columns = ticket_columns
    elapsed = columns["elapsed_minutes"]["description"]
    assert "NOT the answer" in elapsed, elapsed
    resolution = columns["resolution_minutes"]["description"]
    assert "waiting_minutes" in resolution, resolution


def test_the_definitions_are_readable_text_not_html_entities(ticket_columns):
    entry, columns = ticket_columns
    everything = (entry["metadata"].get("description") or "") + "".join(
        c.get("description", "") for c in columns.values()
    )
    assert "&#" not in everything and "&amp;" not in everything, (
        "descriptions reach the model HTML-escaped; the entities are noise in front of the meaning"
    )


def test_the_reversal_is_real_on_this_data_through_this_loader(cfg, mod):
    """Measured here rather than quoted from upstream's README.

    Ranked by wall-clock elapsed time one team is fastest; ranked by the
    definition the business actually uses, a different one is. If this ever
    stops being true, every claim built on it in this repository is stale.
    """
    loader = _loader(cfg, mod)
    tickets = loader.fetch_data_as_arrow(TICKETS, {"size": 5000}).to_pylist()
    agents = {
        a["agent_id"]: a["team"]
        for a in loader.fetch_data_as_arrow(
            "contoso_support.support.agents", {"size": 5000}
        ).to_pylist()
    }
    resolved = [t for t in tickets if t.get("status") == "resolved"]
    assert resolved, "no resolved tickets to rank"

    def fastest(column: str) -> str:
        totals: dict[str, list[float]] = {}
        for ticket in resolved:
            value = ticket.get(column)
            team = agents.get(ticket.get("agent_id"))
            if value is not None and team:
                totals.setdefault(team, []).append(float(value))
        return min(totals, key=lambda team: sum(totals[team]) / len(totals[team]))

    by_elapsed, by_definition = fastest("elapsed_minutes"), fastest("resolution_minutes")
    assert by_elapsed != by_definition, (
        f"both measures name {by_elapsed}; the wrong-winner story no longer holds on this data "
        "and the claims resting on it need re-checking"
    )


def test_a_browse_survives_a_catalog_that_is_not_there(cfg, mod):
    """A glossary being down must not stop a person from reading their data.

    It must also not silently look like a table with no definitions, so the
    absence is recorded where the metadata is read.
    """
    loader = _loader(cfg, mod, catalog="no_such_catalog_source")
    tables = loader.list_tables(table_filter="tickets")
    assert tables, "the browse failed because the catalog was unreachable"
    entry = next(t for t in tables if t["name"].endswith("support.tickets"))
    assert not any(c.get("description") for c in entry["metadata"]["columns"])
    assert "unavailable" in entry["metadata"].get("description", ""), (
        "definitions are missing and nothing says why"
    )
