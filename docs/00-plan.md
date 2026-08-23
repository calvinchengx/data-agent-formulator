# The plan

What this repository is for, what it will build, and the order it builds it
in. Every claim here is either witnessed in [`parity.md`](parity.md) or marked
as a decision that has not been checked yet — and the second kind is marked
in the text, not only in the ledger.

## 1. The one claim

**A question asked in Data Formulator does not produce the wrong winner.**

`data-agent-service`'s README opens on a measurement: on its own seeded data,
inferring *resolution time* from elapsed hours names Frontline as the fastest
support team. The business's definition — which excludes hours spent waiting
on the customer — names Billing. A general-purpose tool pointed at that
warehouse gets it wrong fluently, and nothing in the output says so.

Data Formulator is exactly such a tool: a model writes the transformation and
the chart from the column names it can see. This repository exists to find out
whether attaching it to a governed substrate is enough to change that answer,
and to say honestly if it is not.

Everything below is in service of that one row, which is red today.

## 2. What is inherited, and what is not

The upstream `docs/03-architecture.md` draws a boundary: **authority below
MCP, judgement above.** The executor carries authority. The agent carries
judgement. This repository attaches Data Formulator *below* that line.

| | |
|---|---|
| **Inherited from the executor** | Who the caller is, all the way to the engine. Whether a statement is one read-only `SELECT`. Which schemas exist for this caller. How many rows may come back. That a refusal is a refusal |
| **Not inherited** | What any of it *means*. Data Formulator brings its own model, writes its own transformations, and derives its own fields in DuckDB after the rows arrive |

That is the honest shape, and it is different from `data-agent-voice`, which
is a client of `/ask` and inherits the agent's judgement too. Voice is a new
mouth on the same brain; this is a new brain on the same hands.

Section 8 is about narrowing the second column — carrying enough of the
catalog into what the model reads that the wrong derivation is not the
convenient one. It cannot close it. A tool that can write arbitrary
transformations can always write a wrong one.

## 3. The interface, as read

`ExternalDataLoader` is an ABC with four required members and a large
concrete tail:

```python
@abstractmethod
def __init__(self, params: dict[str, Any]): ...


@staticmethod
@abstractmethod
def list_params() -> list[dict[str, Any]]: ...


@abstractmethod
def list_tables(self, table_filter: str | None = None) -> list[dict[str, Any]]: ...


@abstractmethod
def fetch_data_as_arrow(
    self, source_table: str, import_options: dict[str, Any] | None = None
) -> pa.Table: ...
```

Concrete on the base and inherited for free: `fetch_data_as_dataframe()`,
`ingest_to_workspace()`, `validate_params()`, `catalog_hierarchy()`, `ls()`,
`list_tables_tree()`, `get_column_types()`, `probe()`, `test_connection()`.
Module helpers: `apply_import_projection()`, `build_where_clause()`,
`build_where_clause_inline()`.

Discovery is out of tree. `data_loader/__init__.py` scans `DF_PLUGIN_DIR`
(then `DATA_FORMULATOR_HOME/plugins`, then `~/.data_formulator/plugins`) for
`*_data_loader.py` and derives the registry key from the filename, so
`data_agent_data_loader.py` registers as `data_agent`. A plugin may not
override a built-in key; the collision is rejected and logged, deliberately,
because a plugin shadowing `mssql` would be a credential-exfiltration path.

> **Unchecked.** This was read from `main`. The pin in §11 is `0.7.0`, the
> latest stable release, and `main` is ahead of it. The first commit of the
> loader must re-read the ABC **from the installed pin** and correct this
> section if it differs. A design written against a branch and shipped against
> a release is the same class of error as a runbook naming parameters that do
> not exist.

## 4. The mapping

The four abstract members land on four executor calls. This is why the design
is small: the shapes already agree.

| Loader member | Executor call | Notes |
|---|---|---|
| `test_connection()` | `GET /sources` | also tells the loader whether a source speaks SQL or HTTP |
| `list_tables(filter)` | `GET /sources`, `GET /tables` | "as the asking user may see them" — the filter is applied to what came back, never used to widen it |
| table `metadata` | `GET /tables/{qualified_name}` | columns, types, keys. **The source of the Arrow schema** — see §7 |
| `fetch_data_as_arrow()` | `POST /query` `{sql, source, maxRows}` | one read-only `SELECT`, built from `import_options` |

`list_tables()` is required to return `{"name", "metadata": {row_count,
columns, sample_rows}}`. Two of those need thought:

* **`row_count`** is not free. `GET /tables/{qualified_name}` gives columns and
  types; a count is a query, and doing one per table on every browse is a
  warehouse-sized cost for a UI hint. Decision: report `row_count` as unknown
  rather than issue `COUNT(*)` per table. A number nobody asked for is not
  worth a query the caller did not intend.
* **`sample_rows`** *is* a query — `SELECT … LIMIT n` under the caller's
  identity, so a caller who may not read the table gets a refusal at browse
  time rather than at fetch time. That is the right moment for it.

