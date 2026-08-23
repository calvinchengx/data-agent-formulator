# Security

## Reporting a vulnerability

Report privately through GitHub, on this repository:
**[Security → Report a vulnerability](https://github.com/calvinchengx/data-agent-formulator/security/advisories/new)**.

That opens a draft advisory visible only to you and the maintainer. Please do
not open a public issue for a security report.

## What this project is, and what that means for scope

**This is a workstation tool, not a service.** It is a Data Formulator plugin
that reads through `data-agent-service`'s executor. Two facts set the bar, and
both cut against running it multi-user:

- **A Data Formulator plugin is arbitrary Python in the Data Formulator server
  process.** Scanning is on in local mode and a hosted deployment must set
  `DF_ALLOW_PLUGINS=1` deliberately. This repository does not ask anyone to.
  A single-user, single-machine posture is the intended one.
- **At the pinned release, a plugin may shadow a built-in loader.** On
  `data_formulator==0.7.0` a plugin key that collides with a built-in one
  wins, so a file in the plugin directory can replace `mssql` and receive the
  connection strings typed into it. (`main` later reverses this and rejects
  the collision.) Nothing here does that — the key is `data_agent` — but it
  means **the plugin directory is a trust boundary**, and the mitigation is
  controlling what is in it rather than this loader being well-behaved.
- **Data Formulator brings its own model and derives its own fields.** It
  consumes the executor's authority — the caller's identity, the read-only
  guard, the allow-list, the row ceiling — and supplies its own judgement. A
  wrong figure produced by that judgement is an accuracy defect, not a
  vulnerability, unless it was produced by reaching data the caller should not
  have.

### In scope

- **A path that reaches data as someone other than the caller.** A cached
  token served to the wrong identity, or a fetch that runs with a credential
  the loader holds rather than the caller's bearer.
- **A warehouse credential appearing in this repository's configuration at
  all.** The design's central claim is that none exists; a path that
  reintroduces one contradicts it.
- **Anything that turns a refusal into something that does not look like one.**
  The executor refuses; a loader that returns an empty table instead renders as
  "no data matched" and is a finding, not a cosmetic issue.
- **Query construction that reaches the engine as something other than one
  read-only `SELECT`** — the executor's guard is the backstop, but a loader
  that tries to defeat it is a defect here.
- **Leakage through the workspace.** Rows fetched under a user's identity are
  written to parquet with no identity attached. Documented; a path that widens
  who can read that cache, or that ships it somewhere, is in scope.
- **Supply chain.** A compromised or typosquatted dependency.

### Not in scope

- **Data Formulator itself.** It is consumed as an installed MIT-licensed
  package. Report defects upstream; ones this project has hit are recorded in
  [`docs/upstream-issues.md`](docs/upstream-issues.md).
- **The emulators**, and **`data-agent-service`** — each has its own policy.
- **The model's chart or transformation quality.**
- **Local development defaults** that exist so the stack runs offline on one
  machine, including anything in `.env.example`.

If you are unsure which side a report falls on, send it.

## Supported versions

Fixes land on `main`. There are no maintenance branches, so please confirm
against `main` before reporting.
