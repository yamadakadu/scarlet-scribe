"""Shared rules for the agent hooks (Claude Code) and the git hooks (.githooks/).

Policy data lives in policy.json next to this file. Every check returns a list of
human-readable problems (in Portuguese, since they are shown to the agents and to
the user); an empty list means the action is allowed.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
POLICY = json.loads((HOOKS_DIR / "policy.json").read_text())

AGENT_BRANCH_RE = re.compile(
    r"^(?P<agent>" + "|".join(POLICY["agents"]) + r")/(?P<feature>[a-z0-9][a-z0-9._-]*)$"
)

ESCALATE = (
    "Não contorne a regra (nada de --no-verify, core.hooksPath, renomear arquivo ou "
    "mover código para outra área). Relate ao Maestro, que consulta o Carlos."
)


# ---------------------------------------------------------------- git context


@dataclass
class RepoContext:
    root: Path
    branch: str  # "HEAD" when detached
    merging: bool

    @property
    def agent(self) -> str | None:
        """'maestro' on a main branch, the agent name on <agente>/<feature>, else None."""
        if self.branch in POLICY["main_branches"]:
            return "maestro"
        m = AGENT_BRANCH_RE.match(self.branch)
        return m.group("agent") if m else None

    def rel(self, path: str | Path) -> str:
        return Path(path).resolve().relative_to(self.root).as_posix()


def _git(cwd: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def repo_context(path: str | Path) -> RepoContext | None:
    """Git context of the repository containing `path` (which may not exist yet)."""
    d = Path(path).expanduser().resolve()
    while not d.is_dir():
        if d.parent == d:
            return None
        d = d.parent
    root = _git(d, "rev-parse", "--show-toplevel")
    if root is None:
        return None
    # symbolic-ref also works on an unborn branch (no commits yet); detached HEAD -> "HEAD"
    branch = _git(d, "symbolic-ref", "--short", "-q", "HEAD") or "HEAD"
    merge_head = _git(d, "rev-parse", "--path-format=absolute", "--git-path", "MERGE_HEAD")
    return RepoContext(Path(root), branch, bool(merge_head) and Path(merge_head).exists())


def main_repo_root(path: str | Path) -> Path | None:
    """Root of the main working tree, even when `path` is inside a linked worktree."""
    d = Path(path).resolve()
    common = _git(d, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common).parent if common else None


# ---------------------------------------------------------------- path rules


def _matches(rel: str, entries: list[str]) -> bool:
    return any(rel == e or (e.endswith("/") and rel.startswith(e)) for e in entries)


def area_problems(ctx: RepoContext, rel: str) -> list[str]:
    agent = ctx.agent
    if agent is None:
        return [
            f"Branch '{ctx.branch}' fora do padrão <agente>/<feature> "
            f"(agentes: {', '.join(POLICY['agents'])}). Alterações bloqueadas."
        ]
    if agent == "maestro":
        if ctx.merging or _matches(rel, POLICY["maestro_paths"]):
            return []
        return [
            f"'{rel}' não é da área do Maestro. Na branch principal o Maestro só altera "
            "documentação e configuração; código é alterado pelo agente dono da área, "
            "na branch dele."
        ]
    if POLICY["phase"] < 2 and agent in POLICY["phase2_only_agents"]:
        return [f"O agente '{agent}' só atua na Fase 2; a fase atual é {POLICY['phase']}."]
    if _matches(rel, POLICY["agents"][agent]):
        return []
    owners = [a for a, paths in POLICY["agents"].items() if _matches(rel, paths)]
    owner = f" (área de: {', '.join(owners)})" if owners else " (fora de qualquer área)"
    return [
        f"'{rel}' está fora da área do agente '{agent}'{owner}. Peça a alteração ao "
        "Maestro, que repassa ao dono da área."
    ]


def phase_problems(rel: str, content: str = "") -> list[str]:
    if POLICY["phase"] >= 2:
        return []
    problems = []
    if _matches(rel, POLICY["phase2_paths"]):
        problems.append(f"'{rel}' pertence à Fase 2 (autenticação e horas), fora do escopo atual.")
    tables = "|".join(POLICY["phase2_tables"])
    table_re = re.compile(
        r"""(__tablename__\s*=|create_table\(|Table\()\s*['"](""" + tables + r""")['"]"""
    )
    m = table_re.search(content)
    if m:
        problems.append(f"Tabela '{m.group(2)}' pertence à Fase 2; não crie antes da hora.")
    return problems


TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__)/"
    r"|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$"
    r"|\.(test|spec)\.[cm]?[jt]sx?$"
    r"|(^|/)(pytest\.ini|tox\.ini|(vitest|jest)\.config\.[cm]?[jt]s)$"
)
TEST_DEP_RE = re.compile(r"""['"]?\b(pytest[\w-]*|vitest|jest|@testing-library/[\w-]+|hypothesis)\b""")


def tests_problems(rel: str, content: str = "") -> list[str]:
    problems = []
    if TEST_PATH_RE.search(rel):
        problems.append(f"'{rel}' é um arquivo de teste. Testes estão fora do escopo até o MVP (decisão do Carlos).")
    if rel.endswith(("pyproject.toml", "package.json")) and TEST_DEP_RE.search(content):
        problems.append(f"'{rel}' adiciona dependência de teste. Testes estão fora do escopo até o MVP.")
    return problems


