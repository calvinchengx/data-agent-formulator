"""Record what the suite actually witnessed, for the badge to read back.

`docs/witnesses.json` is written from a real `pytest` run and `--check`
re-verifies it, so a badge can never advertise a number nobody proved. Same
convention as the family: the manifest is committed, CI re-runs the suite and
fails if the recorded figure has drifted.

One check in this suite compares the design to `data-agent-service`'s executor
contract, and a CI runner has no sibling checkout, so it skips there. That
makes `passed` machine-dependent while `total` is not. `--check` therefore
holds the suite to `total` -- a check deleted or added is drift -- and to
nothing having failed, and prints how many were skipped and where. It does not
demand the same `passed` count on every machine, because a check that can only
run locally is exactly what docs/parity.md exists to keep visible. What it
must never do is let a skip read as a pass, which is why the skipped count is
printed rather than absorbed.

No coverage figure is recorded. This repository has no product code yet, so a
percentage would be measured over its own gates -- a number about the tests,
reported as though it were about the loader. It arrives with the loader.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "witnesses.json"


def run_suite() -> tuple[int, int, int]:
    """Return (passed, skipped, failed) from a real run."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    out = proc.stdout + proc.stderr
    if not re.search(r"\d+ (passed|failed|skipped)", out):
        print(out[-2000:])
        raise SystemExit("the suite reported no result at all")

    def tally(word: str) -> int:
        m = re.search(rf"(\d+) {word}", out)
        return int(m.group(1)) if m else 0

    for line in out.splitlines():
        if line.startswith("SKIPPED"):
            print(f"  skipped: {line}")
    return tally("passed"), tally("skipped"), tally("failed")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if the recorded figure has drifted")
    args = ap.parse_args()

    passed, skipped, failed = run_suite()
    total = passed + skipped + failed

    if args.check:
        recorded = json.loads(MANIFEST.read_text())
        if failed:
            print(f"FAIL: {failed} check(s) failed")
            return 1
        if recorded["total"] != total:
            print(f"FAIL: manifest records {recorded['total']} checks, the suite has {total}")
            return 1
        print(
            f"witnesses: {passed}/{total} here, {skipped} skipped — the manifest agrees on {total}"
        )
        return 0

    if skipped:
        print(f"note: recording from a run with {skipped} skipped; `passed` is this machine's")
    MANIFEST.write_text(
        json.dumps({"passed": passed, "skipped": skipped, "total": total}, indent=2) + "\n"
    )
    print(f"witnesses: {passed}/{total} → recorded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
