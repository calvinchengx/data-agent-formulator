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

## 3. The interface, as read from the pin

> Read from `data_formulator==0.7.0`, the pin in §11, and held there by
> `tests/test_interface_pin.py` — which introspects the installed package
> rather than trusting this prose. The first draft of this section was read
> from `main` and was wrong in four ways by the time it met the release. The
> corrections are noted inline, because *what* moved is more useful to a
> future reader than a section that was always right.

`ExternalDataLoader` is an ABC with **five** required members:

```python
@abstractmethod
def __init__(self, params: dict[str, Any]): ...


@staticmethod
@abstractmethod
def list_params() -> list[dict[str, Any]]: ...


@staticmethod
@abstractmethod
def auth_instructions() -> str: ...  # ← the plan missed this one


@abstractmethod
def list_tables(self, table_filter: str | None = None) -> list[dict[str, Any]]: ...


@abstractmethod
def fetch_data_as_arrow(
    self, source_table: str, import_options: dict[str, Any] | None = None
) -> pa.Table: ...
```

Concrete on the base and inherited: `fetch_data_as_dataframe()`,
`ingest_to_workspace()`, `validate_params()`, `get_safe_params()`,
`delegated_login_config()`, `catalog_hierarchy()`, `ls()`,
`list_tables_tree()`, `get_column_types()`, `search_catalog()`,
`test_connection()`. A `DISPLAY_NAME` class attribute overrides the
title-cased registry key in the UI.

Module helpers for turning `import_options` into SQL: `build_where_clause()`,
`build_where_clause_inline()`, `build_source_filter_where_clause_inline()`,
`sanitize_table_name()`. **`apply_import_projection()` does not exist at the
pin** — it is a `main`-only helper, and the first draft named it. Neither does
`probe()`.

Three things the pin offers that the design is better for:

* **`validate_params(params, skip_auth_tier=True)`.** A parameter declared
  `tier="auth"` is not required up front, "useful for SSO/token flows where
  auth comes externally" in upstream's own words. That is exactly §6's shape,
  and it is a supported one rather than something worked around.
* **`list_params()` entries may declare `sensitive: True`**, and
  `get_safe_params()` strips those before parameters are written into stored
  metadata. Useful, and *not* a reason to relax §6 — see the note there.
* **A plugin may not import its sibling by name.** Data Formulator loads each
  plugin file by path and does *not* add the plugin directory to `sys.path`,
  so `import data_agent_data_loader` from the metrics loader fails at run time
  — the application reports the loader as `disabled` with a pip hint for a
  package that does not exist. A test that patched `sys.path` passed happily
  while the app could not load it at all. The metrics loader now loads its
  sibling by path, and the test asserts the directory is *not* importable
  before it starts.
* **`delegated_login_config()`** returns `{"login_url", "label"}` and gives the
  loader a popup sign-in whose window posts an `access_token` back. Superset's
  bridge uses it. It is the better long-run answer for §6 than a token file,
  and §10 keeps it as step 6b rather than phase 1, because it is a browser
  flow and the token file is twenty lines.

`MAX_IMPORT_ROWS` is `2_000_000` at the module level — a Data Formulator-side
ceiling that exists regardless of what `DAF_MAX_ROWS` asks for.

Discovery is out of tree. `data_loader/__init__.py` scans `DF_PLUGIN_DIR`
(then `DATA_FORMULATOR_HOME/plugins`, then `~/.data_formulator/plugins`) for
`*_data_loader.py` and derives the registry key from the filename, so
`data_agent_data_loader.py` registers as `data_agent`. Scanning is enabled
only in local mode; a hosted deployment must set `DF_ALLOW_PLUGINS=1`
deliberately, "since loading a plugin executes arbitrary Python code in the
server process".

> **A correction with teeth.** The first draft said a plugin may not override
> a built-in key, and that the collision is rejected. That is `main`'s
> behaviour. **At the pin, the plugin wins.** So on 0.7.0 a file dropped into
> the plugin directory *can* shadow `mssql` and receive the connection strings
> a person types into it. Nothing in this repository does that — the key is
> `data_agent` and collides with nothing — but the claim in `SECURITY.md` had
> to be corrected, and the mitigation is the plugin directory being trusted,
> not the loader being well-behaved.

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

