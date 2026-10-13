#!/usr/bin/env python3
"""SubagentStop hook: appends one JSON line per finished subagent to .claude/logs/agents.log
in the main working tree, so the Maestro can follow deliveries. Never blocks."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from _common import main_repo_root, read_payload, repo_context


def main() -> int:
    try:
        payload = read_payload()
        cwd = Path(payload.get("cwd") or ".").resolve()
        ctx = repo_context(cwd)
        root = main_repo_root(cwd) or cwd
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": payload.get("hook_event_name", "SubagentStop"),
            "agent": ctx.agent if ctx else None,
            "branch": ctx.branch if ctx else None,
            "cwd": str(cwd),
            "session_id": payload.get("session_id"),
            "agent_id": payload.get("agent_id"),
            "agent_type": payload.get("agent_type"),
            "transcript_path": payload.get("agent_transcript_path") or payload.get("transcript_path"),
        }
        log = root / ".claude" / "logs" / "agents.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # logging must never interfere with the agents
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
