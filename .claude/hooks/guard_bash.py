#!/usr/bin/env python3
"""PreToolUse hook for Bash.

Blocks (exit 2): reading secret files or the environment, bypassing git hooks,
destructive git commands, commits on branches outside <agente>/<feature>, test
dependencies, and write requests to the ClickUp and GitLab APIs. The literal text of commit
messages is not checked (see without_commit_messages).
Asks the user (permissionDecision "ask"): push, commit/merge on the main branch,
and recursive deletions. (`rm -rf` itself is already blocked by the user's global hook.)
"""

import re
import shlex
import sys
from pathlib import Path

from _common import POLICY, block, ask, read_payload, repo_context

SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "{", "}", "then", "do", "else", "!"}
PREFIXES = {"sudo", "doas", "command", "builtin", "exec", "nohup", "time", "xargs", "env"}

SECRET_FILE_RE = re.compile(r"""(^|[\s'"/=<>:])\.env(\.(?!example\b)[\w.-]+)?(?=$|[\s'";|&)>])""")
ENV_DUMP_RE = re.compile(r"(^|[;&|]\s*)(printenv|env|set|export\s+-p)\s*($|[;&|])|/proc/[^\s]*/environ|docker\s+compose\s+config")
TEST_DEP_RE = re.compile(r"\b(uv\s+(add|pip\s+install)|pip3?\s+install|npm\s+(i|install|add)|pnpm\s+add|yarn\s+add)\b.*\b(pytest|vitest|jest|@testing-library|hypothesis)")
API_WRITE_RE = re.compile(
    r"(-X\s*|--request[\s=]+)(POST|PUT|PATCH|DELETE)\b|\s(-d|--data[\w-]*|-F|--form|--json)[\s=]"
    r"|\bhttps?\s+(POST|PUT|PATCH|DELETE)\b",
    re.IGNORECASE,
)

# Commit messages are free text: mentioning ".env" or "pytest" there reads nothing.
# Messages that the shell would expand ($(...), `...`, $VAR) are kept, so
# `git commit -m "$(cat .env)"` is still caught.
GIT_COMMIT_RE = re.compile(r"\bgit\b[^\n;&|]*?\bcommit\b")
MESSAGE_ARG_RE = re.compile(r"""(\s(?:-m|--message)(?:=|\s+))("(?:[^"\\]|\\.)*"|'[^']*')""")
HEREDOC_RE = re.compile(r"""<<-?\s*(['"]?)(\w+)\1""")
STDIN_FILE_RE = re.compile(r"\s(-F|--file)(=|\s*)-(\s|$)")
EXPANSION_RE = re.compile(r"\$|`")
# The GitLab host varies (gitlab.com or self-hosted), so the API path and the glab CLI mark it.
# An HTTP client is also required, so `git branch -d gitlab-x` or `docker compose up -d gitlab` pass.
GITLAB_API_RE = re.compile(r"/api/v4/|\bgitlab\b|\bglab\b", re.IGNORECASE)
HTTP_CLIENT_RE = re.compile(r"\b(curl|wget|xh|glab)\b|(^|[;&|(]\s*)https?\s")


