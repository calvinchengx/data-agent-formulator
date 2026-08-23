"""§5's load-bearing assumption, checked: the bearer survives `/warehouse-rest`.

The design in docs/00-plan.md routes the loader through the gateway's REST
route because a data loader is a non-MCP client. That only works if the
caller's token reaches the executor intact. Upstream documents that a
*synthesised* MCP call loses the caller's headers, which is why the executor
speaks MCP itself; `/warehouse-rest` is documented as a route rather than a
synthesis, so it should pass the bearer through. "Should" is what this file
replaces.

The check is not "a request succeeds". A gateway that dropped the bearer and
substituted a service principal would also succeed -- identically, for
everyone. So the witness is that three tokens produce three DIFFERENT
outcomes on one route with one statement, and that each difference is the one
the access rules predict.
"""

from __future__ import annotations

import pytest

from e2e import upstream

# Seeded upstream by seed/authz.py. The statement reads a column the analyst
# role is denied and the finance role is not, which is the smallest thing that
# can tell two identities apart at the executor.
DENIED_COLUMN_SQL = "SELECT TOP 1 email FROM dbo.dim_customer"
PERSONAS = {
    "alice": "alice@entraemulator.dev",  # Data.Analyst -- denied this column
    "carol": "carol@entraemulator.dev",  # Data.Finance -- allowed
    "bob": "bob@entraemulator.dev",  # no role at all
}


@pytest.fixture(scope="module")
def cfg():
    cfg = upstream.config()
    why = upstream.stack_is_up(cfg)
    if why:
        pytest.skip(f"{why}; run `make up` in ../data-agent-service")
    return cfg


@pytest.fixture(scope="module")
def outcomes(cfg):
    """One statement, three tokens, three answers."""
    return {
        who: upstream.query(DENIED_COLUMN_SQL, upstream.token_for(upn, cfg), cfg, max_rows=1)
        for who, upn in PERSONAS.items()
    }


def test_the_route_tells_the_three_identities_apart(outcomes):
    """The whole of §5, in one assertion.

    If the gateway replaced the bearer with one principal, these three would be
    the same response. They are not the same response.
    """
    statuses = {who: status for who, (status, _) in outcomes.items()}
    assert len(set(statuses.values())) > 1, (
        f"one statement, three identities, identical outcomes {statuses} — "
        "the bearer is not reaching the executor"
    )


def test_the_analyst_is_refused_the_column_the_rules_deny_her(outcomes):
    status, body = outcomes["alice"]
    assert status == 403, f"expected a refusal, got HTTP {status}: {body}"
    detail = str(body.get("detail", ""))
    assert "Data.Analyst" in detail and "dbo.dim_customer.email" in detail, (
        f"refused, but not for the reason the rules give: {detail!r}"
    )


def test_the_finance_analyst_reads_the_same_column(outcomes):
    status, body = outcomes["carol"]
    assert status == 200, f"expected rows, got HTTP {status}: {body}"
    assert body.get("columns") == ["email"], f"unexpected shape: {body}"
    assert body.get("rowCount", 0) >= 1, f"no rows for a role that may read them: {body}"


def test_a_principal_with_no_role_is_refused_at_the_source(outcomes):
    """A different refusal from Alice's, and the difference is the point.

    Alice is refused a column by the access rules. Bob is refused the workspace
    by the source. Two identities, two mechanisms, both named in the response.
    """
    status, body = outcomes["bob"]
    assert status == 403, f"expected a refusal, got HTTP {status}: {body}"
    detail = str(body.get("detail", ""))
    assert "no role" in detail, f"refused, but not as an unassigned principal: {detail!r}"
    assert detail != str(outcomes["alice"][1].get("detail", "")), (
        "the unassigned principal and the analyst were refused identically"
    )
