"""Spike F1-04: valida o comportamento real da API v2 do ClickUp com o token do bot.

Uso (a partir da raiz do repositório):

    uv run --directory backend python scripts/clickup_spike.py [--max-pages N] [--max-list-probes N]

Somente leitura: todas as requisições são GET. O token vem do ambiente ou do
`.env` da raiz, pelo `config.py`, e nunca é impresso.

A saída só traz dados não sensíveis: contagens, tipos de campos, status HTTP,
nomes de headers e de chaves, e ids truncados. Nada de nomes de pessoas,
e-mails, nomes ou conteúdo de tarefas, nem nomes de spaces, folders ou lists.

Usa o `ClickUpClient` do Conector para usuário, spaces, folders e lists. As
tarefas, o `GET /v2/team`, o plano e as lists por tarefa vão por um GET próprio
(httpx), porque o spike precisa do JSON original (tipos das datas, chaves
presentes) e dos headers de cada resposta.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections import Counter
from collections.abc import Generator, Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import SecretStr

from scarlet_scribe.config import Settings
from scarlet_scribe.connectors.clickup.client import BASE_URL, ClickUpClient, ClickUpError
from scarlet_scribe.connectors.clickup.schemas import ClickUpRef

PAGE_SIZE = 100
MIN_INTERVAL_SECONDS = 0.8  # ~75 req/min no máximo, abaixo do limite de 100.
DATE_FIELDS = (
    "date_created",
    "date_updated",
    "date_closed",
    "date_done",
    "start_date",
    "due_date",
    "time_estimate",
)
RATE_HEADERS = ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset")


class _ScriptSettings(Settings):
    # O spike não usa o banco.
    database_url: str | None = None


def mask(value: object) -> str:
    """Id truncado: só os 3 primeiros caracteres."""
    text = str(value)
    return text[:3] + "…" if len(text) > 3 else text


def counts(values: Iterable[object]) -> str:
    c = Counter(values)
    return ", ".join(f"{k!s}: {v}" for k, v in sorted(c.items(), key=lambda kv: str(kv[0]))) or "(vazio)"


# --- Observação de headers e contagem de requisições ------------------------


@dataclass
class HeaderSample:
    origin: str
    label: str
    status: int
    values: dict[str, str | None]
    local_time: float


@dataclass
class Observer:
    samples: list[HeaderSample] = field(default_factory=list)

    def record(self, origin: str, label: str, status: int, headers: httpx.Headers) -> None:
        self.samples.append(
            HeaderSample(origin, label, status, {h: headers.get(h) for h in RATE_HEADERS}, time.time())
        )

    @property
    def total(self) -> int:
        return len(self.samples)


class _ObservingTransport(httpx.AsyncBaseTransport):
    """Transport do `ClickUpClient` que só conta requisições e guarda os headers de rate limit."""

    def __init__(self, observer: Observer) -> None:
        self._inner = httpx.AsyncHTTPTransport()
        self._observer = observer

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET":  # defesa extra: o spike é somente leitura
            raise RuntimeError("o spike só faz GET")
        response = await self._inner.handle_async_request(request)
        self._observer.record("cliente", "cliente", response.status_code, response.headers)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


class _HeaderAuth(httpx.Auth):
    """Token pessoal sem prefixo, sem expor o valor em `repr`."""

    def __init__(self, token: SecretStr) -> None:
        self._token = token

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = self._token.get_secret_value()
        yield request

    def __repr__(self) -> str:
        return "<_HeaderAuth>"


class RawGet:
    """GET direto (httpx), com pausa mínima entre chamadas e respeito ao `X-RateLimit-*`."""

    def __init__(self, token: SecretStr, observer: Observer) -> None:
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            auth=_HeaderAuth(token),
            timeout=httpx.Timeout(30.0),
            headers={"Accept": "application/json"},
        )
        self._observer = observer
        self._last = 0.0

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get(self, label: str, path: str, params: list[tuple[str, str]] | None = None) -> tuple[int, Any]:
        for attempt in range(2):
            wait = self._last + MIN_INTERVAL_SECONDS - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()
            try:
                response = await self._http.get(path, params=params)
            except httpx.HTTPError as exc:
                print(f"  [{label}] erro de rede: {type(exc).__name__}")
                return 0, None
            self._observer.record("httpx", label, response.status_code, response.headers)
            remaining = response.headers.get("X-RateLimit-Remaining")
            if response.status_code == 429 or (remaining is not None and remaining.strip() in {"0", "1", "2"}):
                pause = _seconds_until_reset(response.headers)
                print(f"  [{label}] rate limit perto do fim (status {response.status_code}); pausa de {pause:.0f}s")
                await asyncio.sleep(pause)
                if response.status_code == 429 and attempt == 0:
                    continue
            try:
                body = response.json()
            except ValueError:
                body = None
            return response.status_code, body
        return 429, None


def _seconds_until_reset(headers: httpx.Headers) -> float:
    raw = headers.get("X-RateLimit-Reset")
    try:
        reset = float(raw) if raw is not None else None
    except ValueError:
        reset = None
    if reset is None:
        return 10.0
    if reset > 10**12:
        reset /= 1000
    return min(max(reset - time.time(), 1.0), 65.0)


def error_detail(body: Any) -> str:
    if isinstance(body, dict):
        parts = [str(body.get("err", ""))[:120], f"ECODE={body.get('ECODE')}" if body.get("ECODE") else ""]
        return "; ".join(p for p in parts if p)
    return ""


# --- Tarefas -----------------------------------------------------------------


@dataclass
class TaskFetch:
    label: str
    status: int = 200
    error: str = ""
    page_sizes: list[int] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    top_level_keys: set[str] = field(default_factory=set)

    @property
    def ids(self) -> set[str]:
        return {str(t.get("id")) for t in self.tasks}

    def summary(self) -> str:
        if self.status != 200:
            return f"HTTP {self.status} ({self.error})"
        trunc = " (TRUNCADO pelo --max-pages)" if self.truncated else ""
        return (
            f"HTTP 200; {len(self.page_sizes)} página(s), tamanhos {self.page_sizes}; "
            f"{len(self.tasks)} tarefas, {len(self.ids)} ids distintos{trunc}"
        )


async def fetch_tasks(
    raw: RawGet,
    path: str,
    label: str,
    params: list[tuple[str, str]],
    max_pages: int,
) -> TaskFetch:
    result = TaskFetch(label)
    for page in range(max_pages):
        status, body = await raw.get(label, path, [*params, ("page", str(page))])
        if status != 200 or not isinstance(body, dict):
            result.status, result.error = status, error_detail(body)
            return result
        result.top_level_keys |= set(body)
        batch = body.get("tasks") or []
        result.page_sizes.append(len(batch))
        result.tasks.extend(batch)
        if len(batch) < PAGE_SIZE:
            return result
    result.truncated = True
    return result


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, str):
        return "str-numérica" if value.strip().lstrip("-").isdigit() else ("str-vazia" if not value.strip() else "str")
    return type(value).__name__


def archived_flags(tasks: list[dict[str, Any]]) -> str:
    return counts(t.get("archived", "ausente") for t in tasks)


# --- Main ----------------------------------------------------------------------


async def run(args: argparse.Namespace) -> int:
    settings = _ScriptSettings()
    if settings.clickup_api_token is None or not settings.clickup_team_id:
        print("Erro: CLICKUP_API_TOKEN e CLICKUP_TEAM_ID precisam estar definidos.", file=sys.stderr)
        return 2
    team_id = settings.clickup_team_id
    configured_spaces = settings.clickup_space_ids
    observer = Observer()
    raw = RawGet(settings.clickup_api_token, observer)
    client = ClickUpClient.from_settings(settings, transport=_ObservingTransport(observer))

    try:
        print(f"Workspace configurado: {mask(team_id)}; spaces configurados: {len(configured_spaces)}")

        # --- Usuário (cliente) e members/papel (GET direto, para ver as chaves) ---
        bot = await client.get_user()
        print(f"\n[user] GET /v2/user (cliente): ok; id do bot {mask(bot.id)}")

        status, body = await raw.get("team", "/team")
        print(f"\n[11 e 8] GET /v2/team: HTTP {status}")
        members: list[dict[str, Any]] = []
        if status == 200 and isinstance(body, dict):
            teams = body.get("teams") or []
            print(f"  workspaces visíveis: {len(teams)}; o configurado está entre eles: "
                  f"{any(str(t.get('id')) == team_id for t in teams)}")
            team = next((t for t in teams if str(t.get("id")) == team_id), None)
            if team:
                print(f"  chaves do team: {sorted(team)}")
                members = team.get("members") or []
                print(f"  members: {len(members)}")
                if members:
                    print(f"  chaves de members[]: {sorted({k for m in members for k in m})}")
                    print(f"  chaves de members[].user: {sorted({k for m in members for k in (m.get('user') or {})})}")
                    print(f"  members[].user.role: {counts((m.get('user') or {}).get('role') for m in members)}")
                    print(f"  members[].user.role_key: {counts((m.get('user') or {}).get('role_key') for m in members)}")
                    print(f"  members[].user.role_subtype: "
                          f"{counts((m.get('user') or {}).get('role_subtype') for m in members)}")
                    me = next((m for m in members if (m.get("user") or {}).get("id") == bot.id), None)
                    if me is None:
                        print("  o bot NÃO aparece em members")
                    else:
                        u = me.get("user") or {}
                        print(f"  bot em members: role={u.get('role')!r}, role_key={u.get('role_key')!r}, "
                              f"role_subtype={u.get('role_subtype')!r}; chaves fora de user: "
                              f"{sorted(k for k in me if k != 'user')}")
        else:
            print(f"  erro: {error_detail(body)}")
        member_ids = {str((m.get("user") or {}).get("id")) for m in members}

        # --- Plano ---
        status, body = await raw.get("plan", f"/team/{team_id}/plan")
        print(f"\n[4] GET /v2/team/{{team_id}}/plan: HTTP {status}")
        if status == 200 and isinstance(body, dict):
            print(f"  chaves: {sorted(body)}; plan_name={body.get('plan_name')!r}; plan_id={body.get('plan_id')!r}")
        else:
            print(f"  erro: {error_detail(body)}")

        # --- Estrutura (cliente) ---
        print("\n[5, 6 e 7] Estrutura (cliente do Conector)")
        spaces = await client.get_spaces(team_id)
        archived_spaces = await client.get_spaces(team_id, archived=True)
        space_ids = {s.id for s in spaces}
        print(f"  spaces visíveis (archived=false): {len(spaces)}; com archived=true: {len(archived_spaces)}")
        for sid in configured_spaces:
            print(f"  space configurado {mask(sid)} visível: {sid in space_ids}")
        scan_spaces = [s for s in spaces if not configured_spaces or s.id in configured_spaces]
        others = [s for s in spaces if s not in scan_spaces]
        scan_spaces += others[: max(0, args.max_other_spaces)]
        print(f"  spaces percorridos: {len(scan_spaces)} (configurados + até {args.max_other_spaces} outros)")

        folder_ids: set[str] = set()
        list_ids: set[str] = set()
        lists_meta: list[tuple[str, int | None, str]] = []  # (list_id, task_count, space_id)
        parent_formats: Counter[str] = Counter()
        embedded_lists_present = Counter()
        n_folders_scanned_for_lists = 0
        for space in scan_spaces:
            folders = await client.get_folders(space.id)
            folderless = await client.get_folderless_lists(space.id)
            for f in folders:
                folder_ids.add(f.id)
                if "parent_folder" not in f.model_fields_set:
                    parent_formats["ausente"] += 1
                elif f.parent_folder is None:
                    parent_formats["null"] += 1
                elif isinstance(f.parent_folder, ClickUpRef):
                    parent_formats["objeto"] += 1
                else:
                    parent_formats["id (string/número)"] += 1
                embedded = (f.model_extra or {}).get("lists")
                embedded_lists_present["com lists embutidas" if isinstance(embedded, list) else "sem lists"] += 1
                if isinstance(embedded, list):
                    for lst in embedded:
                        list_ids.add(str(lst.get("id")))
                        lists_meta.append((str(lst.get("id")), _int_or_none(lst.get("task_count")), space.id))
            for lst in folderless:
                list_ids.add(lst.id)
                lists_meta.append((lst.id, _int_or_none((lst.model_extra or {}).get("task_count")), space.id))
            # Confere, em poucos folders, se as lists embutidas batem com GET /folder/{id}/list.
            for f in folders[: max(0, args.max_folder_checks - n_folders_scanned_for_lists)]:
                n_folders_scanned_for_lists += 1
                via_endpoint = {lst.id for lst in await client.get_folder_lists(f.id)}
                embedded_ids = {str(x.get("id")) for x in ((f.model_extra or {}).get("lists") or [])}
                print(f"  folder {mask(f.id)}: lists embutidas {len(embedded_ids)}, via endpoint {len(via_endpoint)}, "
                      f"iguais: {embedded_ids == via_endpoint}")
                list_ids |= via_endpoint
            task_count = sum(m[1] or 0 for m in lists_meta if m[2] == space.id)
            print(f"  space {mask(space.id)} (configurado: {space.id in configured_spaces}): folders {len(folders)}, "
                  f"lists fora de folder {len(folderless)}, soma de task_count das lists {task_count}")
        print(f"  total percorrido: folders {len(folder_ids)}, lists {len(list_ids)}")
        print(f"[6] parent_folder nas folders: {counts(parent_formats.elements()) if parent_formats else '(sem folders)'}")
        print(f"    subfolders (parent_folder preenchido): "
              f"{parent_formats['objeto'] + parent_formats['id (string/número)']}")
        print(f"    folders {dict(embedded_lists_present)}")

        # --- Tarefas ---
        path = f"/team/{team_id}/task"
        base = [("subtasks", "true"), ("include_closed", "true")]
        task_spaces = [] if args.all_spaces else configured_spaces
        base += [("space_ids[]", s) for s in task_spaces]
        scope = "space configurado" if task_spaces else "workspace inteiro"
        print(f"\n[10, 1, 2] GET /v2/team/{{team_id}}/task ({scope}, subtasks=true, include_closed=true)")

        a = await fetch_tasks(raw, path, "tasks", base, args.max_pages)
        print(f"  A (sem archived, sem custom_items[]): {a.summary()}")
        print(f"    chaves no topo da resposta: {sorted(a.top_level_keys)}")
        b = await fetch_tasks(raw, path, "tasks+archived", [*base, ("archived", "true")], args.max_pages)
        print(f"  B (archived=true): {b.summary()}")
        c = await fetch_tasks(
            raw, path, "tasks+custom_items", [*base, ("custom_items[]", "0"), ("custom_items[]", "1")], args.max_pages
        )
        print(f"  C (custom_items[]=0&1): {c.summary()}")
        d = await fetch_tasks(raw, path, "tasks+milestones", [*base, ("custom_items[]", "1")], args.max_pages)
        print(f"  D (custom_items[]=1): {d.summary()}")

        # [1] Arquivadas
        print("\n[1] Tarefas arquivadas")
        print(f"  A: campo archived: {archived_flags(a.tasks)}")
        if b.status == 200:
            print(f"  B: campo archived: {archived_flags(b.tasks)}")
            print(f"  B - A: {len(b.ids - a.ids)} ids; A - B: {len(a.ids - b.ids)} ids; interseção: {len(a.ids & b.ids)}")

        # Probe por list: GET /v2/list/{id}/task com e sem archived=true
        archived_list_ids = [
            str((t.get("list") or {}).get("id")) for t in b.tasks if t.get("archived") is True and t.get("list")
        ]
        candidates = list(dict.fromkeys(archived_list_ids))
        by_count = sorted(
            (m for m in lists_meta if not task_spaces or m[2] in task_spaces),
            key=lambda m: -(m[1] or 0),
        )
        candidates += [m[0] for m in by_count if m[0] not in candidates]
        found = False
        for list_id in candidates[: max(0, args.max_list_probes)]:
            lp = [("subtasks", "true"), ("include_closed", "true"), ("page", "0")]
            s1, body1 = await raw.get("list-tasks", f"/list/{list_id}/task", lp)
            s2, body2 = await raw.get("list-tasks+archived", f"/list/{list_id}/task", [*lp, ("archived", "true")])
            t1 = (body1 or {}).get("tasks") or [] if isinstance(body1, dict) else []
            t2 = (body2 or {}).get("tasks") or [] if isinstance(body2, dict) else []
            ids1 = {str(t.get("id")) for t in t1}
            ids2 = {str(t.get("id")) for t in t2}
            keys2 = sorted(body2) if isinstance(body2, dict) else []
            print(f"  list {mask(list_id)}: sem archived HTTP {s1} ({len(t1)} tarefas, archived: {archived_flags(t1)}); "
                  f"archived=true HTTP {s2} ({len(t2)} tarefas, archived: {archived_flags(t2)}); "
                  f"interseção {len(ids1 & ids2)}; chaves {keys2}")
            if t2:
                found = True
                print(f"    arquivadas desta list presentes em A: {len(ids2 & a.ids)}/{len(ids2)}; "
                      f"em B: {len(ids2 & b.ids)}/{len(ids2)}")
                break
        if not found:
            print(f"  nenhuma das {min(len(candidates), args.max_list_probes)} lists sondadas devolveu tarefas "
                  "com archived=true")

        # [2] Marcos
        print("\n[2] Marcos")
        print(f"  A: custom_item_id: {counts(t.get('custom_item_id', 'ausente') for t in a.tasks)}")
        if c.status == 200:
            print(f"  C: custom_item_id: {counts(t.get('custom_item_id', 'ausente') for t in c.tasks)}")
            print(f"  C - A: {len(c.ids - a.ids)} ids; A - C: {len(a.ids - c.ids)} ids")
        if d.status == 200:
            print(f"  D: custom_item_id: {counts(t.get('custom_item_id', 'ausente') for t in d.tasks)}")
            print(f"  marcos de D presentes em A: {len(d.ids & a.ids)}/{len(d.ids)}")

        # [7] Colisões
        print("\n[7] Colisões de ids")
        sets = {"spaces": space_ids, "folders": folder_ids, "lists": list_ids, "tarefas(A)": a.ids}
        names = list(sets)
        for i, n1 in enumerate(names):
            for n2 in names[i + 1:]:
                inter = sets[n1] & sets[n2]
                sample = ", ".join(mask(x) for x in sorted(inter)[:3])
                print(f"  {n1} ({len(sets[n1])}) ∩ {n2} ({len(sets[n2])}): {len(inter)}"
                      + (f" ex.: {sample}" if inter else ""))
        print(f"  formato dos ids: spaces {counts(type_name(x) for x in space_ids)}; "
              f"folders {counts(type_name(x) for x in folder_ids)}; lists {counts(type_name(x) for x in list_ids)}; "
              f"tarefas {counts(type_name(x) for x in a.ids)}")

        # [8] Assignees fora de members
        print("\n[8] Assignees fora de members")
        assignee_ids = {str(u.get("id")) for t in a.tasks for u in (t.get("assignees") or [])}
        creator_ids = {str((t.get("creator") or {}).get("id")) for t in a.tasks if t.get("creator")}
        print(f"  assignees distintos: {len(assignee_ids)}; fora de members: {len(assignee_ids - member_ids)}")
        print(f"  creators distintos: {len(creator_ids)}; fora de members: {len(creator_ids - member_ids)}")
        print(f"  chaves de assignees[]: {sorted({k for t in a.tasks for u in (t.get('assignees') or []) for k in u})}")

        # [9] Datas e campos
        print("\n[9] Tipos de datas e campos (amostra A)")
        n = len(a.tasks)
        for f_name in DATE_FIELDS:
            print(f"  {f_name}: {counts(type_name(t[f_name]) if f_name in t else 'ausente' for t in a.tasks)}")
        print(f"  priority: {counts(type_name(t.get('priority', 'ausente')) for t in a.tasks)}")
        print(f"  priority.priority: {counts((t.get('priority') or {}).get('priority') for t in a.tasks)}")
        print(f"  priority.id: {counts(type_name((t.get('priority') or {}).get('id')) for t in a.tasks)}")
        print(f"  status.type: {counts((t.get('status') or {}).get('type') for t in a.tasks)}")
        print(f"  parent (subtarefa): {counts('preenchido' if t.get('parent') else 'null' for t in a.tasks)}")
        print(f"  list/folder/space presentes: "
              f"{counts(tuple(k in t for k in ('list', 'folder', 'space')) for t in a.tasks)}")
        print(f"  folder.hidden: {counts((t.get('folder') or {}).get('hidden') for t in a.tasks)}")
        print(f"  chaves das tarefas: {sorted({k for t in a.tasks for k in t})}")
        print(f"  ({n} tarefas analisadas)")

        # [3] Headers de rate limit
        print("\n[3] Headers X-RateLimit-*")
        oks = [s for s in observer.samples if s.status == 200]
        with_all = [s for s in oks if all(s.values[h] is not None for h in RATE_HEADERS)]
        print(f"  respostas 200: {len(oks)}; com os 3 headers: {len(with_all)}")
        print(f"  por origem: {counts((s.origin, all(s.values[h] is not None for h in RATE_HEADERS)) for s in oks)}")
        print(f"  X-RateLimit-Limit observados: {counts(s.values['X-RateLimit-Limit'] for s in oks)}")
        rem = [int(s.values["X-RateLimit-Remaining"]) for s in with_all
               if (s.values["X-RateLimit-Remaining"] or "").strip().isdigit()]
        if rem:
            print(f"  X-RateLimit-Remaining: mín {min(rem)}, máx {max(rem)}")
        for s in with_all[:3] + with_all[-2:]:
            reset = float(s.values["X-RateLimit-Reset"] or 0)
            print(f"  [{s.label}] Reset={int(reset)} ({len(str(int(reset)))} dígitos); "
                  f"relógio local {s.local_time:.0f}; delta se segundos {reset - s.local_time:+.1f}s; "
                  f"delta se ms {reset / 1000 - s.local_time:+.1f}s; Remaining={s.values['X-RateLimit-Remaining']}")
        others_status = [s for s in observer.samples if s.status != 200]
        if others_status:
            print(f"  respostas não 200: {counts((s.label, s.status) for s in others_status)}; "
                  f"com headers: {sum(all(s.values[h] is not None for h in RATE_HEADERS) for s in others_status)}")

        print(f"\nTotal de requisições GET: {observer.total}")
        return 0
    except ClickUpError as exc:
        print(f"Erro do cliente do ClickUp: {exc}", file=sys.stderr)
        return 1
    finally:
        await client.aclose()
        await raw.aclose()


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-pages", type=int, default=10, help="teto de páginas por variante de busca")
    parser.add_argument("--max-list-probes", type=int, default=4, help="lists sondadas com archived=true")
    parser.add_argument("--max-folder-checks", type=int, default=2, help="folders conferidas via /folder/{id}/list")
    parser.add_argument("--all-spaces", action="store_true", help="busca tarefas sem filtrar por space_ids[]")
    parser.add_argument("--max-other-spaces", type=int, default=5, help="spaces não configurados a percorrer")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