def without_commit_messages(command: str) -> str:
    """The command with the literal text of `git commit` messages (-m/--message, or a
    heredoc read with -F -) replaced by an empty message; everything else is kept."""
    start = GIT_COMMIT_RE.search(command)
    if start is None:
        return command
    head, tail = command[: start.start()], command[start.start() :]

    def blank(m: re.Match) -> str:
        value = m.group(2)
        if value.startswith('"') and EXPANSION_RE.search(value):
            return m.group(0)
        return m.group(1) + "''"

    tail = MESSAGE_ARG_RE.sub(blank, tail)
    lines, out, i = tail.split("\n"), [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        doc = HEREDOC_RE.search(line)
        if not (doc and GIT_COMMIT_RE.search(line) and STDIN_FILE_RE.search(line)):
            continue
        end = next((j for j in range(i, len(lines)) if lines[j].strip() == doc.group(2)), None)
        if end is None:
            continue
        body = "\n".join(lines[i:end])
        if doc.group(1) or not EXPANSION_RE.search(body):  # quoted delimiter: no expansion
            i = end
    return head + "\n".join(out)


def split_commands(command: str) -> list[list[str]]:
    spaced = re.sub(r"(\|\||&&|[;|&(){}\n])", r" \1 ", command)
    try:
        tokens = shlex.split(spaced, posix=True)
    except ValueError:
        tokens = spaced.split()
    commands, current = [], []
    for tok in tokens:
        if tok in SEPARATORS:
            if current:
                commands.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        commands.append(current)
    return commands


def strip_prefixes(argv: list[str]) -> list[str]:
    i = 0
    while i < len(argv) and (argv[i] in PREFIXES or argv[i].startswith("-") or "=" in argv[i]):
        i += 1
    return argv[i:]


def parse_git(argv: list[str], cwd: Path) -> tuple[str, list[str], Path, list[str]] | None:
    """(subcommand, args, effective cwd, global -c options) for a git invocation."""
    if not argv or argv[0].rsplit("/", 1)[-1] != "git":
        return None
    i, configs = 1, []
    while i < len(argv) and argv[i].startswith("-"):
        if argv[i] == "-C" and i + 1 < len(argv):
            cwd = (cwd / argv[i + 1]).resolve()
            i += 2
        elif argv[i] == "-c" and i + 1 < len(argv):
            configs.append(argv[i + 1])
            i += 2
        else:
            i += 1
    if i >= len(argv):
        return None
    return argv[i], argv[i + 1 :], cwd, configs


def git_checks(sub: str, args: list[str], cwd: Path, configs: list[str]) -> tuple[list[str], list[str]]:
    blocks: list[str] = []
    asks: list[str] = []
    flags = {a for a in args if a.startswith("-")}

    read_only_config = {"--get", "--get-all", "--get-regexp", "-l", "--list", "--show-origin"} & flags
    if any(c.lower().startswith("core.hookspath") for c in configs) or (
        sub == "config" and not read_only_config and any(a.lower() == "core.hookspath" for a in args)
    ):
        blocks.append("Alterar core.hooksPath desativa a verificação dos commits.")
    if sub in ("commit", "merge", "cherry-pick", "revert", "am") and (
        "--no-verify" in flags or (sub == "commit" and any(re.fullmatch(r"-[a-zA-Z]*n[a-zA-Z]*", f) for f in flags))
    ):
        blocks.append("--no-verify pula a verificação de segredos e de arquivos proibidos.")

    destructive = (
        (sub == "reset" and "--hard" in flags)
        or (sub == "clean" and ("--force" in flags or any("f" in f for f in flags if not f.startswith("--"))))
        or (sub == "checkout" and ("--" in args or "." in args))
        or (sub == "restore" and "." in args and "--staged" not in flags)
        or (sub == "branch" and ({"-D", "--delete"} & flags or ("-d" in flags and "--force" in flags)))
        or sub in ("rebase", "filter-branch", "filter-repo", "update-ref", "gc", "prune")
        or (sub == "reflog" and args[:1] in (["expire"], ["delete"]))
        or (sub == "stash" and args[:1] in (["drop"], ["clear"]))
        or (sub == "push" and ({"-f", "--force", "--force-with-lease", "--delete", "-d"} & flags or any(a.startswith("+") or a.startswith(":") for a in args)))
        or (sub == "worktree" and args[:1] == ["remove"] and ({"-f", "--force"} & flags))
    )
    if destructive:
        blocks.append(f"'git {sub} {' '.join(args)}' é destrutivo ou reescreve histórico. Peça ao Carlos.")

    if sub == "push" and not destructive:
        asks.append("Push para o remoto: confirme se deve ser enviado.")

    if sub in ("commit", "merge", "cherry-pick", "revert"):
        ctx = repo_context(cwd)
        if ctx is not None:
            if ctx.branch in POLICY["main_branches"]:
                asks.append(f"'git {sub}' na branch principal ({ctx.branch}): confirme a integração.")
            elif ctx.agent is None:
                blocks.append(
                    f"Branch '{ctx.branch}' fora do padrão <agente>/<feature>. Crie a branch com o "
                    "nome do agente e da feature, por exemplo 'conector/cliente-http'."
                )
    return blocks, asks


def main() -> int:
    payload = read_payload()
    command = payload.get("tool_input", {}).get("command", "")
    if not command:
        return 0
    command = without_commit_messages(command)
    cwd = Path(payload.get("cwd") or ".").resolve()
    blocks: list[str] = []
    asks: list[str] = []

    if SECRET_FILE_RE.search(command):
        blocks.append("O comando referencia um arquivo .env. O conteúdo de segredos não pode entrar no contexto.")
    if ENV_DUMP_RE.search(command):
        blocks.append("O comando exibe variáveis de ambiente, que podem conter os tokens do ClickUp e do GitLab.")
    if TEST_DEP_RE.search(command):
        blocks.append("Instalar dependência de teste: testes estão fora do escopo até o MVP.")
    if "api.clickup.com" in command and API_WRITE_RE.search(command):
        blocks.append("Requisição de escrita para a API do ClickUp. O projeto é somente leitura.")
    if GITLAB_API_RE.search(command) and HTTP_CLIENT_RE.search(command) and API_WRITE_RE.search(command):
        blocks.append("Requisição de escrita para a API do GitLab. O projeto é somente leitura.")

    for argv in split_commands(command):
        argv = strip_prefixes(argv)
        if not argv:
            continue
        git = parse_git(argv, cwd)
        if git:
            b, a = git_checks(*git)
            blocks += b
            asks += a
            continue
        name = argv[0].rsplit("/", 1)[-1]
        opts = [a for a in argv[1:] if a.startswith("-") and not a.startswith("--")]
        if name == "rm" and ("--recursive" in argv or any("r" in o.lower() for o in opts)):
            asks.append(f"Remoção recursiva: '{' '.join(argv)}'.")
        elif name == "find" and ("-delete" in argv or ("-exec" in argv and "rm" in argv)):
            asks.append(f"Remoção via find: '{' '.join(argv)}'.")
        elif name == "shred":
            asks.append(f"Destruição de arquivos: '{' '.join(argv)}'.")

    if blocks:
        return block(blocks)
    if asks:
        return ask(asks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