> **Checked.** `tests/test_identity_witness.py` sends one statement —
> `SELECT TOP 1 email FROM dbo.dim_customer` — through `/warehouse-rest` under
> three seeded identities, and gets three different answers: Alice
> (`Data.Analyst`) is refused the column by name, Carol (`Data.Finance`) reads
> it, and Bob, who holds no role, is refused the workspace by the source. A
> gateway that had replaced the bearer with one principal would have answered
> all three identically. **The bearer survives the route**, and the surface
> decision stands.

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
  name, the tenant and client id, and the row ceiling. **No secret.** The
  bearer, if it is declared at all, is `tier="auth"` so
  `validate_params(skip_auth_tier=True)` does not demand it up front — the pin
  supports exactly this flow (§3).
* The token comes from a broker outside Data Formulator: `make login` runs the
  device-code flow against the tenant (the family's shape for a CLI — upstream
  `docs/03-architecture.md`, "device code for CLIs") and writes the result to
  `DAF_TOKEN_FILE`, mode `0600`. The loader reads it per call and holds it in
  memory only.
* `get_safe_params()` and `sensitive: True` are **not** the mitigation. They
  keep a declared-sensitive parameter out of stored *metadata*; they do not
  make a parameter store a safe place for a bearer. The token stays out of
  `params` entirely rather than being declared carefully.
* Expiry needs no rule. An expired token is refused by the executor with a 401
  and the loader surfaces it as a refusal to re-authenticate. Authority
  expires where it always did; the loader is not a grant.

**Later, a popup instead of a file.** `delegated_login_config()` gives a
loader its own sign-in window, which is what a person actually wants and what
Superset's bridge already does. It is step 6b in §10 rather than phase 1: a
browser flow against the tenant is a day, and the token file is twenty lines.
The token file is not a stepping stone that has to be removed — both feed the
same "read the bearer, hold it in memory" path.

**`authz_tier` is reported, not assumed.** `GET /sources` says whether a
source is `user` or `service` tier. A `service`-tier source — a DuckDB source
always, a PostgreSQL with no Entra trust often — means the engine cannot tell
callers apart and the gateway's roles are the entire control. The loader shows
the tier in the table listing. A person exploring should be able to see, on
the screen, which of the two they are in.

## 7. The hazards

These are the failure modes worth designing against, in the order they bit.
Four were planned; the fourth below was found while building, which is why the
section is no longer called "the four hazards".

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

**A decimal is exact in the store and a string in the preview.** Found by
running the application, not by testing the loader. Data Formulator's preview
JSON has no decimal type, so `decimal128(19,4)` is serialised as the string
`"3856.7174"` and labelled `string` in the preview pane. The **stored parquet
is `decimal128(19, 4)` holding real `Decimal`s** — nothing is lost, and the
value is exact where it matters. But a person looking at the preview sees a
text column where they expect a number, and the model reading that preview
sees one too.

The temptation is to hand Data Formulator a float so its preview looks right.
That is the G8 mistake with better manners, and this repository does not take
it. The decimal stays a decimal and the consequence is written down here.

**A timestamp is a string on the wire, and must not stay one.** Found while
building phase 2, not while planning it: JSON has no way to spell a timestamp,
so the executor sends ISO-8601 text, and Arrow refuses to build a timestamp
array from strings. The wrong fix is to let the column be text — the engine
called it a date and a chart would then sort it lexically. The right one is to
build a string array and *cast* it to the declared type, which keeps the
declaration in charge: a value that is not a timestamp fails at fetch time
instead of surviving as text in a column everything downstream believes is a
date. Same rule as the decimal, arrived at from the other direction.

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

1. ~~**The identity witness.**~~ **Done.** Three identities, one statement,
   three outcomes — `tests/test_identity_witness.py`. §5 stands.
