# Data Agent Formulator — governed tables, ungoverned exploration

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

**Explore in Data Formulator. Read through the executor, as yourself, one
read-only `SELECT` at a time.**

A [Data Formulator](https://github.com/microsoft/data-formulator) data loader
that fetches through [data-agent-service](https://github.com/calvinchengx/data-agent-service)'s
executor instead of holding a warehouse credential of its own — so an
exploratory charting session inherits on-behalf-of identity, the schema
allow-list, the row ceiling, and a refusal that stays a refusal.

> **Status: scaffold.** There is no loader yet. This repository currently
> holds its own structure, its environment template, and a ledger that says
> so. [`docs/parity.md`](docs/parity.md) has no green rows, and nothing here
> claims a working plugin. The design document is the next commit; the loader
> is the one after that.

## Why this exists

Data Formulator is an exploratory tool: you point it at data and a model
writes the transformation and the chart. Pointed at a warehouse directly it
infers meaning from column names, which is the failure `data-agent-service`
was built around — on that repository's own seeded data, inferring
*resolution time* from elapsed hours names the wrong team, fluently, with
nothing in the chart to say it happened.

So this repository does not point it at a warehouse. It points it at the
executor, which is the part of the upstream service that carries **authority**
rather than judgement: the caller's own token all the way to the engine, one
parsed read-only `SELECT`, a schema allow-list, a row ceiling, and refusals
reported rather than routed around.

What that buys, and what it does not, is worth stating plainly, because the
distinction is the whole design:

- **Inherited.** Who may read what. How much. From where. Whether a query is
  a query at all.
- **Not inherited.** What the numbers *mean*. Data Formulator brings its own
  model and derives its own fields client-side. It sits **below** the
  judgement boundary in the upstream `docs/03-architecture.md`, consuming
  authority while supplying its own judgement.

That makes it a different animal from
[data-agent-voice](https://github.com/calvinchengx/data-agent-voice), which is
a client of `/ask` and inherits the upstream service's judgement too. Naming
the difference is cheaper than discovering it in a chart.

## What is planned

| | |
|---|---|
| **A loader, out of tree** | Data Formulator discovers `*_data_loader.py` from `DF_PLUGIN_DIR`. No fork, no patch, no vendored tree |
| **Semantics carried into the UI** | Column metadata enriched from the catalog, so the model that writes the transformation sees the stated definition and not only the column name |
| **A third-party parity witness** | Data Formulator's *stock* mssql, blob and databricks loaders pointed at `fabric-emulator`, `azure-emulators` and `databricks-emulator` — evidence produced by code that has never heard of them |
| **Honest tiers** | A fetch runs as the user; the parquet Data Formulator writes to its workspace afterwards carries no identity. That cache is recorded at `service` tier, as Superset is upstream |

## Quick start

Nothing to start yet. When there is:

```sh
make doctor   # toolchain, and the upstream stack reachable
make check    # everything CI's quality job runs, in the order it runs it
```

## Upstream

Data Formulator is MIT-licensed (Copyright (c) Microsoft Corporation) and is
consumed as a dependency — installed, not vendored. Defects found in it are
recorded in [`docs/upstream-issues.md`](docs/upstream-issues.md) and reported
there, not worked around here.
