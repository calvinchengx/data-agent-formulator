# Parity — what is witnessed, and where

Two columns, because they are different claims. **Witnessed locally** means a
check in this repository runs and passes; the check is named, so a green row
can always be re-run. **Witnessed running** means the same claim has been
watched holding with Data Formulator open in a browser against a live
upstream stack.

> Only the scaffold's own rows are green, and they are about files agreeing
> with each other. There is no loader in this repository. The rows describe a design and the
> checks that will hold it; they stop at exactly the line they can prove.
>
> The family precedent for keeping this ledger honest is `data-agent-service`
> discovering that a runbook naming three parameters which did not exist reads
> as deployable. The fix was not a better runbook but a check comparing the
> runbook to the definition. The scaffold rows below are that check.

## The scaffold

| Capability | Witnessed locally | Check | Witnessed running |
|---|---|---|---|
| Every setting the documents name exists in `.env.example` | 🟢 | `make test` | n/a |
| Every key in the template is named by a document | 🟢 — `docs/00-plan.md` §11 is the table it is held to | `make test` | n/a |
| No row here is marked green without naming a check that produces it | 🟢 | `make test` | n/a |
| The four executor calls this design rests on exist in the upstream contract, checked against `services/contract/openapi.json` rather than against memory | 🟢 | `make test` — skips visibly when the sibling checkout is absent | n/a |

## The design's own decisions, now checked

Both were written into the plan as unchecked. Both have been run, and both
moved the plan.

| Decision | Witnessed locally | Check | Witnessed running |
|---|---|---|---|
| The caller's bearer survives the gateway's `/warehouse-rest` route (§5) | 🟢 **run** — one statement, three seeded identities, three different outcomes: a column refusal by role name, the same column read, and a workspace refusal for a principal with no role | `make test` — `tests/test_identity_witness.py`, against a live stack; skips visibly without one | n/a — this is the transport, not the UI |
| The `ExternalDataLoader` interface in §3 is the pinned release's, not `main`'s | 🟢 — and it was wrong in four ways: `auth_instructions` is a fifth abstract member, `apply_import_projection` and `probe` do not exist at the pin, and a plugin **wins** a key collision here rather than being rejected | `make test` — `tests/test_interface_pin.py` introspects the installed package | n/a |

## Signing in

| Capability | Witnessed locally | Check | Witnessed running |
|---|---|---|---|
| Every `make` target a document names exists — the rule that would have caught `make login` being named in three places before it was written | 🟢 | `make test` | n/a |
| The tenant issues a device code, and an unfinished sign-in reads as *pending* rather than as a failure | 🟢 **run** | `make test` | n/a |
| The token file is `0600`, set before the bytes are written rather than after | 🟢 **on POSIX only** — Windows does not implement these bits, and `scripts/login.py` says so rather than implying a guarantee it cannot keep. The check skips there with that reason | `make test` | n/a |
| The broker names the identity it signed in as, without trusting the token to authorize anything | 🟢 | `make test` | n/a |
| **A person completes the sign-in and the loader reads the token** | 🔴 **not run** — the emulator's `verification_uri` names its in-network hostname, which a workstation browser cannot resolve (`upstream-issues.md` 2). The witnesses above stop exactly where a browser would start | — | not yet |

## The loader

| Capability | Witnessed locally | Check | Witnessed running |
|---|---|---|---|
| The plugin is discovered from `DF_PLUGIN_DIR` with no fork of Data Formulator and no patched file | 🟢 | `make test` | 🟢 **run** — `make serve`, then `/api/data-loaders` reports both loaders with `source: plugin` and `disabled: none` |
| `list_tables()` returns what the executor says this caller may see, and nothing else | 🟢 **run** — the analyst's column set for `dbo.dim_customer` is a strict subset of the finance role's, and `email` is the difference | `make test` | 🟢 **run** — the app's own `/api/connectors/get-catalog` renders the columns, the catalog description and the service-tier note |
| `fetch_data_as_arrow()` sends one read-only `SELECT` and the executor accepts it | 🟢 **run** — seven `import_options` shapes, each fetched through the guard | `make test` | 🟢 **run** — imported through the app; 500 rows came back where 2000 were asked for, because the executor's own ceiling is the one that counts |
| A temporal column arrives as a timestamp rather than as text — cast from ISO-8601, never left as a string | 🟢 **run** — found while building, not while planning | `make test` | not yet |
| A decimal column arrives as a decimal — the Arrow schema is built from the executor's declared types, never inferred from JSON rows | 🟢 **run** — `decimal(19,4)` arrives as `decimal128(19,4)` holding `Decimal`s, and a companion check shows inference would have produced `float64` | `make test` | 🟢 **run** — the parquet Data Formulator wrote holds `decimal128(19, 4)` and `Decimal('3856.7174')`. It survives the application's own ingest |
| A refusal reaches the UI as a refusal, never as an empty chart | 🟢 — a principal with no role raises `ExecutorRefusal` carrying the executor's own reason; a missing token raises one naming `make login` | `make test` | not yet — the UI half needs a browser |
| `import_options` — columns, filters, sort, size — becomes SQL the executor's guard accepts rather than refuses | 🟢 **run** — seven shapes, both dialects. T-SQL gets `TOP`, PostgreSQL gets `LIMIT`; a denied column never enters the statement and `SELECT *` is never generated | `make test` | not yet |
| No warehouse credential exists in Data Formulator's configuration; the only secret is the caller's own bearer | 🟢 — `list_params()` declares no password, DSN or token, and marks nothing `sensitive` | `make test` | 🟢 **run** — the connector Data Formulator persisted to disk holds the gateway, the source and the *path* to a token file. No secret is in it |
| The parquet Data Formulator writes after a fetch is recorded at `service` tier, and the documents say so where a reader will meet it | 🔴 not yet | — | not yet |