2. ~~**The ABC, re-read from the pin.**~~ **Done**, and it moved §3 in four
   ways — `tests/test_interface_pin.py` now holds the section to the installed
   package rather than to prose.
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
6b. **A popup instead of a token file** — `delegated_login_config()` against
   the tenant (§6). Deferred, not skipped: it changes where the bearer comes
   from and nothing else.
7. ~~**Definitions in metadata**~~ **Done.** One catalog call per browse,
   indexed by matching FQN endings because the database segment is the
   engine's and is not derivable from anything the executor reports.
8. **The wrong-winner question**, asked through Data Formulator, end to end.
   The two halves that can be checked without a model are done and green: the
   reversal is real on this data measured through the loader, and the
   definition that prevents it reaches the metadata. What is left is a person,
   a browser and a key — and that is the row the repository is for.
9. **The emulator witnesses.** Data Formulator's stock `mssql` and
   `azure_blob` loaders against this family's emulators — third-party
   evidence, and failures filed upstream. **Not `databricks`:** the pin has no
   `databricks_data_loader.py`; it arrives after 0.7.0. That row waits for the
   pin to move rather than for the emulator.
10. ~~**The metrics loader**~~ **Done**, with one seam left open: there is no
    API that serves released candidates, so it reads the promoter's output
    file by configured path. That is recorded rather than hidden.

## 11. Settings

Every key in `.env.example`, and what reads it. A key here that the template
lacks — or a key in the template named nowhere — fails `make test`.

| Setting | Read by | Meaning |
|---|---|---|
| `DATA_FORMULATOR_VERSION` | the harnesses, and this document | The pin the ABC in §3 must be checked against. `0.7.0` |
| `DF_ALLOW_PLUGINS` | Data Formulator | Empty. Scanning is on in local mode already; setting it is how a *hosted* deployment opts in, and this repository does not ask anyone to |
| `DF_PLUGIN_DIR` | Data Formulator | Where the loader is discovered. Naming it means the other two discovery locations never decide anything |
| `DATA_FORMULATOR_HOME` | Data Formulator | Deliberately empty. Setting it would give the plugin a second home and a precedence rule between the two |
| `DAS_STACK_NETWORK` | compose | The upstream stack's network, joined rather than recreated |
| `DAF_APIM_BASE` | the loader | The gateway, as a workstation sees it — the host-published port, not the in-network one |
| `DAF_TLS_INSECURE` | the loader, the witnesses | Local development only. The emulator family serves self-signed certificates |
| `DAF_AUTHORITY` | `make login`, the witnesses | The tenant's token endpoint host |
| `DAF_WAREHOUSE_REST_PATH` | the loader | `/warehouse-rest` — the executor's REST route for non-MCP clients (§5) |
| `DAF_WAREHOUSE_MCP_PATH` | the loader, if §5 is rewritten | `/warehouse/mcp`. Present because the fallback in §5 must have a home, not because it is used |
| `DAF_EXECUTOR_SURFACE` | the loader | `rest` or `mcp`. The decision in §5, in one place |
| `DAF_CANDIDATES` | the metrics loader | The promoter's released candidates. A file path, because nothing serves them over HTTP |
| `DAF_CATALOG_SOURCE` | the loader | The HTTP source holding the catalog (`om_catalog_api`). Empty browses without definitions |
| `DAF_SOURCE` | the loader | Which source to browse. Empty means "ask `GET /sources`" |
| `DAF_TENANT` | `make login` | The tenant the device-code flow authenticates against |
| `DAF_CLIENT_ID` | `make login` | The public client id for that flow |
| `DAF_SCOPE` | `make login` | `api://data-agent-service/access_as_user` |
| `DAF_TOKEN_FILE` | `make login`, the loader | Where the broker writes the token, mode `0600`. Never a Data Formulator param (§6) |
| `DAF_TEST_PASSWORD` | the witnesses | The seeded personas' password on a local stack. Published upstream, not a secret this repository keeps |
| `DAF_MAX_ROWS` | the loader | The ceiling the loader asks for. The executor applies its own regardless; this one stops a browse from asking for a warehouse |
