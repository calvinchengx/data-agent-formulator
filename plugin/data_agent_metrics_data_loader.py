"""Tables that are released metric templates, not warehouse tables.

Registered as ``data_agent_metrics``. This is §8 phase 2 of docs/00-plan.md,
and it is the honest answer to the question the repository exists to ask.

`data_agent` narrows the gap by putting the catalog's definitions in front of
the model. It cannot close it: a tool that writes arbitrary transformations can
always write `avg(elapsed_minutes)` and label it resolution time, however
clearly the column says otherwise.

This loader closes it differently. Its tables are the templates the promoter
*released* — SQL that recurred often enough across enough people to be worth
governing, already expressed in the catalog's vocabulary. The measure is
computed by the warehouse from the released statement, so the column a person
charts is the metric, and there is no rawer column beside it to derive the
wrong thing from.

Two consequences worth being plain about:

* **It is narrow by construction.** You can chart what has been released and
  nothing else. That is the trade, not a limitation to be fixed.
* **It reads the promoter's output file.** There is no upstream API that
  serves released candidates; see `docs/upstream-issues.md`. Until there is,
  the path is configuration and this loader is only as fresh as the last
  promoter run.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from typing import Any

import pyarrow as pa


def _sibling(name: str):
    """Load the other plugin in this directory, by path.

    Data Formulator loads each plugin file directly and does **not** put the
    plugin directory on `sys.path`, so `import data_agent_data_loader` fails at
    run time -- the app reports the loader as disabled with a pip install hint
    for a package that does not exist. A test that imported it with the path
    patched passed happily while the application could not load it at all;
    opening the UI is what found that, which is why docs/parity.md keeps
    "witnessed running" as its own column.
    """
    import importlib.util

    path = pathlib.Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_agent = _sibling("data_agent_data_loader")
ConnectorError = _agent.ConnectorError
DataAgentDataLoader = _agent.DataAgentDataLoader
ExecutorRefusal = _agent.ExecutorRefusal
arrow_type_for = _agent.arrow_type_for
_to_array = _agent._to_array
from data_formulator.data_loader.external_data_loader import ExternalDataLoader

#: How many values of a slot column become their own table. A template with an
#: unbound slot is not importable, and offering every value of a high-cardinality
#: column would be a browse nobody can read. What is dropped is said, never
#: silently truncated.
_MAX_SLOT_VALUES = 25

_AGGREGATE = re.compile(r"^\s*(count|sum|avg|min|max)\s*\(\s*(.+?)\s*\)\s*$", re.I)


def measure_type(expression: str, column_types: dict[str, str]) -> pa.DataType:
    """The Arrow type of an aggregate, from the type of what it aggregates.

    Same rule as everywhere else here: derived from the engine's declaration,
    never inferred from a value. `SUM` and `AVG` over `decimal(p, s)` widen to
    `decimal(38, s)` in T-SQL, which is the only widening this needs to know
    about — and an aggregate over something whose type is unknown is refused
    rather than guessed at.
    """
    match = _AGGREGATE.match(expression)
    if not match:
        raise ConnectorError(f"cannot type the measure {expression!r}: not an aggregate")
    function, inner = match.group(1).lower(), match.group(2)
    if function == "count":
        return pa.int64()
    column = inner.rsplit(".", 1)[-1].strip()
    declared = column_types.get(column)
    if not declared:
        raise ConnectorError(
            f"cannot type the measure {expression!r}: nothing declares the type of {column!r}"
        )
    base = arrow_type_for(declared, column)
    if function in {"sum", "avg"} and pa.types.is_decimal(base):
        return pa.decimal128(38, base.scale)
    return base


class DataAgentMetricsDataLoader(ExternalDataLoader):
    """Released metric templates, one importable table per bound slot value."""

    DISPLAY_NAME = "Data Agent Metrics"

    @staticmethod
    def list_params() -> list[dict[str, Any]]:
        params = [p for p in DataAgentDataLoader.list_params() if p["name"] != "catalog_source"]
        params.append(
            {
                "name": "candidates",
                "type": "string",
                "required": True,
                "default": os.environ.get(
                    "DAF_CANDIDATES", "../data-agent-service/promoter/candidates.json"
                ),
                "tier": "connection",
                "description": "The promoter's released candidates. No API serves these yet",
            }
        )
        return params

    @staticmethod
    def auth_instructions() -> str:
        return (
            DataAgentDataLoader.auth_instructions()
            + "\n\n**What you can chart here:** only metrics the promoter has *released* — "
            "questions that recurred often enough, across enough people, to be worth governing. "
            "The measure is computed by the warehouse from the released statement, so there is no "
            "rawer column beside it to derive something else from. That narrowness is the point."
        )

    def __init__(self, params: dict[str, Any]):
        self.params = dict(params or {})
        self.agent = DataAgentDataLoader(self.params)
        self.candidates_path = pathlib.Path(str(self.params.get("candidates") or "")).expanduser()

    def test_connection(self) -> bool:
        return self.candidates_path.exists() and self.agent.test_connection()

    # --------------------------------------------------------------- browsing

    def released(self) -> list[dict[str, Any]]:
        if not self.candidates_path.exists():
            raise ConnectorError(
                f"no released candidates at {self.candidates_path} — run the promoter in "
                "data-agent-service, or point `candidates` at its output"
            )
        payload = json.loads(self.candidates_path.read_text(encoding="utf-8"))
        return list(payload.get("released") or [])

    def _slot_values(self, source: str, table: str, column: str) -> tuple[list[Any], str]:
        """Distinct values of a slot column, so nothing has to be guessed.

        A template's `?` has to be bound before the statement means anything.
        Choosing a value for the person would be exactly the kind of quiet
        decision this repository exists to avoid, so each value becomes its own
        importable table and the choice is theirs.
        """
        sql = f'SELECT DISTINCT "{column}" FROM {table}'
        payload = self.agent._call(
            "POST", "/query", body={"sql": sql, "source": source, "maxRows": _MAX_SLOT_VALUES + 1}
        )
        values = [row[0] for row in (payload.get("rows") or [])]
        note = ""
        if len(values) > _MAX_SLOT_VALUES:
            values = values[:_MAX_SLOT_VALUES]
            note = f"only the first {_MAX_SLOT_VALUES} values of {column} are offered"
        return values, note

    def list_tables(self, table_filter: str | None = None) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for candidate in self.released():
            source = candidate.get("source", "")
            table = (candidate.get("tables") or [""])[0]
            title = candidate.get("title") or candidate.get("template_hash", "")
            slots = list(candidate.get("slot_columns") or [])
            column_types = {
                c["name"]: c.get("type", "") for c in self.agent._columns_for(source, table)
            }
            bindings, note = self._bindings_for(source, table, slots)
            for binding in bindings:
                label = " · ".join([title, *(f"{k}={v}" for k, v in binding.items())])
                if table_filter and table_filter.lower() not in label.lower():
                    continue
                results.append(
                    {
                        "name": label,
                        "path": [source, title, *(str(v) for v in binding.values())],
                        "metadata": self._metadata(candidate, column_types, binding, note),
                    }
                )
        self.ensure_table_keys(results)
        return results

    def _bindings_for(
        self, source: str, table: str, slots: list[str]
    ) -> tuple[list[dict[str, Any]], str]:
        """One binding per slot value. Multi-slot templates are not expanded.

        A cross product of two slots is a browse of hundreds of near-identical
        tables, which is worse than saying so. Such a template is listed once,
        unbound, and refused at import with the slots named.
        """
        if not slots:
            return [{}], ""
        if len(slots) > 1:
            return [
                {}
            ], f"template has {len(slots)} slots ({', '.join(slots)}) and is not importable"
        values, note = self._slot_values(source, table, slots[0])
        return [{slots[0]: v} for v in values], note

    def _metadata(
        self,
        candidate: dict[str, Any],
        column_types: dict[str, str],
        binding: dict[str, Any],
        note: str,
    ) -> dict[str, Any]:
        columns = []
        for dimension in candidate.get("dimensions") or []:
            name = dimension.rsplit(".", 1)[-1]
            columns.append(
                {"name": name, "type": column_types.get(name, ""), "description": "dimension"}
            )
        for index, measure in enumerate(candidate.get("measures") or [], start=1):
            columns.append(
                {
                    "name": f"c{index}",
                    "type": measure,
                    "description": f"released metric: {measure}",
                }
            )
        described = [
            f"Released template, run about {candidate.get('approx_runs', '?')} times by about "
            f"{candidate.get('approx_users', '?')} people.",
            "The measure is computed by the warehouse from the released statement.",
        ]
        if candidate.get("title_quality") == "degraded":
            # The promoter says when it could not name the columns from the
            # catalog. Passing that on matters: a degraded title is a hint that
            # the catalog is thin here, which is the opposite of the guarantee
            # this loader otherwise offers.
            thin = ", ".join(candidate.get("degraded_columns") or [])
            described.append(
                f"The promoter could not name every column from the catalog ({thin}), "
                "so this title is degraded."
            )
        if note:
            described.append(note)
        return {
            "columns": columns,
            "source_metadata_status": "synced",
            "authz_tier": "user",
            "binding": binding,
            "template_hash": candidate.get("template_hash", ""),
            "description": " ".join(described),
        }

    # --------------------------------------------------------------- fetching

    def _find(self, source_table: str) -> tuple[dict[str, Any], dict[str, Any]]:
        for entry in self.list_tables():
            if entry["name"] == source_table:
                candidate = next(
                    c
                    for c in self.released()
                    if c.get("template_hash") == entry["metadata"]["template_hash"]
                )
                return candidate, entry["metadata"]
        raise ConnectorError(f"no released metric called {source_table!r}")

    def fetch_data_as_arrow(
        self, source_table: str, import_options: dict[str, Any] | None = None
    ) -> pa.Table:
        """Run the released statement, with its slot bound to the chosen value."""
        candidate, metadata = self._find(source_table)
        source = candidate.get("source", "")
        sql = candidate.get("template_sql") or ""
        binding = metadata.get("binding") or {}

        slots = list(candidate.get("slot_columns") or [])
        if len(slots) != len(binding):
            raise ConnectorError(
                f"{source_table!r} has unbound slots ({', '.join(slots)}) and cannot be imported. "
                "Templates with more than one slot are listed but not expanded."
            )
        for value in binding.values():
            sql = sql.replace("?", _literal(value), 1)
        if "?" in sql:
            raise ConnectorError(f"{source_table!r} still has an unbound slot after binding")

        payload = self.agent._call(
            "POST",
            "/query",
            body={"sql": sql, "source": source, "maxRows": self.agent.max_rows},
            sql=sql,
        )
        names = payload.get("columns") or []
        column_types = {c["name"]: c.get("type", "") for c in self._base_columns(candidate)}
        measures = list(candidate.get("measures") or [])

        fields = []
        for name in names:
            if name in column_types:
                fields.append(pa.field(name, arrow_type_for(column_types[name], name)))
            else:
                # A measure column, named positionally by the promoter.
                position = len(fields) - len(candidate.get("dimensions") or [])
                expression = measures[position] if 0 <= position < len(measures) else ""
                fields.append(pa.field(name, measure_type(expression, column_types)))
        schema = pa.schema(fields)

        rows = payload.get("rows") or []
        columnar = [[row[i] if i < len(row) else None for row in rows] for i in range(len(names))]
        arrays = [
            _to_array(values, field.type, field.name)
            for values, field in zip(columnar, schema, strict=True)
        ]
        return pa.Table.from_arrays(arrays, schema=schema)

    def _base_columns(self, candidate: dict[str, Any]) -> list[dict[str, Any]]:
        table = (candidate.get("tables") or [""])[0]
        return self.agent._columns_for(candidate.get("source", ""), table)


def _literal(value: Any) -> str:
    """A bound slot value, escaped. The executor's guard parses what comes back."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


__all__ = ["DataAgentMetricsDataLoader", "ExecutorRefusal", "measure_type"]