## Semantics

| Capability | Witnessed locally | Check | Witnessed running |
|---|---|---|---|
| Column metadata carries the catalog's stated definition, so the model writing the transformation sees the meaning and not only the name | 🟢 **run** — `elapsed_minutes` reaches the metadata carrying *NOT the answer to 'how long did we take'*, unescaped | `make test` | not yet |
| A metric that the catalog defines is present as a column, so the derivable-but-wrong field is not the only one to hand | 🟢 on this data — `resolution_minutes` is a real column beside `elapsed_minutes`. It is **not** general: where a metric is a formula rather than a column, §8 phase 2 is the answer and it is not built | `make test` | not yet |
| The reversal is real on this data, measured through this loader | 🟢 **run** — ranked by wall-clock, one team is fastest; ranked by the business's definition, a different one is. Measured, not quoted from upstream's README | `make test` | n/a |
| The metadata states the difference well enough that a model *could* avoid it | 🟢 — the definition says which figure to report, in the text the model reads | `make test` | not yet |
| **The wrong-winner question, asked through Data Formulator, does not produce the wrong winner** | 🔴 **not run** — the browser half is done: the app runs, both loaders register, and the governed tables import. What is missing is a **model**. Data Formulator gates its whole UI behind model selection and no API key is available here, so no chart has been drawn and no transformation has been generated | — | not yet |
| A browse survives a catalog that is down, and says definitions are missing rather than showing none | 🟢 | `make test` | not yet |

## Data Formulator against the emulators

Third-party evidence: Data Formulator's own connectors, unmodified, against
this family's emulators. A pass is evidence produced by code that has never
heard of them; a failure is a parity gap with a reproducer attached and
belongs in [`upstream-issues.md`](upstream-issues.md).

| Connector | Emulator | Witnessed locally | Witnessed running |
|---|---|---|---|
| `mssql_data_loader` | `fabric-emulator` (+ SQL Server) | 🔴 **blocked, not failed** — this machine's ODBC stack cannot connect to a SQL Server the executor queries fine (`upstream-issues.md` 4). Separately, the connector's own connection string is invalid on Driver 18 (`upstream-issues.md` 3), reproduced with raw `pyodbc` | — | not yet |
| `azure_blob_data_loader` | `azure-emulators` | 🔴 not yet | not yet |
| `databricks_data_loader` | `databricks-emulator` | ⚫ **not applicable at the pin** — `data_formulator==0.7.0` has no Databricks connector; it lands after this release. Waiting on the pin, not on the emulator | — | n/a |

## Released metrics (§8 phase 2)

| Capability | Witnessed locally | Check | Witnessed running |
|---|---|---|---|
| Tables are the promoter's released templates, and the measure is computed by the warehouse | 🟢 **run** — `SUM(revenue_usd)` arrives as `decimal128(38, 4)` holding exact `Decimal`s | `make test` | 🟢 **run** — imported through the app; the stored parquet is `decimal128(38, 4)` |
| The raw column the wrong derivation would need is **not** offered beside the metric | 🟢 — this is the property `data_agent` cannot have | `make test` | not yet |
| A slot value is never chosen for the person: each becomes its own table, with the binding visible in the name | 🟢 **run** — two fiscal years, two tables | `make test` | not yet |
| An aggregate is typed from what it aggregates, and an untypeable one is refused | 🟢 | `make test` | n/a |
| A released template is not a way around the executor: it still runs as the caller | 🟢 **run** — a principal with no role is refused the released statement too | `make test` | not yet |
| The promoter's "degraded title" warning is passed on rather than smoothed | 🟢 | `make test` | not yet |
| Released candidates come from an API rather than the promoter's output file | 🔴 **not built anywhere** — no upstream surface serves them (`upstream-issues.md` 1 is the related gap). The path is configuration, and this loader is only as fresh as the last promoter run | — | n/a |

## Not measured, and why

There is no coverage figure. This repository has no product code yet, so a
percentage would be measured over its own gates — a number about the tests,
reported as though it were about the loader. It appears when the loader does.
