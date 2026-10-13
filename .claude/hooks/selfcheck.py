#!/usr/bin/env python3
"""Runs the hook scripts against the cases in selfcheck_cases.json and reports mismatches.

Maintenance tool for the Maestro: run it after changing policy.json or any hook.
Usage (from the repository root, on the main branch): python3 .claude/hooks/selfcheck.py
"""

import json
import subprocess
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
REPO = HOOKS.parent.parent


def outcome(script: str, payload: dict) -> str:
    proc = subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    if proc.returncode == 2:
        return "block"
    if '"permissionDecision": "ask"' in proc.stdout:
        return "ask"
    return "allow"


def with_repo(d: dict) -> dict:
    return {k: v.replace("REPO", str(REPO)) if isinstance(v, str) else v for k, v in d.items()}


def main() -> int:
    cases = json.loads((HOOKS / "selfcheck_cases.json").read_text())
    runs = [("guard_bash.py", {"command": c, "_label": c}, e) for c, e in cases["bash"]]
    runs += [("guard_reads.py", with_repo(i), e) for i, e in cases["read"]]
    runs += [("guard_edits.py", with_repo(i), e) for i, e in cases["edit_on_main"]]
    failures = 0
    for script, tool_input, expected in runs:
        label = tool_input.pop("_label", None) or json.dumps(tool_input)[:90]
        got = outcome(script, {"tool_input": tool_input, "cwd": str(REPO)})
        ok = got == expected
        failures += not ok
        print(f"{'OK  ' if ok else 'FAIL'} [{script}] {label} -> {got}" + ("" if ok else f" (esperado: {expected})"))
    print(f"\n{len(runs) - failures}/{len(runs)} casos corretos")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
