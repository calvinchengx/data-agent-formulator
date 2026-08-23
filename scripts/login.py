"""The token broker: device code in, a short-lived bearer on disk, mode 0600.

This is deliberately not part of the plugin. Data Formulator persists loader
parameters with the workspace, and a token's lifetime is not the workspace's
(docs/00-plan.md §6) -- so the token never becomes a parameter, and the thing
that mints it is a command a person runs rather than a form they fill in.

Device code is the family's shape for a CLI, and it is what upstream's own
architecture table names for this hop. §10 step 6b replaces it with a popup
inside Data Formulator; both feed the same "read the bearer, hold it in memory
only" path in the loader, so neither is a stepping stone that has to be removed.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e2e import upstream  # noqa: E402 — the path above is what makes it importable


def request_code(cfg: dict[str, str]) -> dict:
    status, body = upstream.http(
        "POST",
        f"{cfg['DAF_AUTHORITY']}/{cfg['DAF_TENANT']}/oauth2/v2.0/devicecode",
        cfg=cfg,
        form={"client_id": cfg["DAF_CLIENT_ID"], "scope": cfg["DAF_SCOPE"]},
    )
    if status != 200:
        raise SystemExit(f"the tenant refused a device code: HTTP {status} {body[:300]}")
    return json.loads(body)


def poll(cfg: dict[str, str], device_code: str, interval: int, expires_in: int) -> str:
    """Poll until the person finishes, or the code expires.

    `authorization_pending` is the normal answer and must not read as a
    failure; `slow_down` means back off rather than give up. Anything else is
    terminal and is reported with the tenant's own words.
    """
    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(interval)
        status, body = upstream.http(
            "POST",
            f"{cfg['DAF_AUTHORITY']}/{cfg['DAF_TENANT']}/oauth2/v2.0/token",
            cfg=cfg,
            form={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": cfg["DAF_CLIENT_ID"],
                "device_code": device_code,
            },
        )
        payload = json.loads(body) if body.lstrip().startswith("{") else {}
        if status == 200 and "access_token" in payload:
            return payload["access_token"]
        error = payload.get("error", "")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        raise SystemExit(
            f"sign-in failed: {error or status} {payload.get('error_description', '')}"
        )
    raise SystemExit("the device code expired before sign-in completed")


def write_token(path: pathlib.Path, token: str) -> None:
    """0600 before the bytes, not after.

    Creating the file and then chmod-ing it leaves a window where the token is
    world-readable. Short, but it is the kind of window that only ever gets
    noticed after it matters.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(token)


def main() -> int:
    ap = argparse.ArgumentParser(description="Sign in and write a token for the loader to read.")
    ap.add_argument("--out", default=None, help="override DAF_TOKEN_FILE")
    args = ap.parse_args()

    cfg = upstream.config()
    out = pathlib.Path(args.out or cfg.get("DAF_TOKEN_FILE", "./.token")).expanduser()

    code = request_code(cfg)
    verification = code.get("verification_uri") or code.get("verification_url") or ""
    print(f"\n  Open  {verification}")
    print(f"  Code  {code['user_code']}\n")
    if code.get("message"):
        print(f"  ({code['message']})\n")

    token = poll(
        cfg, code["device_code"], int(code.get("interval", 5)), int(code.get("expires_in", 900))
    )
    write_token(out, token)

    # Say whose token it is. A broker that prints "signed in" without naming
    # the principal is how a person ends up exploring as the wrong identity and
    # concluding the permissions are broken.
    claims = upstream.claims(token)
    who = claims.get("preferred_username") or claims.get("upn") or claims.get("oid") or "unknown"
    expires = claims.get("exp")
    when = time.strftime("%H:%M:%S", time.localtime(expires)) if expires else "unknown"
    print(f"signed in as {who}; token written to {out} (0600), expires {when}")
    print(f"scope: {urllib.parse.unquote(cfg['DAF_SCOPE'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
