"""The checks that hold this repository's scaffold to itself.

There is no loader here yet, so what can be proved is that the files agree —
with each other, and with the upstream contract this design rests on. That is
a real thing to check and it is not the same thing as a working plugin;
docs/parity.md keeps the two apart.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / ".env.example"
PARITY = ROOT / "docs" / "parity.md"
# data-agent-service is consumed, not built, from here. The path is where the
# family keeps its checkouts side by side; absent, the contract check skips
# visibly rather than passing on nothing.
UPSTREAM = ROOT.parent / "data-agent-service"

SETTING = re.compile(
    r"\b(DAF_[A-Z0-9_]+|DAS_[A-Z0-9_]+|DF_[A-Z0-9_]+|DATA_FORMULATOR_[A-Z0-9_]+)\b"
)


def _template_keys() -> set[str]:
    return {
        line.split("=", 1)[0].strip()
        for line in TEMPLATE.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }


def _documents() -> list[pathlib.Path]:
    return [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


def test_every_setting_a_document_names_exists_in_the_template():
    """A document naming a setting that does not exist reads as deployable.

    This is the failure `data-agent-service` spent a day on: a runbook naming
    three parameters which were never defined. The fix was not a better
    runbook but this comparison.
    """
    declared = _template_keys()
    missing: dict[str, set[str]] = {}
    for doc in _documents():
        named = {k for k in SETTING.findall(doc.read_text(encoding="utf-8")) if k not in declared}
        if named:
            missing[doc.name] = named
    assert not missing, f"named in a document, absent from .env.example: {missing}"


def test_every_key_in_the_template_is_named_by_a_document():
    """The other direction: a setting nobody documents is one nobody can decide about.

    docs/00-plan.md §11 is the table this holds the template to. It only became
    checkable once that document existed; before it, most keys were named
    nowhere but the template itself.
    """
    documented = set()
    for doc in _documents():
        documented |= set(SETTING.findall(doc.read_text(encoding="utf-8")))
    undocumented = _template_keys() - documented
    assert not undocumented, f"in .env.example, named by no document: {sorted(undocumented)}"


def test_no_parity_row_is_green_without_naming_a_check():
    """A green that names no command is a claim nobody can re-run."""
    unproved = []
    for line in PARITY.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "🟢" not in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        # Capability | Witnessed locally | Check | Witnessed running
        if len(cells) < 3 or not cells[2] or cells[2] in {"—", "-"}:
            unproved.append(cells[0])
    assert not unproved, f"green rows naming no check: {unproved}"


def test_the_executor_calls_this_design_rests_on_exist_upstream():
    """Check the design against the contract, not against memory.

    The loader's four abstract methods map onto four executor calls. If that
    mapping is wrong the design is wrong, and it is cheaper to learn here than
    in the plugin.
    """
    contract = UPSTREAM / "services" / "contract" / "openapi.json"
    if not contract.exists():
        pytest.skip(f"upstream checkout absent at {UPSTREAM}; nothing to check the design against")
    paths = set(json.loads(contract.read_text(encoding="utf-8"))["paths"])
    required = {"/sources", "/tables", "/tables/{qualified_name}", "/query"}
    missing = required - paths
    assert not missing, f"the design names calls the contract does not have: {sorted(missing)}"
