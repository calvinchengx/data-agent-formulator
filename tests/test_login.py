"""The token broker, and the rule that would have caught it being fictional.

`make login` was named in `auth_instructions()`, in `.env.example` and twice in
the plan before it existed. That is the same failure the settings check already
guards against, one level up: a document naming a thing that is not there reads
as usable. So the first test here is about the Makefile, not about OAuth.
"""

from __future__ import annotations

import pathlib
import re
import stat

import pytest

from e2e import upstream
from scripts import login

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / "Makefile"
PLUGIN = ROOT / "plugin" / "data_agent_data_loader.py"


def test_every_make_target_a_document_names_exists():
    """`make login` was named in three places and did not exist."""
    targets = set(re.findall(r"^([a-z][a-z-]*):", MAKEFILE.read_text(), re.M))
    documents = [ROOT / "README.md", PLUGIN, ROOT / ".env.example", *(ROOT / "docs").glob("*.md")]
    # `make up` in `../data-agent-service` is a different Makefile's target and
    # is not this one's to have. The qualifier is what tells them apart, so an
    # unqualified mention is read as a claim about this repository.
    elsewhere = re.compile(r"`make [a-z][a-z-]*`[^.]{0,60}?(?:in `\.\./|-C )")
    named: dict[str, set[str]] = {}
    for doc in documents:
        # Newlines collapsed first: the qualifier often wraps onto the next
        # line, and a rule that only worked on unwrapped prose would be a rule
        # about formatting.
        text = elsewhere.sub("", " ".join(doc.read_text().split()))
        missing = set(re.findall(r"`make ([a-z][a-z-]*)", text)) - targets
        if missing:
            named[doc.name] = missing
    assert not named, f"named in a document, absent from the Makefile: {named}"


def test_the_token_file_is_never_world_readable(tmp_path):
    """0600 before the bytes, not after.

    Writing the file and then chmod-ing it leaves a window where the token is
    readable by anyone on the machine.
    """
    target = tmp_path / "nested" / ".token"
    login.write_token(target, "a-token")
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600, f"token file is {oct(mode)}"
    assert target.read_text() == "a-token"


def test_claims_are_read_without_being_trusted():
    """The broker names the principal it signed in as; it authorizes nothing."""
    # header.payload.signature, payload = {"upn": "carol@entraemulator.dev"}
    token = "eyJhbGciOiJub25lIn0.eyJ1cG4iOiAiY2Fyb2xAZW50cmFlbXVsYXRvci5kZXYifQ.not-a-signature"
    assert upstream.claims(token).get("upn") == "carol@entraemulator.dev"
    assert upstream.claims("not-a-jwt") == {}


@pytest.fixture(scope="module")
def cfg():
    cfg = upstream.config()
    why = upstream.stack_is_up(cfg)
    if why:
        pytest.skip(f"{why}; run `make up` in ../data-agent-service")
    return cfg


def test_the_tenant_issues_a_device_code(cfg):
    code = login.request_code(cfg)
    assert code["user_code"] and code["device_code"]
    assert int(code["interval"]) >= 1
    assert code.get("verification_uri"), "no URI for a person to open"


def test_an_unfinished_sign_in_is_pending_rather_than_failed(cfg):
    """`authorization_pending` is the normal answer while a person is typing.

    A broker that treated it as an error would fail every sign-in on the first
    poll. Checked directly against the tenant rather than through `poll()`,
    which would sleep for the interval to say the same thing.
    """
    code = login.request_code(cfg)
    status, body = upstream.http(
        "POST",
        f"{cfg['DAF_AUTHORITY']}/{cfg['DAF_TENANT']}/oauth2/v2.0/token",
        cfg=cfg,
        form={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": cfg["DAF_CLIENT_ID"],
            "device_code": code["device_code"],
        },
    )
    assert status != 200, "an unapproved device code returned a token"
    assert "authorization_pending" in body, body[:300]
