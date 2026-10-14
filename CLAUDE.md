# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project goal

An integration layer for corporate tools. ClickUp is the first one. Data reaches our own database by two routes. A dedicated **read-only "bot" user** pulls the workspace structure, members, tasks and milestones. **Time entries come from each person's own ClickUp OAuth token**: the person logs into the web app via the company **LDAP**, then connects their ClickUp account. The web app shows everything in one place. More tools will be added later. `PROJECT.md` has the original idea (in Portuguese). **`ARCHITECTURE.md` holds the agreed decisions, the phases and the risks to validate. Read it before starting a feature.**

The user writes in Portuguese. Reply in Portuguese.

## Current state and phases

The architecture is under review with the user. No application code exists yet; the repo is still the `uv init --package` scaffold at the root (`src/scarlet_scribe/__init__.py`).

Work happens in two phases:
- **Phase 1 (initial structure):** the bot token, structure, tasks, milestones, sync, read API and frontend. It has **no login and no time entries**, and all routes are open.
- **Phase 2 (separate):** authentication (LDAP and ClickUp OAuth) and time entries.

**Do not build Phase 2 pieces (auth, sessions, OAuth, `time_entries`) during Phase 1.** Sections marked "(Fase 2)" in `ARCHITECTURE.md` describe the agreed design for later.

`PLANO_DE_EXECUCAO.md` lists every task with its owning agent (Maestro, the orchestrator; Alicerce, Batedor, Conector, Arquivista, Sincronista, Portal, Vitrine and Revisor; Guardião and Ponte join in Phase 2), dependencies, waves, file-ownership boundaries and done criteria. When acting as one of those agents, change only files in that agent's area, and report divergences from `ARCHITECTURE.md` to the Maestro instead of editing it.

Agent definitions live in `.claude/agents/`. Each agent works in its own worktree on the branch `<agente>/<feature>`, and every commit subject starts with `<agente>/<feature>: `. The Maestro creates each worktree with `python3 .claude/scripts/novo_worktree.py <agente> <feature>`. The script branches from `main` into `.claude/worktrees/<agente>-<feature>` and links the worktree's `.env` to the main tree's `.env`, which worktrees don't otherwise get because it's gitignored.

Hooks enforce these rules. The policy is in `.claude/hooks/policy.json`; the hook scripts are in `.claude/hooks/` (Claude Code) and `.githooks/` (git pre-commit and commit-msg). See `PLANO_DE_EXECUCAO.md` › "Hooks". If a hook blocks you, never bypass it: no `--no-verify`, no `core.hooksPath` change, no renaming or moving files to dodge a rule. Unstage the file, report to the Maestro, and let the user decide. After changing the policy or a hook, run `python3 .claude/hooks/selfcheck.py`.

## Stack

- Backend: Python 3.12, FastAPI, httpx (async), Pydantic v2, SQLAlchemy 2 + Alembic, PostgreSQL, APScheduler in a separate worker process. Managed with **uv** (`uv_build` backend, `src/` layout).
- Frontend: Vite + React + TypeScript, TanStack Query, with a TS client generated from the backend's OpenAPI.
- Local dev: Docker Compose (postgres, api, worker, frontend). The deployment target is still undecided.

## Architecture rules

- **Never write to ClickUp.** Connectors are read-only, and that is a product requirement. ClickUp has no read-only tokens: the bot's token can do whatever the bot's workspace role allows. Read-only access therefore rests on the bot's role and on the code using only GET.
- Tool-specific types stay inside `connectors/<tool>/`. Everything else uses the canonical models in `domain/`, keyed by `(source, external_id)`.
- API requests read only from our own database. They never call ClickUp directly, with one exception: the OAuth callback exchanges the code for a token and calls `GET /v2/user` and `GET /v2/team`. Data from ClickUp only gets into our database through the sync, which runs in the worker.
- Sync runs come from the scheduler or from the UI's "Sincronizar agora" button (`POST /sync` → `sync_runs` row with status `pending` → picked up by the worker). Only one sync runs at a time (Postgres advisory lock), and manual syncs have a cooldown. Respect ClickUp's `X-RateLimit-*` headers and back off on HTTP 429.
- The ClickUp token is a personal `pk_...` token for the bot user, read from env. It is never committed.
- The bot token **never** reads other users' time entries; it doesn't have the role for it.
- Phase 2 rules:
  - Web app login uses LDAP (search with a service account, then bind as the user), with server-side sessions in Postgres and an HttpOnly cookie. Never store or log passwords.
  - Time entries are fetched per person with that person's OAuth token (`Authorization: Bearer ...`), **without** the `assignee` param.
  - ClickUp has no token scopes, so OAuth tokens can write. Keep them Fernet-encrypted at rest. Never put them in logs, API responses or `raw` columns. A 401 on a person's token marks their connection `revoked`; it does not fail the whole sync.
  - Users see only their own time entries. Who may see other people's hours is still undecided; don't add that access without asking. LDAP ↔ ClickUp identity verification is a deliberate future step (`identity_verified_at` is reserved for it).
- ClickUp API gotchas, checked against the official docs (details in `ARCHITECTURE.md` › "Endpoints de leitura do ClickUp"):
  - The personal token goes in `Authorization: pk_...` with no `Bearer` prefix.
  - In v2, "team" means workspace.
  - Timestamps and durations are in ms.
  - `GET /v2/team/{id}/task` returns 100 tasks per page and has no `last_page`; stop paging on a short page. It excludes subtasks and closed tasks unless you ask for them.
  - Milestones are tasks with `custom_item_id == 1`.
  - Time entries have no pagination, so query in date chunks. Reading other users' entries needs Owner/Admin. Without `assignee`, the endpoint returns the token owner's own entries.
  - The rate limit is per token.
- `ARCHITECTURE.md` is the source of truth for the HTTP API contract (`/api/v1`), the database schema, the ClickUp endpoints used and the sync steps. Keep it in sync when the code diverges. Items marked "(a confirmar)" there are unverified assumptions about the ClickUp API. Check them before relying on them, then update the doc.

## Testing

By the user's request, no test suite until an MVP exists. Don't add tests or test tooling unless asked.

## Commands

Available now (repo root):

```bash
uv sync                      # create/update .venv from uv.lock
uv run scarlet-scribe        # run the placeholder entry point
uv add <pkg>                 # add a dependency
```

To be created in the first MVP step (update this section once they exist): `backend/` uv commands, `frontend/` npm scripts and `docker compose up`.
