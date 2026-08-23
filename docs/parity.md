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

## The loader

| Capability | Witnessed locally | Check | Witnessed running |
|---|---|---|---|
| The plugin is discovered from `DF_PLUGIN_DIR` with no fork of Data Formulator and no patched file | 🟢 — Data Formulator's own registry, run out of process, reports `data_agent` under `PLUGIN_LOADERS`; an empty plugin dir reports nothing | `make test` | not yet |
| `list_tables()` returns what the executor says this caller may see, and nothing else | 🟢 **run** — the analyst's column set for `dbo.dim_customer` is a strict subset of the finance role's, and `email` is the difference | `make test` | not yet |
| `fetch_data_as_arrow()` sends one read-only `SELECT` and the executor accepts it | 🔴 not yet — phase 2. It raises `NotImplementedError` naming the phase rather than returning an empty table | `make test` witnesses the refusal to pretend | not yet |
| A decimal column arrives as a decimal — the Arrow schema is built from the executor's declared types, never inferred from JSON rows | 🔴 not yet | — | not yet |
| A refusal reaches the UI as a refusal, never as an empty chart | 🔴 not yet | — | not yet |
| `import_options` — columns, filters, sort, size — becomes SQL the executor's guard accepts rather than refuses | 🔴 not yet | — | not yet |
| No warehouse credential exists in Data Formulator's configuration; the only secret is the caller's own bearer | 🟢 — `list_params()` declares no password, DSN or token, and marks nothing `sensitive` | `make test` | not yet |
| The parquet Data Formulator writes after a fetch is recorded at `service` tier, and the documents say so where a reader will meet it | 🔴 not yet | — | not yet |

## Semantics

| Capability | Witnessed locally | Check | Witnessed running |
|---|---|---|---|
| Column metadata carries the catalog's stated definition, so the model writing the transformation sees the meaning and not only the name | 🔴 not yet | — | not yet |
| A metric that the catalog defines is present as a column, so the derivable-but-wrong field is not the only one to hand | 🔴 not yet | — | not yet |
| The wrong-winner question, asked through Data Formulator, does not produce the wrong winner | 🔴 **not run** — this is the claim the repository exists to make, and it is unproven | — | not yet |

## Data Formulator against the emulators

Third-party evidence: Data Formulator's own connectors, unmodified, against
this family's emulators. A pass is evidence produced by code that has never
heard of them; a failure is a parity gap with a reproducer attached and
belongs in [`upstream-issues.md`](upstream-issues.md).

| Connector | Emulator | Witnessed locally | Witnessed running |
|---|---|---|---|
| `mssql_data_loader` | `fabric-emulator` (+ SQL Server) | 🔴 not yet | not yet |
| `azure_blob_data_loader` | `azure-emulators` | 🔴 not yet | not yet |
| `databricks_data_loader` | `databricks-emulator` | 🔴 not yet | not yet |

## Not measured, and why

There is no coverage figure. This repository has no product code yet, so a
percentage would be measured over its own gates — a number about the tests,
reported as though it were about the loader. It appears when the loader does.
