#!/usr/bin/env python3
"""Creates the worktree of an agent: branch <agente>/<feature> in .claude/worktrees/<agente>-<feature>.

Git worktrees only get versioned files, so the local .env (gitignored) does not exist
inside them. This script links the worktree's .env to the main working tree's .env,
so code and docker compose find the variables without any agent command naming the
file. The script never reads the .env contents.

Usage (Maestro, from anywhere in the repository):
    python3 .claude/scripts/novo_worktree.py <agente> <feature>
Example:
    python3 .claude/scripts/novo_worktree.py conector cliente-http
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from _common import AGENT_BRANCH_RE, POLICY, main_repo_root  # noqa: E402

NO_WORKTREE = {"revisor"}  # only reads: reviews with git diff from the main working tree


def fail(msg: str) -> int:
    print(f"novo_worktree: {msg}", file=sys.stderr)
    return 1


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def main() -> int:
    if len(sys.argv) != 3:
        return fail("uso: novo_worktree.py <agente> <feature>")
    agent, feature = sys.argv[1], sys.argv[2]
    branch = f"{agent}/{feature}"

    if not AGENT_BRANCH_RE.match(branch):
        return fail(
            f"'{branch}' fora do padrão <agente>/<feature>. Agentes: {', '.join(POLICY['agents'])}; "
            "feature em minúsculas, com letras, dígitos, '.', '_' ou '-'."
        )
    if agent in NO_WORKTREE:
        return fail(f"o agente '{agent}' só lê e não precisa de worktree.")
    if POLICY["phase"] < 2 and agent in POLICY["phase2_only_agents"]:
        return fail(f"o agente '{agent}' só atua na Fase 2; a fase atual é {POLICY['phase']}.")

    root = main_repo_root(Path.cwd())
    if root is None:
        return fail("execute dentro do repositório.")
    base = POLICY["main_branches"][0]
    path = root / ".claude" / "worktrees" / f"{agent}-{feature}"
    if path.exists():
        return fail(f"'{path}' já existe.")

    branch_exists = git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0
    args = ["worktree", "add", str(path), branch] if branch_exists else ["worktree", "add", "-b", branch, str(path), base]
    result = git(root, *args)
    if result.returncode != 0:
        return fail(f"git worktree add falhou:\n{result.stderr.strip()}")

    target = root / ".env"
    (path / ".env").symlink_to(target)

    origin = f"branch existente '{branch}'" if branch_exists else f"nova branch '{branch}' a partir de '{base}'"
    print(f"Worktree criado em {path} ({origin}).")
    print("O .env do worktree aponta para o .env da raiz principal.")
    if not target.exists():
        print("Atenção: o .env da raiz ainda não existe (tarefa F1-02). O link passa a funcionar quando ele for criado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
