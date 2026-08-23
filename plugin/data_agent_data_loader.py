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
import json
import os
import pathlib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import pyarrow as pa
from data_formulator.data_loader.external_data_loader import ExternalDataLoader

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
        return json.loads(payload) if payload.lstrip().startswith(("{", "[")) else {}

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

    def fetch_data_as_arrow(
        self, source_table: str, import_options: dict[str, Any] | None = None
    ) -> pa.Table:
        raise NotImplementedError(
            "phase 2 of docs/00-plan.md: fetching is not built yet. "
            "Browsing works; importing a table does not."
        )
