"""A Data Formulator loader that reads through data-agent-service's executor.

Registered as ``data_agent`` -- Data Formulator derives the key from this
file's name. See docs/00-plan.md for the design and docs/parity.md for what is
witnessed.

**Self-contained on purpose.** Data Formulator loads a plugin by file path, out
of a directory that is not a package, so this file may import only the standard
library and Data Formulator's own modules. There is no shared helper module to
import, and adding one would mean the deployed artefact is no longer the single
file a person drops into ``DF_PLUGIN_DIR``.

Two properties this loader exists to keep, both from §2 and §6 of the plan:

* **It holds no warehouse credential.** Its parameters are a gateway URL and a
  source name. The bearer comes from outside Data Formulator's parameter store,
  because that store is persisted to the workspace and a token's lifetime is
  not the workspace's.
* **A refusal stays a refusal.** The executor refuses -- a denied column, a
  schema outside the allow-list, an expired token. None of those may reach the
  UI as an empty result, which reads as "nothing matched".
"""

from __future__ import annotations

import contextlib
import decimal
import json
import os
import pathlib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import pyarrow as pa
from data_formulator.data_loader.external_data_loader import (
    MAX_IMPORT_ROWS,
    ExternalDataLoader,
    build_source_filter_where_clause_inline,
    build_where_clause_inline,
)

# Data Formulator's own connector error, when it is importable. It is what makes
# the UI say *failed* with a message rather than render an empty table. The
# fallback keeps this file loadable against a release that moves it, because a
# plugin that cannot import is a plugin that silently is not there.
try:  # pragma: no cover - exercised by whichever branch the pin provides
    from data_formulator.data_loader.connector_errors import ConnectorError
except ImportError:  # pragma: no cover
    ConnectorError = RuntimeError


class ExecutorRefusal(ConnectorError):
    """The executor refused, and said why.

    A distinct type because a refusal is not a transport failure and not an
    empty result. `docs/00-plan.md` §7: a refusal that renders as an empty
    chart is the one failure mode most likely to be mistaken for an answer.
    """

    def __init__(self, status: int, detail: str, sql: str | None = None):
        self.status = status
        self.detail = detail
        self.sql = sql
        said = detail or f"HTTP {status}"
        super().__init__(f"The data agent refused this request: {said}")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _quote(name: str) -> str:
    """One spelling for both dialects.

    T-SQL accepts double-quoted identifiers under the default
    QUOTED_IDENTIFIER setting, and PostgreSQL requires them, so brackets buy
    nothing and one rule is easier to be sure about than two.
    """
    return '"' + name.replace('"', '""') + '"'


#: The executor reports engine types (``decimal(19,4)``, ``int(10,0)``,
#: ``varchar(64)``). Arrow is built from THESE and never inferred from the
#: JSON rows -- see docs/00-plan.md §7. A decimal serialises as a JSON number,
#: and inference turns it into a double: a wrong figure, no error, no signal.
_SCALAR_TYPES = {
    "bit": pa.bool_(),
    "bool": pa.bool_(),
    "boolean": pa.bool_(),
    "tinyint": pa.uint8(),
    "smallint": pa.int16(),
    "int": pa.int32(),
    "integer": pa.int32(),
    "bigint": pa.int64(),
    "real": pa.float32(),
    "float": pa.float64(),
    "double": pa.float64(),
    "double precision": pa.float64(),
    "date": pa.date32(),
    "datetime": pa.timestamp("us"),
    "datetime2": pa.timestamp("us"),
    "smalldatetime": pa.timestamp("us"),
    "timestamp": pa.timestamp("us"),
    "timestamp without time zone": pa.timestamp("us"),
    "timestamp with time zone": pa.timestamp("us", tz="UTC"),
    "datetimeoffset": pa.timestamp("us", tz="UTC"),
    "time": pa.time64("us"),
    "uuid": pa.string(),
    "uniqueidentifier": pa.string(),
}
_STRING_PREFIXES = (
    "varchar",
    "nvarchar",
    "char",
    "nchar",
    "text",
    "ntext",
    "string",
    "json",
    "xml",
)
_DECIMAL_PREFIXES = ("decimal", "numeric", "money", "smallmoney")


