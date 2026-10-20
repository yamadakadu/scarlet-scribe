# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project goal

An integration layer for corporate tools. ClickUp is the first one. Data reaches our own database by two routes. A dedicated **read-only "bot" user** pulls the workspace structure, members, tasks and milestones. **Time entries come from each person's own ClickUp OAuth token**: the person logs into the web app via the company **LDAP**, then connects their ClickUp account. The web app shows everything in one place. More tools will be added later. `PROJECT.md` has the original idea (in Portuguese). **`ARCHITECTURE.md` holds the agreed decisions, the phases and the risks to validate. Read it before starting a feature.**

The user writes in Portuguese. Reply in Portuguese.

## Current state and phases

Phase 1 is under way; `PLANO_DE_EXECUCAO.md` › "Acompanhamento" has the status of each task. The repo is a monorepo: the Python package lives in `backend/` (uv project, `src/` layout) and `frontend/` holds the Vite app. Already integrated: the infrastructure (`config.py`, `docker-compose.yml`, Alembic), the ClickUp HTTP client and schemas (`connectors/clickup/`), the canonical models, Phase 1 tables and migration `0001` (`domain/`, `db/`), and the frontend scaffold (`frontend/`). The mapper, sync, API and real screens are still to come.

Work happens in two phases:
- **Phase 1 (initial structure):** the bot token, structure, tasks, milestones, sync, read API and frontend. It has **no login and no time entries**, and all routes are open.
- **Phase 2 (separate):** authentication (LDAP and ClickUp OAuth) and time entries.

**Do not build Phase 2 pieces (auth, sessions, OAuth, `time_entries`) during Phase 1.** Phase 2 is now split: login and account connections (F2-01 to F2-04) come before Phase I, and time entries come after it. It still opens only when the user releases it. Sections marked "(Fase 2)" in `ARCHITECTURE.md` describe the agreed design for later.

