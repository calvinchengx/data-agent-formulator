# Upstream issues

Defects found in dependencies, reported there rather than worked around here.
Data Formulator is consumed as an installed package under its own MIT licence;
this repository forks nothing, so a workaround that lives here is a workaround
that hides a bug from the people who can fix it.

Each entry names what was hit, what it cost, where it was reported, and — if a
local mitigation exists — what removes it.

## 1. `data-agent-service` — the REST contract omits the HTTP surface

`services/contract/openapi.json` describes four paths: `/sources`, `/tables`,
`/tables/{qualified_name}` and `/query`. The running executor also serves
`/operations`, `/operations/{operation}` and `/call` on the same REST route —
they are registered in `services/warehouse-query-py/app.py` and answer 200.

**Cost:** this repository's catalog reader was written against the running
service rather than against the contract, because the contract does not
describe the calls it needed. A client written strictly from the contract
cannot reach an HTTP source at all over REST, and the 21 conformance checks
that both executors pass therefore say nothing about those three routes.

**Where:** `data-agent-service`, `services/contract/openapi.json`.

**Status:** to report upstream. Not worked around here — the loader calls the
routes the service actually serves, and `docs/00-plan.md` §8 says so.

_Nothing else recorded. Data Formulator itself has not been run as an
application yet._
