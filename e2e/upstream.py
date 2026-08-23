"""Reaching the upstream stack: configuration, tokens, and the executor.

The one rule this module exists to keep: a token is minted per persona and
carried unchanged. Nothing here holds a credential for the warehouse, and
nothing caches a token across personas -- the whole point of the witnesses
above it is that identity is what differs between two calls.
"""

from __future__ import annotations

import json
import os
import pathlib
import ssl
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]


def config() -> dict[str, str]:
    """`.env` if it exists, else `.env.example`.

    The template is a working local configuration, not a set of placeholders,
    so a fresh checkout can run the witnesses without a copy step. When the two
    disagree it is `.env` that is being used, which is the file a person edited.
    """
    values: dict[str, str] = {}
    for name in (".env.example", ".env"):
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    values.update({k: v for k, v in os.environ.items() if k.startswith(("DAF_", "DF_"))})
    return values


def _ctx(cfg: dict[str, str]) -> ssl.SSLContext | None:
    """Self-signed certificates are what the emulator family serves locally.

    `DAF_TLS_INSECURE` is a local-development setting and is named in
    docs/00-plan.md §11 as one. A production configuration does not set it, and
    the witnesses are not what runs in production.
    """
    if cfg.get("DAF_TLS_INSECURE", "").lower() not in {"1", "true", "yes"}:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def http(
    method: str,
    url: str,
    *,
    cfg: dict[str, str],
    headers: dict[str, str] | None = None,
    form: dict[str, str] | None = None,
    json_body: dict | None = None,
    timeout: float = 30.0,
) -> tuple[int, str]:
    """One request. Returns (status, body) and never raises on an HTTP error.

    A 403 is a result here, not a failure: the witnesses are largely about
    which refusals happen to whom.
    """
    data = None
    headers = dict(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif json_body is not None:
        data = json.dumps(json_body).encode()
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx(cfg)) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def token_for(upn: str, cfg: dict[str, str]) -> str:
    """A real sign-in for a seeded persona, by password grant.

    The password grant is what upstream's own harness uses against the
    development tenant, and for the same reason: a witness that a token
    identifies someone needs a token that genuinely does. `make login` uses the
    device-code flow instead, which is the shape a person gets; neither is a
    credential this repository stores.
    """
    url = f"{cfg['DAF_AUTHORITY']}/{cfg['DAF_TENANT']}/oauth2/v2.0/token"
    status, body = http(
        "POST",
        url,
        cfg=cfg,
        form={
            "grant_type": "password",
            "client_id": cfg["DAF_CLIENT_ID"],
            "username": upn,
            "password": cfg["DAF_TEST_PASSWORD"],
            "scope": cfg["DAF_SCOPE"],
        },
    )
    payload = json.loads(body) if body.lstrip().startswith("{") else {}
    if status != 200 or "access_token" not in payload:
        raise RuntimeError(f"no token for {upn}: HTTP {status} {body[:200]}")
    return payload["access_token"]


def executor(cfg: dict[str, str]) -> str:
    """The executor's base URL, on the surface §5 decided."""
    path = (
        cfg["DAF_WAREHOUSE_REST_PATH"]
        if cfg.get("DAF_EXECUTOR_SURFACE", "rest") == "rest"
        else cfg["DAF_WAREHOUSE_MCP_PATH"]
    )
    return cfg["DAF_APIM_BASE"].rstrip("/") + path


def query(
    sql: str, token: str, cfg: dict[str, str], max_rows: int | None = None
) -> tuple[int, dict]:
    status, body = http(
        "POST",
        executor(cfg) + "/query",
        cfg=cfg,
        headers={"Authorization": "Bearer " + token},
        json_body={
            "sql": sql,
            "source": cfg.get("DAF_SOURCE") or "contoso_warehouse",
            "maxRows": int(max_rows or cfg.get("DAF_MAX_ROWS", 100)),
        },
    )
    return status, (json.loads(body) if body.lstrip().startswith("{") else {"raw": body})


def stack_is_up(cfg: dict[str, str]) -> str | None:
    """None when reachable, else why not -- for a visible skip."""
    try:
        status, _ = http("GET", executor(cfg) + "/sources", cfg=cfg, timeout=5.0)
    except OSError as exc:
        return f"upstream stack unreachable at {executor(cfg)}: {exc}"
    if status in {401, 403}:
        return None  # answering, and asking for a token, which is the point
    if status >= 500:
        return f"upstream executor returned HTTP {status}"
    return None