**Phase M (multi-integration)** starts alongside F1-11 and comes before Phase 2. It adds a sidebar that lists the connected apps (icons only, one per app) and brings in GitLab as a second source (gitlab.com or the company's self-hosted instance, whichever is available; the code treats both the same, and switching later follows FM-11): repositories, merge requests and commits, read-only, using a bot token. For now the apps are only shown side by side: no cross-tool data and no writes. Writing at specific points is planned for later and needs an explicit rule change first. The design is in `ARCHITECTURE.md` › "Fase M: multi-integração"; the tasks (FM-01 to FM-11) and a checklist are in `PLANO_DE_EXECUCAO.md` › "Fase M". GitLab issues, read-only, extend Phase M (FM-12 to FM-17).

**Phase I (ClickUp ↔ GitLab integration with writes) is planned, not open.** Agreed with the user on 2026-10-20:
- From a task's modal in our web app, a logged-in person creates a GitLab issue linked to the task.
- When an MR closes that issue, the worker **only comments** on the ClickUp task; the system never changes a task's status or closes it.
- Writes use **each person's own OAuth token** (ClickUp and GitLab), never a bot, and only through a closed list of endpoints (`POST /projects/:id/issues` on GitLab, `POST /v2/task/{id}/comment` on ClickUp).
- They also go through an audited write queue (`write_actions`) with a `WRITES_ENABLED` switch that defaults to off and only simulates, plus allowlists of projects and lists.
- A new agent, **Mensageiro**, owns the writers (`connectors/*/writer.py`) and the queue (`actions/`).
- Order: GitLab issues (read-only), then Phase 2 login and account connections only (F2-01 to F2-04, GitLab OAuth included), then Phase I. Phase 2 time entries come after Phase I.

Until task FI-02 changes this file, `ARCHITECTURE.md`, the policy and the hooks, **the read-only rules below still apply in full**. The tasks, safeguards and test approach are in `PLANO_DE_EXECUCAO.md` › "Fase I".

`PLANO_DE_EXECUCAO.md` lists every task with its owning agent (Maestro, the orchestrator; Alicerce, Batedor, Conector, Arquivista, Sincronista, Portal, Vitrine and Revisor; Guardião and Ponte join in Phase 2), dependencies, waves, file-ownership boundaries and done criteria. When acting as one of those agents, change only files in that agent's area, and report divergences from `ARCHITECTURE.md` to the Maestro instead of editing it.

Agent definitions live in `.claude/agents/`. Each agent works in its own worktree on the branch `<agente>/<feature>`, and every commit subject starts with `<agente>/<feature>: `. The Maestro creates each worktree with `python3 .claude/scripts/novo_worktree.py <agente> <feature>`. The script branches from `main` into `.claude/worktrees/<agente>-<feature>` and links the worktree's `.env` to the main tree's `.env`, which worktrees don't otherwise get because it's gitignored. Each agent's model and effort are set in its frontmatter; when spawning, the Maestro varies them per task exactly as `PLANO_DE_EXECUCAO.md` › "Modelos e esforço dos agentes" says (that table is the instruction that allows passing `model` and `effort` per invocation).

Hooks enforce these rules. The policy is in `.claude/hooks/policy.json`; the hook scripts are in `.claude/hooks/` (Claude Code) and `.githooks/` (git pre-commit and commit-msg). See `PLANO_DE_EXECUCAO.md` › "Hooks". If a hook blocks you, never bypass it: no `--no-verify`, no `core.hooksPath` change, no renaming or moving files to dodge a rule. Unstage the file, report to the Maestro, and let the user decide. After changing the policy or a hook, run `python3 .claude/hooks/selfcheck.py`.

## Stack

- Backend: Python 3.12, FastAPI, httpx (async), Pydantic v2, SQLAlchemy 2 + Alembic, PostgreSQL, APScheduler in a separate worker process. Managed with **uv** (`uv_build` backend, `src/` layout).
- Frontend: Vite + React + TypeScript, TanStack Query, with a TS client generated from the backend's OpenAPI.
- Local dev: Docker Compose (postgres, api, worker, frontend). The deployment target is still undecided.

## Architecture rules

- **Never write to any connected tool (ClickUp, GitLab).** Connectors are read-only, and that is a product requirement for now. Future writes at specific points need an explicit decision from the user and a matching update to this file, `ARCHITECTURE.md` and the hooks. The GitLab bot token has only the `read_api` scope, goes in the `PRIVATE-TOKEN` header, comes from env and is never committed. ClickUp has no read-only tokens: the bot's token can do whatever the bot's workspace role allows. Read-only access therefore rests on the bot's role and on the code using only GET.
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

The one approved exception is in Phase I, for the write code only (the writers, the write queue and its safeguards). Those tests check the exact captured request, include mandatory negative cases, and must fail against a deliberately broken writer. The user sees the cases and the pytest output before integration. The details are in `PLANO_DE_EXECUCAO.md` › "Fase I".

## Showing progress to the user

When a review finishes and the work is integrated into `main`, bring the whole stack up with Docker Compose (`docker compose up -d --build` from the repo root) so the user can look at it in the browser. Then tell them the URLs (frontend on `:5173`, API on `:8000`) and what changed on screen. This is the user's standing preference.

## Commands

Available now (from the repo root; requires Docker Compose 2.24+):

```bash
uv sync --directory backend                        # create/update backend/.venv from uv.lock
uv add --directory backend <pkg>                   # add a dependency
docker compose up -d postgres                      # start Postgres (dev defaults work without .env)
docker compose run --rm migrate                    # apply migrations inside Docker
uv run --directory backend alembic upgrade head    # apply migrations from the host (needs DATABASE_URL)
docker compose down                                # stop everything (add -v to drop the database volume)
```

Frontend (from `frontend/`):

```bash
npm ci                       # install exactly what package-lock.json pins
npm run dev                  # Vite on :5173, proxying /api/ to VITE_API_PROXY_TARGET (default http://localhost:8000)
npm run build                # type-check and build to dist/
npm run typecheck            # tsc on both tsconfigs
npm run lint                 # oxlint
```

`config.py` reads the `.env` at the repo root wherever the command runs; `.env.example` documents every variable. Vite does not read that file: `VITE_API_PROXY_TARGET` comes from the process environment or `frontend/.env*`. The `api` and `worker` services start once F1-08 and F1-07 create their modules. To be added later: the full `docker compose up` with the frontend (F1-12).
