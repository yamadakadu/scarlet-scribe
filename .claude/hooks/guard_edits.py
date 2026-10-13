#!/usr/bin/env python3
"""PreToolUse hook for Edit/Write/MultiEdit/NotebookEdit.

Blocks (exit 2) edits outside the acting agent's area, Phase 2 work during
Phase 1, test files, write calls in the ClickUp connector and secrets in content.
The acting agent comes from the git branch of the edited file's worktree.
"""

import sys
from pathlib import Path

from _common import (
    area_problems,
    block,
    clickup_problems,
    phase_problems,
    read_payload,
    repo_context,
    secret_problems,
    tests_problems,
)


def new_content(tool_input: dict) -> str:
    if "content" in tool_input:
        return tool_input["content"] or ""
    if "new_string" in tool_input:
        return tool_input["new_string"] or ""
    if "edits" in tool_input:
        return "\n".join(e.get("new_string", "") for e in tool_input["edits"])
    return tool_input.get("new_source", "") or ""


def main() -> int:
    payload = read_payload()
    tool_input = payload.get("tool_input", {})
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not path:
        return 0
    if ".git" in Path(path).expanduser().resolve().parts:
        return block([f"Não edite '{path}' diretamente: arquivos internos do git ficam fora do alcance dos agentes."])
    ctx = repo_context(path)
    if ctx is None:
        return 0  # outside any repository (memory, plans, ...): not ours to police
    rel = ctx.rel(path)
    content = new_content(tool_input)
    problems = (
        area_problems(ctx, rel)
        + phase_problems(rel, content)
        + tests_problems(rel, content)
        + clickup_problems(rel, content)
        + secret_problems(rel, content.splitlines())
    )
    return block(problems) if problems else 0


if __name__ == "__main__":
    sys.exit(main())