CONNECTOR_WRITE_RE = re.compile(
    r"""\.(post|put|patch|delete)\s*\("""
    r"""|method\s*=\s*['"](POST|PUT|PATCH|DELETE)['"]"""
    r"""|\.(request|stream)\(\s*['"](POST|PUT|PATCH|DELETE)['"]""",
    re.IGNORECASE,
)


def connector_write_problems(rel: str, content: str = "") -> list[str]:
    """Every connector (ClickUp, GitLab, ...) is read-only: only GET calls."""
    if "/connectors/" not in f"/{rel}" or rel in POLICY["connector_write_allowed_files"]:
        return []
    m = CONNECTOR_WRITE_RE.search(content)
    if m:
        return [
            f"'{rel}' contém uma chamada HTTP de escrita ({m.group(0).strip()}). "
            "Os conectores (ClickUp, GitLab) são somente leitura: use apenas GET."
        ]
    return []


# ---------------------------------------------------------------- forbidden files


FORBIDDEN_DIRS = (
    ".venv/", "venv/", "node_modules/", "__pycache__/", ".pytest_cache/",
    ".mypy_cache/", ".ruff_cache/", "dist/", "build/", ".claude/logs/", ".claude/worktrees/",
)
FORBIDDEN_NAMES_RE = re.compile(
    r"^(\.env(\..+)?|id_(rsa|dsa|ecdsa|ed25519)(\.pub)?|\.DS_Store)$"
    r"|\.(pem|key|p12|pfx|kdbx|pyc|sqlite3?|db|log|tsbuildinfo)$"
)


def is_secret_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    if name == ".env.example":
        return False
    return bool(re.match(r"^\.env(\..+)?$|^id_(rsa|dsa|ecdsa|ed25519)$|.*\.(pem|key|p12|pfx|kdbx)$", name))


def forbidden_file_problems(rel: str, size: int | None = None) -> list[str]:
    name = rel.rsplit("/", 1)[-1]
    problems = []
    if name != ".env.example" and (
        FORBIDDEN_NAMES_RE.search(name)
        or any(f"/{d}" in f"/{rel}" for d in FORBIDDEN_DIRS)
        or rel == ".claude/settings.local.json"
    ):
        problems.append(f"'{rel}' não deve ser versionado (segredo, artefato gerado ou arquivo local).")
    if size is not None and size > POLICY["max_file_bytes"]:
        problems.append(f"'{rel}' tem {size} bytes, acima do limite de {POLICY['max_file_bytes']}.")
    return problems


# ---------------------------------------------------------------- secrets in content


SECRET_PATTERNS = [
    ("token pessoal do ClickUp", re.compile(r"\bpk_\d+_[A-Za-z0-9]{20,}")),
    ("token do GitLab", re.compile(r"\bgl(pat|dt|ptt|rt|cbt|soat|ft|imt|oas|agent)-[A-Za-z0-9_.-]{20,}")),
    ("chave privada", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("chave de acesso AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("token do GitHub", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("token do Slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("token Bearer literal", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}")),
]
DSN_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@'\"]+:([^\s@'\"]+)@")
ASSIGN_RE = re.compile(
    r"(?i)\b[\w-]*(password|passwd|secret|token|api_?key|private_?key|encryption_?key)[\w-]*"
    r"""['"]?\s*[:=]\s*['"]?([A-Za-z0-9+/=_-]{16,})"""
)
PLACEHOLDER_RE = re.compile(
    r"(?i)^(\$\{.*\}|<.*>|\*+|x+|changeme|change_me|example|placeholder|dummy|test|"
    r"password|postgres|senha|secret|your[\w-]*)$"
)


def _allowlist() -> set[str]:
    path = HOOKS_DIR.parent.parent / ".githooks" / "secrets-allowlist.txt"
    if not path.exists():
        return set()
    return {ln.split()[0] for ln in path.read_text().splitlines() if ln.strip() and not ln.startswith("#")}


def fingerprint(line: str) -> str:
    return hashlib.sha256(line.strip().encode()).hexdigest()[:16]


def secret_problems(rel: str, lines: list[str]) -> list[str]:
    """Look for secrets in `lines` (the content being written or the added lines of a commit)."""
    allow = _allowlist()
    problems = []
    for n, line in enumerate(lines, 1):
        if fingerprint(line) in allow:
            continue
        hit = next((label for label, rx in SECRET_PATTERNS if rx.search(line)), None)
        if hit is None:
            dsn = DSN_RE.search(line)
            if dsn and not PLACEHOLDER_RE.match(dsn.group(1)):
                hit = "URL de conexão com senha"
        if hit is None:
            asg = ASSIGN_RE.search(line)
            if asg:
                value = asg.group(2)
                looks_random = re.search(r"\d", value) and re.search(r"[A-Za-z]", value)
                if looks_random and not PLACEHOLDER_RE.match(value):
                    hit = "valor com cara de segredo atribuído a variável sensível"
        if hit:
            problems.append(
                f"'{rel}', linha {n}: possível {hit} (impressão digital {fingerprint(line)})."
            )
    return problems


# ---------------------------------------------------------------- claude hook I/O


def read_payload() -> dict:
    import sys

    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def block(problems: list[str], extra: str = ESCALATE) -> int:
    import sys

    print("Bloqueado pelos hooks do projeto:\n- " + "\n- ".join(problems) + f"\n{extra}", file=sys.stderr)
    return 2


def ask(reasons: list[str]) -> int:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": " ".join(reasons),
                }
            }
        )
    )
    return 0