class UnmappedColumnType(ConnectorError):
    """A declared type with no Arrow equivalent.

    Raised rather than falling back to a string or a double, because a silent
    cast is the failure this loader is built to prevent (§7).
    """

    def __init__(self, column: str, declared: str):
        super().__init__(
            f"column {column!r} has type {declared!r}, which this loader cannot map to Arrow "
            "without guessing. Refusing to guess."
        )


def arrow_type_for(declared: str, column: str = "") -> pa.DataType:
    """Map one declared engine type onto an Arrow type, or refuse."""
    raw = (declared or "").strip().lower()
    base, _, rest = raw.partition("(")
    base = base.strip()
    args = [a.strip() for a in rest.rstrip(")").split(",") if a.strip()]

    if base.startswith(_DECIMAL_PREFIXES):
        # int(10,0) and bigint(19,0) also arrive with precision and scale; only
        # the decimal family becomes a decimal.
        precision = int(args[0]) if args else 38
        scale = int(args[1]) if len(args) > 1 else 0
        return pa.decimal128(precision, scale)
    if base.startswith(_STRING_PREFIXES):
        return pa.string()
    if base in _SCALAR_TYPES:
        return _SCALAR_TYPES[base]
    raise UnmappedColumnType(column or "?", declared)


def _to_array(values: list[Any], field_type: pa.DataType, name: str) -> pa.Array:
    """Build one Arrow array in the DECLARED type.

    `pa.array(values, type=...)` is strict: it raises rather than truncating,
    so a value that does not fit the type the engine declared is an error here
    instead of a wrong number downstream.
    """
    try:
        # Temporal columns cross JSON as ISO-8601 strings -- there is no other
        # way to spell a timestamp in JSON. Arrow will not build a timestamp
        # array from strings directly, so they are cast, which keeps the
        # DECLARED type in charge: a string that is not a timestamp fails here
        # rather than surviving as text in a column the engine calls a date.
        if pa.types.is_temporal(field_type) and any(isinstance(v, str) for v in values):
            return pa.array(values, type=pa.string()).cast(field_type)
        return pa.array(values, type=field_type)
    except (pa.ArrowInvalid, pa.ArrowTypeError, pa.ArrowNotImplementedError) as exc:
        raise ConnectorError(
            f"column {name!r} does not fit its declared type {field_type}: {exc}"
        ) from None