Only SQL sources are in scope for phase 1. An HTTP source uses
`list_operations` / `call_operation`, which is a different shape and does not
fit `list_tables` honestly; the loader reports HTTP sources as present and not
loadable rather than pretending.

## 5. Which surface

**The REST contract, through `/warehouse-rest`.** The gateway routes
`/warehouse/mcp` and `/warehouse-rest` to the same executor, and the second
exists, in upstream's own words, "for non-MCP clients & load tests". A data
loader is a non-MCP client.

Two reasons beyond fit. The REST contract is `services/contract/openapi.json`
with 21 conformance checks that **both** executors pass, so the loader cannot
accidentally depend on the Python one. And MCP would mean a session, a
lifecycle and a tool-description surface inside a function whose whole job is
to return a table.

> **Unchecked, and load-bearing.** Upstream documents that a *synthesised* MCP
> call loses the caller's headers, which is why the executor speaks MCP
> itself. `/warehouse-rest` is documented as a route, not as a synthesis, so
> the bearer should pass through — but "should" is the word that costs days.
> The first witness this repository records is: **a token that identifies
> user A, sent to `/warehouse-rest`, produces user A's rows and not user B's.**
> Nothing else is built until that passes. If it does not, the loader speaks
> MCP after all and §5 is rewritten.

## 6. Identity

The caller's own bearer, and no other credential. Two consequences shape the
design more than anything else in this document.

**No warehouse credential exists here.** Data Formulator's built-in loaders
take a connection string. This one takes a gateway URL and a source name. If a
connection string ever appears in `list_params()`, the design has failed.

**The token must not be a `param`.** Data Formulator persists loader params so
a session can be reopened. A bearer in that store is a bearer on disk, in a
file whose lifetime is the workspace's rather than the token's. So:

* `list_params()` declares the gateway base, the executor path, the source
  name, the tenant and client id, and the row ceiling. **No secret.**
* The token comes from a broker outside Data Formulator: `make login` runs the
  device-code flow against the tenant (the family's shape for a CLI — upstream
  `docs/03-architecture.md`, "device code for CLIs") and writes the result to
  `DAF_TOKEN_FILE`, mode `0600`. The loader reads it per call and holds it in
  memory only.
* Expiry needs no rule. An expired token is refused by the executor with a 401
  and the loader surfaces it as a refusal to re-authenticate. Authority
  expires where it always did; the loader is not a grant.

**`authz_tier` is reported, not assumed.** `GET /sources` says whether a
source is `user` or `service` tier. A `service`-tier source — a DuckDB source
always, a PostgreSQL with no Entra trust often — means the engine cannot tell
callers apart and the gateway's roles are the entire control. The loader shows
the tier in the table listing. A person exploring should be able to see, on
the screen, which of the two they are in.

## 7. The four hazards

These are the failure modes worth designing against, in the order they will
bite.

**A decimal must not become a double.** `POST /query` returns JSON rows.
`pa.Table.from_pylist` infers types from values, and a decimal arrives as a
float — a wrong number, no error, no signal, and a chart that looks right.
This repository has the receipt: G8 upstream was a decimal read as a double,
misattributed twice before anyone measured it, and the cause was column
metadata rather than the aggregation. So the rule is structural: **the Arrow
schema is constructed from `GET /tables/{qualified_name}` and the rows are
read into it.** Never inferred. A column whose declared type has no Arrow
equivalent is an error at fetch time, not a silent cast.

**A refusal must not arrive as zero rows.** The executor refuses — a denied
column, a schema outside the allow-list, an expired token. Returning an empty
`pa.Table` renders in Data Formulator as an empty chart, which a person reads
as "nothing matched". That is the one thing the upstream ask contract forbids
its clients from doing, and it applies here for the same reason. Refusals
raise through Data Formulator's `connector_errors` so the UI says *refused*,
with the executor's own reason.

**`import_options` must produce SQL the guard accepts.** Columns, filters,
sort and size arrive as a dict and become a `WHERE` clause via upstream's own
`build_where_clause()`. The executor's guard is a parser, not a pattern
matcher, and it will refuse anything that is not one read-only `SELECT` inside
the allow-list. The loader's job is to generate within that, and the witness
is a corpus: every shape `import_options` can take, sent to the executor, and
none refused. Where the executor legitimately refuses — a filter on a denied
column — the refusal is the correct outcome and the corpus records it as one.

**The workspace cache is `service` tier.** `ingest_to_workspace()` writes
parquet after a fetch. The fetch ran as the caller; the parquet does not carry
them, and anything that reads the workspace afterwards reads it with no
identity check. That is not a defect to fix — it is what a workspace is — but
it is a claim that must be labelled rather than left to be assumed. Upstream
labels Superset `service` for the same honesty. It goes in `parity.md`, in
`SECURITY.md`, and in the loader's own description text where the person
choosing it will meet it.

## 8. Semantics: narrowing the gap

The model that writes Data Formulator's transformations reads column names and
sample rows. Give it more and the convenient derivation stops being the wrong
one.