class DataAgentDataLoader(ExternalDataLoader):
    """Browse and read a governed source as the person asking."""

    DISPLAY_NAME = "Data Agent"

    # ------------------------------------------------------------------ setup

    @staticmethod
    def list_params() -> list[dict[str, Any]]:
        """No connection string, and no secret.

        Every built-in loader in Data Formulator takes a host and a credential.
        This one takes a gateway and a source name: the credential is the
        caller's own bearer, and it does not live here (§6). If a connection
        string ever appears in this list, the design has failed.
        """
        return [
            {
                "name": "gateway",
                "type": "string",
                "required": True,
                "default": os.environ.get("DAF_APIM_BASE", "https://localhost:8446"),
                "tier": "connection",
                "description": "API Management base URL for data-agent-service",
            },
            {
                "name": "executor_path",
                "type": "string",
                "required": False,
                "default": os.environ.get("DAF_WAREHOUSE_REST_PATH", "/warehouse-rest"),
                "tier": "connection",
                "description": "The executor's REST route on the gateway",
            },
            {
                "name": "source",
                "type": "string",
                "required": False,
                "default": os.environ.get("DAF_SOURCE", ""),
                "tier": "filter",
                "description": "Which source to browse. Empty browses every SQL source you may see",
            },
            {
                "name": "max_rows",
                "type": "string",
                "required": False,
                "default": os.environ.get("DAF_MAX_ROWS", "10000"),
                "tier": "connection",
                "description": "Row ceiling this loader asks for; the executor applies its own too",
            },
            {
                # `tier: auth` so validate_params(skip_auth_tier=True) does not
                # demand it, and NOT `sensitive` -- because it is not meant to
                # hold a token at all. It names the FILE the broker writes.
                "name": "token_file",
                "type": "string",
                "required": False,
                "default": os.environ.get("DAF_TOKEN_FILE", "./.token"),
                "tier": "auth",
                "description": "Path to the file `make login` writes. Never paste a token here",
            },
            {
                "name": "tls_insecure",
                "type": "string",
                "required": False,
                "default": os.environ.get("DAF_TLS_INSECURE", ""),
                "tier": "connection",
                "description": "Local development only: accept self-signed certificates",
            },
        ]

    @staticmethod
    def auth_instructions() -> str:
        return """**You do not enter a credential here.** This loader reads as *you*: your own
token is carried to the source, and the source's own permissions decide what comes back.

**Sign in:** run `make login` in the `data-agent-formulator` checkout. It performs the
device-code flow against your tenant and writes a short-lived token to the file named in
`token_file` (default `./.token`, mode 0600). Never paste a token into this form —
parameters are persisted with the workspace and a token's lifetime is not the workspace's.

**What you will see:** only the sources, tables and columns your roles allow. A table
you may not read is refused with the reason, not silently returned empty.

**`service`-tier sources** are marked as such in the table list. For those the engine
cannot tell callers apart, and the gateway's roles are the entire control.

**Troubleshooting:** `401` means the token expired — run `make login` again. `403` is a
real permission decision and names what was denied."""

    def __init__(self, params: dict[str, Any]):
        self.params = dict(params or {})
        self.gateway = str(self.params.get("gateway") or "").rstrip("/")
        self.executor_path = str(self.params.get("executor_path") or "/warehouse-rest")
        self.source = str(self.params.get("source") or "").strip()
        self.token_file = str(self.params.get("token_file") or "./.token")
        self.tls_insecure = _truthy(str(self.params.get("tls_insecure") or ""))
        try:
            self.max_rows = int(str(self.params.get("max_rows") or "10000"))
        except ValueError:
            self.max_rows = 10000

    # ------------------------------------------------------------- transport

    @property
    def base(self) -> str:
        return self.gateway + self.executor_path

    def _token(self) -> str:
        """The caller's bearer, read per call and held nowhere.

        `DAF_BEARER` is honoured first so a harness can supply a token without
        writing one to disk; otherwise the file the broker wrote.
        """
        env = os.environ.get("DAF_BEARER", "").strip()
        if env:
            return env
        path = pathlib.Path(self.token_file).expanduser()
        if not path.exists():
            raise ExecutorRefusal(
                401,
                f"no token at {path} — run `make login` in the data-agent-formulator checkout",
            )
        return path.read_text().strip()

    def _ctx(self) -> ssl.SSLContext | None:
        if not self.tls_insecure:
            return None
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _call(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        sql: str | None = None,
    ) -> dict[str, Any]:
        """One executor call. Refusals raise; they never return empty."""
        url = self.base + path
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v})
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": "Bearer " + self._token()}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120, context=self._ctx()) as resp:
                payload = resp.read().decode()
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            detail = raw
            if raw.lstrip().startswith("{"):
                with contextlib.suppress(ValueError):
                    detail = str(json.loads(raw).get("detail") or raw)
            raise ExecutorRefusal(exc.code, detail, sql) from None
        except urllib.error.URLError as exc:
            raise ConnectorError(
                f"Cannot reach the data agent at {self.base}: {exc.reason}"
            ) from None
        # `parse_float=Decimal` is half of the decimal rule. Python's json
        # would otherwise produce a float here, and no amount of care about the
        # Arrow schema afterwards can recover the digits it dropped.
        return (
            json.loads(payload, parse_float=decimal.Decimal)
            if payload.lstrip().startswith(("{", "["))
            else {}
        )

    # -------------------------------------------------------------- browsing

    def test_connection(self) -> bool:
        try:
            self._call("GET", "/sources")
            return True
        except Exception:
            return False

    def sources(self) -> list[dict[str, Any]]:
        """SQL sources this caller may see, in the order the executor gave them.

        HTTP sources are dropped rather than shown as empty tables: they use
        `list_operations`/`call_operation`, which is a different shape that
        `list_tables` cannot describe honestly (§4).
        """
        payload = self._call("GET", "/sources")
        wanted = self.source
        return [
            s
            for s in payload.get("sources", [])
            if s.get("surface", "sql") == "sql" and (not wanted or s.get("name") == wanted)
        ]

    def list_tables(self, table_filter: str | None = None) -> list[dict[str, Any]]:
        """Every table this caller may see, with its columns and its tier.

        `row_count` is deliberately absent. It would be one `COUNT(*)` per
        table on every browse — a warehouse-sized cost for a UI hint nobody
        asked for (§4). Data Formulator renders its absence as unknown.
        """
        results: list[dict[str, Any]] = []
        for src in self.sources():
            name = src.get("name", "")
            tier = src.get("authzTier", "unknown")
            listing = self._call("GET", "/tables", query={"source": name})
            for table in listing.get("tables", []):
                qualified = (
                    table.get("qualifiedName") or f"{table.get('schema')}.{table.get('name')}"
                )
                label = f"{name}.{qualified}"
                if table_filter and table_filter.lower() not in label.lower():
                    continue
                results.append(
                    {
                        "name": label,
                        "path": [name, table.get("schema", ""), table.get("name", "")],
                        "metadata": self._table_metadata(name, qualified, tier),
                    }
                )
        self.ensure_table_keys(results)
        return results

    def _table_metadata(self, source: str, qualified: str, tier: str) -> dict[str, Any]:
        """Columns as the executor reports them for THIS caller.

        A column the access rules deny is not listed, so the model that writes
        transformations never sees a field the person could not have read.
        """
        try:
            described = self._call(
                "GET", "/tables/" + urllib.parse.quote(qualified), query={"source": source}
            )
        except ExecutorRefusal as refusal:
            # Browsing must survive one refused table; the refusal is recorded
            # on the entry rather than thrown away or turned into an empty one.
            return {
                "columns": [],
                "source_metadata_status": "partial",
                "description": f"Refused: {refusal.detail}",
                "authz_tier": tier,
            }
        columns = [
            {
                "name": col.get("name", ""),
                "type": col.get("type", ""),
                "nullable": col.get("nullable", True),
            }
            for col in described.get("columns", [])
        ]
        meta: dict[str, Any] = {
            "columns": columns,
            "source_metadata_status": "synced" if columns else "partial",
            "authz_tier": tier,
        }
        if tier == "service":
            # Said where a person will meet it, not only in the documents. For a
            # service-tier source the engine cannot tell callers apart.
            meta["description"] = (
                "service tier: the engine cannot tell callers apart; "
                "the gateway's roles are the entire control"
            )
        return meta

    # ------------------------------------------------------------- fetching

    def _split(self, source_table: str) -> tuple[str, str]:
        """`source.schema.table` -> (source, `schema.table`).

        `list_tables` labels every entry with its source because a browse may
        span several, so a name that came from there always has three parts.
        A two-part name is accepted and resolved against the pinned source.
        """
        parts = [p for p in (source_table or "").split(".") if p]
        if len(parts) >= 3:
            return parts[0], ".".join(parts[1:])
        if self.source:
            return self.source, ".".join(parts)
        raise ConnectorError(
            f"{source_table!r} does not name its source, and no source is pinned in the "
            "loader's parameters"
        )

    def _columns_for(self, source: str, qualified: str) -> list[dict[str, Any]]:
        described = self._call(
            "GET", "/tables/" + urllib.parse.quote(qualified), query={"source": source}
        )
        columns = described.get("columns", [])
        if not columns:
            raise ConnectorError(
                f"{qualified} in {source} reports no columns you may read; nothing to import"
            )
        return columns

    def _statement(
        self, qualified: str, columns: list[dict[str, Any]], dialect: str, opts: dict[str, Any]
    ) -> str:
        """One read-only SELECT, generated for the source's declared dialect.

        The projection is always explicit. `SELECT *` would leave the column
        set to the engine, and the whole point is that the executor already
        decided it for this caller -- a column that is not in the description
        is one this person may not read, and it must not appear in the text of
        the statement at all.

        The row ceiling is spelled differently per dialect: T-SQL has no
        `LIMIT`. The executor applies its own ceiling regardless; this one
        stops a browse from asking for a warehouse.
        """
        wanted = [c["name"] for c in columns]
        requested = [c for c in (opts.get("columns") or []) if c in set(wanted)]
        projection = ", ".join(_quote(c) for c in (requested or wanted))

        size = min(int(opts.get("size") or self.max_rows), self.max_rows, MAX_IMPORT_ROWS)

        where = build_source_filter_where_clause_inline(
            opts.get("source_filters") or [], quote_char='"', dialect=dialect
        ) or build_where_clause_inline(opts.get("conditions") or [], quote_char='"')

        order = ""
        sort_columns = [c for c in (opts.get("sort_columns") or []) if c in set(wanted)]
        if sort_columns:
            direction = "DESC" if str(opts.get("sort_order", "asc")).lower() == "desc" else "ASC"
            order = " ORDER BY " + ", ".join(f"{_quote(c)} {direction}" for c in sort_columns)

        table = ".".join(_quote(part) for part in qualified.split("."))
        clause = f" {where}" if where else ""
        if dialect == "tsql":
            return f"SELECT TOP {size} {projection} FROM {table}{clause}{order}"
        return f"SELECT {projection} FROM {table}{clause}{order} LIMIT {size}"

    def fetch_data_as_arrow(
        self, source_table: str, import_options: dict[str, Any] | None = None
    ) -> pa.Table:
        """Rows, read into a schema built from the executor's declared types.

        The order matters and is the point of §7: describe first, build the
        Arrow schema from what the engine says the columns ARE, and only then
        read the rows into it. Inferring from the JSON payload would turn
        `decimal(19,4)` into a double, which is a wrong figure with no error
        attached -- the exact defect the upstream service already paid for once.
        """
        opts = dict(import_options or {})
        source, qualified = self._split(source_table)
        columns = self._columns_for(source, qualified)
        dialect = self._dialect_of(source)

        by_name = {c["name"]: c for c in columns}
        sql = self._statement(qualified, columns, dialect, opts)
        payload = self._call(
            "POST",
            "/query",
            body={"sql": sql, "source": source, "maxRows": self.max_rows},
            sql=sql,
        )

        names = payload.get("columns") or [c["name"] for c in columns]
        fields = []
        for name in names:
            declared = (by_name.get(name) or {}).get("type", "")
            field_type = arrow_type_for(declared, name)
            nullable = bool((by_name.get(name) or {}).get("nullable", True))
            fields.append(pa.field(name, field_type, nullable=nullable))
        schema = pa.schema(fields)

        rows = payload.get("rows") or []
        columnar = [[row[i] if i < len(row) else None for row in rows] for i in range(len(names))]
        arrays = [
            _to_array(values, field.type, field.name)
            for values, field in zip(columnar, schema, strict=True)
        ]
        return pa.Table.from_arrays(arrays, schema=schema)

    def _dialect_of(self, source: str) -> str:
        for candidate in self.sources():
            if candidate.get("name") == source:
                return str(candidate.get("dialect") or "tsql")
        raise ConnectorError(f"no source named {source!r} that you may see")