**Phase 1 — definitions in the metadata.** `list_tables()` returns a
`metadata` dict, and its `columns` entries are what the model sees. Where the
catalog holds a description or a glossary term for a column, it goes there. A
model reading `resolution_hours — excludes time awaiting customer response`
is in a different position from one reading `resolution_hours`. This is cheap
and it is not sufficient.

**Phase 2 — metrics as columns.** A second loader whose "tables" are not
warehouse tables but the promoter's released templates. `list_tables()` lists
released candidates; `fetch_data_as_arrow()` runs `plan.comparison_sql`; the
columns are the metrics the catalog defines, already computed correctly. Data
Formulator then derives *over* correct columns instead of raw ones, and the
derivable-but-wrong field is not the nearest thing to hand.

Phase 2 is the honest answer to §1 and phase 1 is not. Phase 1 ships first
because it is the smaller change and because it is what proves the transport.

## 9. What is out of scope

**`/ask`.** It is question → ticket → SSE → one of three terminal events. The
loader ABC is catalog → table → Arrow. Neither fits inside the other, and
Data Formulator's plugin system extends loaders only — an `/ask` panel means
forking the frontend. `data-agent-voice` is the client that consumes `/ask`;
this one consumes the executor.

**Forking Data Formulator.** It is consumed as an installed MIT-licensed
package. If something cannot be done from a plugin, it is reported upstream
and recorded in [`upstream-issues.md`](upstream-issues.md), not patched here.

**Multi-user deployment.** A plugin is arbitrary Python in the Data Formulator
server process, which is why upstream disables plugin scanning by default in
multi-user deployments. This repository does not ask anyone to turn it back
on. See [`../SECURITY.md`](../SECURITY.md).

**Writing anything.** The executor is read-only and there is nothing to
compensate. That is also why cancelling a browse needs no rule.

## 10. The order of work

Each step ends with a row in `parity.md` turning green, or with this document
being wrong and rewritten.

1. **The identity witness.** User A's token to `/warehouse-rest` returns user
   A's rows. Nothing else is built first, because §5 rests on it.
2. **The ABC, re-read from the pin.** Correct §3 against `0.7.0` as installed.
3. **`list_params()` and `test_connection()`.** The loader is discovered from
   `DF_PLUGIN_DIR`, appears in the UI, and connects with no secret in its
   configuration.
4. **`list_tables()`.** Sources, tables, per-table columns and types, tier
   shown, `row_count` unknown, `sample_rows` under the caller's identity.
5. **`fetch_data_as_arrow()`, schema-first.** The decimal witness before the
   happy path: a decimal column arrives as a decimal, and the check fails when
   the schema is inferred instead.
6. **Refusals.** The corpus of `import_options` shapes; a refusal reaching the
   UI as a refusal.
7. **Definitions in metadata** (§8 phase 1).
8. **The wrong-winner question**, asked through Data Formulator, end to end.
   Green or red, this is the row the repository is for.
9. **The emulator witnesses.** Data Formulator's stock `mssql`, `azure_blob`
   and `databricks` loaders against this family's emulators — third-party
   evidence, and failures filed upstream.
10. **The metrics loader** (§8 phase 2).

## 11. Settings

Every key in `.env.example`, and what reads it. A key here that the template
lacks — or a key in the template named nowhere — fails `make test`.

| Setting | Read by | Meaning |
|---|---|---|
| `DATA_FORMULATOR_VERSION` | the harnesses, and this document | The pin the ABC in §3 must be checked against. `0.7.0` |
| `DF_PLUGIN_DIR` | Data Formulator | Where the loader is discovered. Naming it means the other two discovery locations never decide anything |
| `DATA_FORMULATOR_HOME` | Data Formulator | Deliberately empty. Setting it would give the plugin a second home and a precedence rule between the two |
| `DAS_STACK_NETWORK` | compose | The upstream stack's network, joined rather than recreated |
| `DAF_APIM_BASE` | the loader | The gateway. The only host the loader talks to |
| `DAF_WAREHOUSE_REST_PATH` | the loader | `/warehouse-rest` — the executor's REST route for non-MCP clients (§5) |
| `DAF_WAREHOUSE_MCP_PATH` | the loader, if §5 is rewritten | `/warehouse/mcp`. Present because the fallback in §5 must have a home, not because it is used |
| `DAF_EXECUTOR_SURFACE` | the loader | `rest` or `mcp`. The decision in §5, in one place |
| `DAF_SOURCE` | the loader | Which source to browse. Empty means "ask `GET /sources`" |
| `DAF_TENANT` | `make login` | The tenant the device-code flow authenticates against |
| `DAF_CLIENT_ID` | `make login` | The public client id for that flow |
| `DAF_SCOPE` | `make login` | `api://data-agent-service/access_as_user` |
| `DAF_TOKEN_FILE` | `make login`, the loader | Where the broker writes the token, mode `0600`. Never a Data Formulator param (§6) |
| `DAF_MAX_ROWS` | the loader | The ceiling the loader asks for. The executor applies its own regardless; this one stops a browse from asking for a warehouse |
