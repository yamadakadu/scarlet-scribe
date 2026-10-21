"""Spike FM-03: valida o comportamento real da API v4 do GitLab com o token do bot.

Uso (a partir da raiz do worktree/repositório):

    uv run --directory backend python scripts/gitlab_spike.py

Somente leitura: todas as requisições são GET (o único método exposto é `get`).
O token vem do ambiente ou do `.env` da raiz e nunca é impresso.

A saída só traz dados não sensíveis: contagens, nomes de campos, tipos, status
HTTP e headers de paginação e de rate limit. Nomes e ids de grupos e projetos
podem aparecer; nomes de pessoas, e-mails, títulos e conteúdo de MRs e commits
nunca aparecem.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/scripts/gitlab_spike.py → raiz do repositório (ou do worktree).
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
MAX_REQUESTS = 150
PAGE_SIZE = 100
TIMEOUT = 30.0


class GitLabSpikeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    gitlab_url: str | None = None
    gitlab_api_token: SecretStr | None = None
    gitlab_group_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)
    gitlab_project_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)
    gitlab_ca_bundle: str | None = None

    @field_validator("gitlab_group_ids", "gitlab_project_ids", mode="before")
    @classmethod
    def _split(cls, v: object) -> object:
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v


class Budget(Exception):
    pass


class Spike:
    def __init__(self, base: str, token: str, verify: str | bool) -> None:
        self.base = base.rstrip("/") + "/api/v4"
        self.count = 0
        self.http = httpx.Client(
            headers={"PRIVATE-TOKEN": token},
            timeout=TIMEOUT,
            verify=verify,
            follow_redirects=False,
        )

    def get(self, path: str, **params: Any) -> httpx.Response:
        if self.count >= MAX_REQUESTS:
            raise Budget
        self.count += 1
        params = {k: v for k, v in params.items() if v is not None}
        return self.http.get(self.base + path, params=params)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def tname(v: Any) -> str:
    return type(v).__name__ if v is not None else "None"


def pag_headers(r: httpx.Response) -> str:
    keys = ("X-Page", "X-Per-Page", "X-Next-Page", "X-Prev-Page", "X-Total", "X-Total-Pages")
    parts = [f"{k}={r.headers.get(k, '<ausente>')}" for k in keys]
    return " ".join(parts)


def link_summary(r: httpx.Response) -> str:
    link = r.headers.get("Link")
    if not link:
        return "Link=<ausente>"
    out = []
    for part in link.split(","):
        part = part.strip()
        try:
            url, rel = part.split(";", 1)
        except ValueError:
            continue
        q = parse_qs(urlparse(url.strip("<> ")).query)
        out.append(f"{rel.strip()} (params: {sorted(q)})")
    return "Link: " + "; ".join(out)


def ratelimit_headers(r: httpx.Response) -> dict[str, str]:
    return {
        k: v
        for k, v in r.headers.items()
        if k.lower().startswith("ratelimit") or k.lower() == "retry-after"
    }


def fields_report(items: list[dict], wanted: tuple[str, ...]) -> None:
    print(f"  campos pedidos (presença/tipos no 1o item): ", end="")
    if not items:
        print("sem itens")
        return
    first = items[0]
    print({f: (tname(first[f]) if f in first else "AUSENTE") for f in wanted})
    print(f"  todos os campos do 1o item: {sorted(first)}")


def main() -> int:
    s = GitLabSpikeSettings()

    # Primeiro passo: só "preenchida" ou "vazia".
    section("Variáveis (preenchida/vazia)")
    status = {
        "GITLAB_URL": bool(s.gitlab_url),
        "GITLAB_API_TOKEN": bool(s.gitlab_api_token and s.gitlab_api_token.get_secret_value()),
        "GITLAB_GROUP_IDS": bool(s.gitlab_group_ids),
        "GITLAB_PROJECT_IDS": bool(s.gitlab_project_ids),
        "GITLAB_CA_BUNDLE": bool(s.gitlab_ca_bundle),
    }
    for k, v in status.items():
        print(f"  {k}: {'preenchida' if v else 'vazia'}")
    if not (status["GITLAB_URL"] and status["GITLAB_API_TOKEN"]) or not (
        status["GITLAB_GROUP_IDS"] or status["GITLAB_PROJECT_IDS"]
    ):
        print("\nParando: faltam variáveis obrigatórias (URL, token, e grupos ou projetos).")
        return 2

    assert s.gitlab_url and s.gitlab_api_token
    verify: str | bool = s.gitlab_ca_bundle or True
    sp = Spike(s.gitlab_url, s.gitlab_api_token.get_secret_value(), verify)
    host = urlparse(s.gitlab_url).hostname or ""
    now = datetime.now(UTC)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731

    try:
        if "--confidential" in sys.argv:
            run_confidential(sp, s)
        elif "--issues" in sys.argv:
            run_issues(sp, s)
        elif "--tags-avatar" in sys.argv:
            run_tags_avatar(sp, s, verify)
        else:
            run(sp, s, host, now, iso)
    except Budget:
        print(f"\nOrçamento de {MAX_REQUESTS} requisições esgotado.")
    except httpx.HTTPError as exc:
        print(f"\nErro de transporte: {type(exc).__name__}")
    print(f"\nRequisições feitas: {sp.count}/{MAX_REQUESTS} (todas GET)")
    return 0


def run(sp: Spike, s: GitLabSpikeSettings, host: str, now: datetime, iso) -> None:
    # 1. Versão
    section("1. Versão e instância")
    r = sp.get("/version")
    print(f"  GET /version -> {r.status_code}")
    if r.status_code == 200:
        j = r.json()
        print(f"  campos: {sorted(j)}  version={j.get('version')} revision={j.get('revision')}")
        print(f"  enterprise={j.get('enterprise')}")
    print(f"  host é gitlab.com: {host == 'gitlab.com'}")
    ratelimit_200 = [("/version", ratelimit_headers(r))]

    # 2. Token
    section("2. Token (personal_access_tokens/self)")
    r = sp.get("/personal_access_tokens/self")
    print(f"  GET /personal_access_tokens/self -> {r.status_code}")
    if r.status_code == 200:
        j = r.json()
        print(f"  campos: {sorted(j)}")
        print(
            f"  scopes={j.get('scopes')} active={j.get('active')} revoked={j.get('revoked')} "
            f"expires_at={j.get('expires_at')} created_at={j.get('created_at')} "
            f"last_used_at={j.get('last_used_at')}"
        )
        print(f"  só read_api: {j.get('scopes') == ['read_api']}")
    ratelimit_200.append(("/personal_access_tokens/self", ratelimit_headers(r)))

    # 3. Projetos por grupo
    section("3. Projetos dos grupos")
    project_pool: list[dict] = []
    wanted = ("id", "path_with_namespace", "web_url", "default_branch", "archived", "last_activity_at")
    for gid in s.gitlab_group_ids:
        r = sp.get(f"/groups/{gid}")
        if r.status_code == 200:
            g = r.json()
            print(f"  grupo {gid}: GET /groups/:id -> 200 full_path={g.get('full_path')}")
        else:
            print(f"  grupo {gid}: GET /groups/:id -> {r.status_code}")
        r = sp.get(
            f"/groups/{gid}/projects",
            include_subgroups="true",
            archived="false",
            per_page=PAGE_SIZE,
            page=1,
        )
        print(f"  GET /groups/{gid}/projects?include_subgroups=true&archived=false -> {r.status_code}")
        print(f"  {pag_headers(r)}")
        print(f"  {link_summary(r)}")
        if r.status_code == 200:
            items = r.json()
            print(f"  itens na pagina 1: {len(items)}")
            fields_report(items, wanted)
            project_pool.extend(items)
            ratelimit_200.append((f"/groups/{gid}/projects", ratelimit_headers(r)))
            if items:
                print(f"  projetos (id, path): {[(p['id'], p['path_with_namespace']) for p in items[:15]]}")
    for pid in s.gitlab_project_ids:
        r = sp.get(f"/projects/{pid}")
        print(f"  GET /projects/{pid} -> {r.status_code}")
        if r.status_code == 200:
            p = r.json()
            print(f"  projeto avulso: id={p['id']} path={p.get('path_with_namespace')}")
            fields_report([p], wanted)
            project_pool.append(p)

    if not project_pool:
        print("  nenhum projeto acessível; não dá para continuar os itens 4 e 5.")
        project = None
    else:
        project = max(project_pool, key=lambda p: p.get("last_activity_at") or "")
        print(f"\n  projeto usado nos itens 4 e 5 (mais recente): id={project['id']} {project['path_with_namespace']}")

    if project:
        pid = project["id"]

        # 4. Merge requests
        section("4. Merge requests")
        r = sp.get(
            f"/projects/{pid}/merge_requests",
            state="all",
            scope="all",
            per_page=PAGE_SIZE,
            order_by="updated_at",
            sort="desc",
        )
        print(f"  sem updated_after -> {r.status_code} {pag_headers(r)}")
        mrs_all: list[dict] = r.json() if r.status_code == 200 else []
        print(f"  itens na pagina 1: {len(mrs_all)}")
        ratelimit_200.append(("merge_requests", ratelimit_headers(r)))
        if mrs_all:
            first = mrs_all[0]
            wanted_mr = (
                "id", "iid", "project_id", "state", "source_branch", "target_branch",
                "author", "assignee", "assignees", "reviewers", "web_url",
                "created_at", "updated_at", "merged_at", "closed_at", "merged_by", "closed_by",
            )
            fields_report(mrs_all, wanted_mr)
            print(f"  author: campos={sorted(first['author'])}")
            for k in ("assignees", "reviewers"):
                lst = first.get(k)
                print(f"  {k}: tipo={tname(lst)} len={len(lst) if isinstance(lst, list) else '-'}"
                      f" campos={sorted(lst[0]) if lst else 'lista vazia'}")
            print(f"  estados vistos: {dict(Counter(m['state'] for m in mrs_all))}")
            for d in ("created_at", "updated_at", "merged_at", "closed_at"):
                vals = [m.get(d) for m in mrs_all]
                nn = [v for v in vals if v]
                print(f"  {d}: nao-nulos={len(nn)}/{len(vals)} exemplo-formato={nn[0] if nn else '-'}")
            print(f"  iid unicos: {len({m['iid'] for m in mrs_all})}/{len(mrs_all)}; "
                  f"id != iid em todos: {all(m['id'] != m['iid'] for m in mrs_all)}")
            ups = sorted(m["updated_at"] for m in mrs_all)
            cutoff = ups[len(ups) // 2]
            r2 = sp.get(
                f"/projects/{pid}/merge_requests",
                state="all", scope="all", per_page=PAGE_SIZE, updated_after=cutoff,
            )
            lst2 = r2.json() if r2.status_code == 200 else []
            ok = all(m["updated_at"] >= cutoff for m in lst2)
            print(f"  updated_after=<mediana das datas> -> {r2.status_code}, {len(lst2)} itens "
                  f"(de {len(mrs_all)}); todos com updated_at >= corte: {ok}")
        future = iso(now + timedelta(days=1))
        r3 = sp.get(f"/projects/{pid}/merge_requests", state="all", scope="all",
                    per_page=PAGE_SIZE, updated_after=future)
        print(f"  updated_after=amanha -> {r3.status_code}, itens={len(r3.json()) if r3.status_code == 200 else '-'}")

        # 5. Commits
        section("5. Commits (since = 90 dias)")
        since = iso(now - timedelta(days=90))
        counts: dict[str, int] = {}
        samples: dict[str, list[dict]] = {}
        for label, extra in (("branch padrão", {}), ("all=true", {"all": "true"})):
            total, page, items_acc = 0, 1, []
            while page and page <= 3:
                r = sp.get(f"/projects/{pid}/repository/commits", since=since,
                           per_page=PAGE_SIZE, page=page, **extra)
                if r.status_code != 200:
                    print(f"  {label}: pagina {page} -> {r.status_code}")
                    break
                items = r.json()
                total += len(items)
                items_acc.extend(items[:1] if page > 1 else items)
                nxt = r.headers.get("X-Next-Page", "")
                print(f"  {label}: pagina {page} -> 200, {len(items)} itens, {pag_headers(r)}")
                if page == 1:
                    ratelimit_200.append(("commits", ratelimit_headers(r)))
                page = int(nxt) if nxt else 0
            counts[label] = total
            samples[label] = items_acc
        print(f"  contagem (ate 3 paginas): {counts}")
        wanted_c = ("id", "short_id", "title", "message", "author_name", "author_email",
                    "authored_date", "committer_name", "committer_email", "committed_date",
                    "created_at", "parent_ids", "web_url")
        fields_report(samples.get("all=true") or samples.get("branch padrão") or [], wanted_c)
        a, b = samples.get("branch padrão") or [], samples.get("all=true") or []
        sha_a = {c["id"] for c in a}
        sha_b = {c["id"] for c in b}
        print(f"  shas no padrão que faltam em all=true (na amostra): {len(sha_a - sha_b)}")

    # 6. Paginação
    section("6. Paginação")
    r = sp.get("/projects", membership="true", per_page=2, page=1, order_by="id", sort="asc")
    print(f"  offset /projects?membership=true&per_page=2 -> {r.status_code}")
    print(f"  {pag_headers(r)}")
    print(f"  {link_summary(r)}")
    r = sp.get("/projects", membership="true", per_page=2, pagination="keyset", order_by="id", sort="asc")
    print(f"  keyset /projects?pagination=keyset&order_by=id&per_page=2 -> {r.status_code}")
    print(f"  {pag_headers(r)}")
    print(f"  {link_summary(r)}")
    nxt = None
    for part in r.headers.get("Link", "").split(","):
        if 'rel="next"' in part:
            nxt = part.split(";")[0].strip("<> ")
    if nxt and urlparse(nxt).hostname == urlparse(sp.base).hostname:
        if sp.count < MAX_REQUESTS:
            sp.count += 1
            r2 = sp.http.get(nxt)  # URL de próxima página devolvida pelo servidor, ainda GET
            print(f"  keyset seguindo rel=next -> {r2.status_code}, itens="
                  f"{len(r2.json()) if r2.status_code == 200 else '-'}")
    if s.gitlab_group_ids:
        gid = s.gitlab_group_ids[0]
        r = sp.get(f"/groups/{gid}/projects", include_subgroups="true", archived="false",
                   per_page=2, page=1)
        print(f"  offset /groups/{gid}/projects per_page=2 -> {r.status_code}")
        print(f"  {pag_headers(r)}")
        print(f"  {link_summary(r)}")

    # 7. Rate limit
    section("7. Rate limit (headers RateLimit-* em respostas 200)")
    for where, h in ratelimit_200:
        print(f"  {where}: {h or 'nenhum header RateLimit-*'}")
    r = sp.get("/version")
    date = r.headers.get("Date")
    rl = ratelimit_headers(r)
    print(f"  GET /version de novo -> {r.status_code}: {rl}")
    reset = next((v for k, v in r.headers.items() if k.lower() == "ratelimit-reset"), None)
    if reset and reset.isdigit():
        print(f"  RateLimit-Reset={reset}; epoch atual={int(now.timestamp())}; "
              f"Date da resposta={date}; (valor ~ epoch absoluto se próximo do atual, "
              f"senão segundos restantes)")

    # 8. Membros
    section("8. Membros do grupo (members/all)")
    for gid in s.gitlab_group_ids[:1]:
        r = sp.get(f"/groups/{gid}/members/all", per_page=PAGE_SIZE)
        print(f"  GET /groups/{gid}/members/all -> {r.status_code} {pag_headers(r)}")
        if r.status_code == 200:
            items = r.json()
            print(f"  itens na pagina 1: {len(items)}")
            if items:
                print(f"  campos: {sorted(items[0])}")
                print(f"  tipos: { {k: tname(v) for k, v in items[0].items()} }")
                print(f"  access_level: {dict(Counter(m.get('access_level') for m in items))}")
                print(f"  state: {dict(Counter(m.get('state') for m in items))}")
                print(f"  email presente em algum membro: {any('email' in m for m in items)}")
        else:
            print(f"  corpo: chaves={sorted(r.json()) if r.headers.get('content-type','').startswith('application/json') and isinstance(r.json(), dict) else '-'}")


def run_tags_avatar(sp: Spike, s: GitLabSpikeSettings, verify: str | bool) -> None:
    """ML-01: tags do repositório e avatar_url (rode com --tags-avatar)."""
    projects: list[dict] = []
    for gid in s.gitlab_group_ids:
        r = sp.get(f"/groups/{gid}/projects", include_subgroups="true", archived="false",
                   per_page=PAGE_SIZE, page=1)
        print(f"  GET /groups/{gid}/projects -> {r.status_code}")
        if r.status_code == 200:
            projects.extend(r.json())
    for pid in s.gitlab_project_ids:
        r = sp.get(f"/projects/{pid}")
        if r.status_code == 200:
            projects.append(r.json())
    projects = projects[:20]
    print(f"  projetos: {len(projects)}")

    section("9. avatar_url e visibilidade")
    print(f"  visibility (listagem do grupo): {dict(Counter(p.get('visibility') for p in projects))}")
    print(f"  avatar_url na listagem: chave presente em {sum('avatar_url' in p for p in projects)}/"
          f"{len(projects)}; nao-nulos={sum(bool(p.get('avatar_url')) for p in projects)}")
    shown_fmt = False
    for p in projects:
        r = sp.get(f"/projects/{p['id']}")
        d = r.json() if r.status_code == 200 else {}
        a = d.get("avatar_url")
        list_a = p.get("avatar_url")
        print(f"  projeto {p['id']}: GET /projects/:id -> {r.status_code} visibility={d.get('visibility')} "
              f"avatar(detalhe)={'null' if a is None else 'preenchido'} "
              f"avatar(lista)={'null' if list_a is None else 'preenchido'}")
        if a and not shown_fmt:
            u = urlparse(a)
            print(f"  formato: esquema={u.scheme} host={u.hostname} caminho={u.path.rsplit('/', 1)[0]}/<arquivo> "
                  f"query={'sim' if u.query else 'nao'}; mesma instancia: {u.hostname == urlparse(sp.base).hostname}")
            shown_fmt = True
            if sp.count < MAX_REQUESTS:
                sp.count += 1
                with httpx.Client(timeout=TIMEOUT, verify=verify, follow_redirects=False) as anon:
                    ra = anon.get(a)  # GET sem PRIVATE-TOKEN
                print(f"  GET avatar SEM token -> {ra.status_code} content-type={ra.headers.get('content-type')} "
                      f"bytes={len(ra.content)} location={'sim' if ra.headers.get('location') else 'nao'}")
    if not shown_fmt:
        print("  nenhum projeto tem avatar_url nao nulo (sem ícone).")

    section("10. Tags do repositório")
    for p in projects:
        pid = p["id"]
        r = sp.get(f"/projects/{pid}/repository/tags", per_page=PAGE_SIZE, order_by="updated", sort="desc")
        print(f"  projeto {pid}: GET .../repository/tags -> {r.status_code}")
        print(f"    {pag_headers(r)}")
        print(f"    {link_summary(r)}")
        if r.status_code != 200:
            continue
        tags = r.json()
        print(f"    tags na pagina 1: {len(tags)}")
        if not tags:
            continue
        t0 = tags[0]
        print(f"    campos: {sorted(t0)}")
        print(f"    tipos: { {k: tname(v) for k, v in t0.items() if k != 'commit'} }")
        c = t0.get("commit") or {}
        print(f"    commit campos: {sorted(c)}")
        print(f"    protected: {dict(Counter(t.get('protected') for t in tags))}")
        print(f"    message nao-nula (anotadas): {sum(bool(t.get('message')) for t in tags)}/{len(tags)}")
        print(f"    target != commit.id: {sum(t.get('target') != (t.get('commit') or {}).get('id') for t in tags)}/{len(tags)}")
        print(f"    commit.id tem {len(c.get('id', ''))} chars; short_id tem {len(c.get('short_id', ''))}")
        for k in ("created_at", "committed_date", "authored_date"):
            print(f"    commit.{k}: {c.get(k, 'AUSENTE')}; tag.created_at: {t0.get('created_at', 'AUSENTE')}")
            break


def _projects_for_issues(sp: Spike, s: GitLabSpikeSettings) -> list[dict]:
    projects: list[dict] = []
    # --only-project=ID: ignora o grupo de teste e le so esse projeto (GET; ex.: um projeto
    # publico, para observar o formato quando o grupo de teste nao tem issues).
    only = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--only-project=")]
    if only:
        print(f"  MODO --only-project: {only}")
    for gid in [] if only else s.gitlab_group_ids:
        r = sp.get(f"/groups/{gid}/projects", include_subgroups="true", archived="false",
                   per_page=PAGE_SIZE, page=1)
        print(f"  GET /groups/{gid}/projects -> {r.status_code}")
        if r.status_code == 200:
            projects.extend(r.json())
    for pid in only or s.gitlab_project_ids:
        r = sp.get(f"/projects/{pid}")
        print(f"  GET /projects/{pid} -> {r.status_code}")
        if r.status_code == 200:
            projects.append(r.json())
    return projects[:25]


def run_confidential(sp: Spike, s: GitLabSpikeSettings) -> None:
    """FM-12 (complemento): issue confidencial vista pelo bot (rode com --confidential).

    So GET. Nao imprime titulo, descricao, nomes nem e-mails: so status, chaves e booleanos.
    """
    projects = _projects_for_issues(sp, s)
    print(f"  projetos: {len(projects)}")

    section("0. Papel do bot")
    r = sp.get("/user")
    bot_id = r.json().get("id") if r.status_code == 200 else None
    print(f"  GET /user -> {r.status_code} (id lido: {bot_id is not None})")
    for gid in s.gitlab_group_ids:
        r = sp.get(f"/groups/{gid}/members/all/{bot_id}") if bot_id else None
        if r is not None:
            lvl = r.json().get("access_level") if r.status_code == 200 else None
            print(f"  grupo {gid}: membro (herdado incluso) -> {r.status_code} access_level={lvl}")

    for p in projects:
        pid = p["id"]
        section(f"1. projeto {pid}")
        perms = p.get("permissions") or {}
        pa = (perms.get("project_access") or {}).get("access_level")
        ga = (perms.get("group_access") or {}).get("access_level")
        print(f"  permissions.project_access={pa} permissions.group_access={ga}; "
              f"visibility={p.get('visibility')} issues_enabled={p.get('issues_enabled')}")
        if bot_id:
            r = sp.get(f"/projects/{pid}/members/all/{bot_id}")
            lvl = r.json().get("access_level") if r.status_code == 200 else None
            print(f"  GET /projects/:id/members/all/<bot> -> {r.status_code} access_level={lvl}")

        r = sp.get(f"/projects/{pid}/issues", scope="all", state="all", per_page=PAGE_SIZE, page=1)
        print(f"  GET /issues scope=all state=all -> {r.status_code}")
        if r.status_code != 200:
            continue
        items = r.json()
        conf = [i for i in items if i.get("confidential")]
        print(f"  total na pagina: {len(items)}; confidential=true: {len(conf)}; "
              f"X-Total={r.headers.get('X-Total')}")
        r2 = sp.get(f"/projects/{pid}/issues", scope="all", state="all", confidential="true",
                    per_page=PAGE_SIZE)
        print(f"  filtro confidential=true -> {r2.status_code} n={len(r2.json()) if r2.status_code == 200 else '-'}")
        for i in conf[:3]:
            iid = i["iid"]
            print(f"  issue iid={iid}: state={i.get('state')} confidential={i.get('confidential')}")
            print(f"    campos={len(i)}; chaves ausentes vs. uma issue comum: "
                  f"{sorted(set(next((x for x in items if not x.get('confidential')), {})) - set(i))}")
            print(f"    title presente={bool(i.get('title'))}; description presente={bool(i.get('description'))}; "
                  f"author presente={isinstance(i.get('author'), dict)}; web_url presente={bool(i.get('web_url'))}; "
                  f"labels={len(i.get('labels') or [])}")
            r = sp.get(f"/projects/{pid}/issues/{iid}")
            ok = r.status_code == 200
            print(f"    GET /issues/{iid} -> {r.status_code}"
                  + (f" confidential={r.json().get('confidential')}; description presente="
                     f"{bool(r.json().get('description'))}" if ok else ""))
            r = sp.get(f"/projects/{pid}/issues/{iid}/closed_by")
            j = r.json() if r.status_code == 200 else None
            print(f"    GET /issues/{iid}/closed_by -> {r.status_code}"
                  + (f" n={len(j)}" if isinstance(j, list) else ""))
        if not conf:
            print("  nao observado: nenhuma issue confidencial visivel ao bot neste projeto.")


def run_issues(sp: Spike, s: GitLabSpikeSettings) -> None:
    """FM-12: issues e closed_by (rode com --issues). Nada de titulos, nomes ou e-mails."""
    projects = _projects_for_issues(sp, s)
    print(f"  projetos: {len(projects)}")
    ratelimit: dict[str, dict] = {}

    section("1. GET /projects/:id/issues?scope=all&state=all&per_page=100")
    by_proj: dict[int, list[dict]] = {}
    for p in projects:
        pid = p["id"]
        r = sp.get(f"/projects/{pid}/issues", scope="all", state="all", per_page=PAGE_SIZE, page=1)
        rl = ratelimit_headers(r)
        ratelimit.setdefault("issues", rl)
        print(f"  projeto {pid}: -> {r.status_code} issues_enabled={p.get('issues_enabled')} "
              f"issues_access_level={p.get('issues_access_level')}")
        print(f"    {pag_headers(r)}")
        if r.status_code != 200:
            print(f"    corpo: chaves={sorted(r.json()) if r.headers.get('content-type','').startswith('application/json') and isinstance(r.json(), dict) else '-'}")
            continue
        by_proj[pid] = r.json()
        print(f"    issues na pagina 1: {len(by_proj[pid])}")
    allissues = [i for v in by_proj.values() for i in v]
    print(f"\n  total de issues (pagina 1 de cada projeto): {len(allissues)}")
    if allissues:
        keys: dict[str, Counter] = {}
        for i in allissues:
            for k, v in i.items():
                keys.setdefault(k, Counter())[tname(v)] += 1
        print("  chaves -> tipos (contagem):")
        for k in sorted(keys):
            print(f"    {k}: {dict(keys[k])}")
        print(f"  state: {dict(Counter(i.get('state') for i in allissues))}")
        print(f"  issue_type: {dict(Counter(i.get('issue_type') for i in allissues))}")
        print(f"  type: {dict(Counter(i.get('type') for i in allissues))}")
        print(f"  confidential: {dict(Counter(i.get('confidential') for i in allissues))}")
        labs = [l for i in allissues for l in (i.get('labels') or [])]
        print(f"  labels: elemento tipo={dict(Counter(tname(l) for l in labs))}; "
              f"issues com >=1 label={sum(bool(i.get('labels')) for i in allissues)}")
        print(f"  assignees: tamanhos={dict(Counter(len(i.get('assignees') or []) for i in allissues))}; "
              f"'assignee' (singular) presente={sum('assignee' in i for i in allissues)}")
        a = next((i['author'] for i in allissues if isinstance(i.get('author'), dict)), {})
        print(f"  author chaves: {sorted(a)}; e-mail em algum author: "
              f"{any('email' in (i.get('author') or {}) for i in allissues)}")
        asg = [x for i in allissues for x in (i.get('assignees') or [])]
        print(f"  assignees chaves: {sorted(asg[0]) if asg else 'nenhum'}; e-mail em algum: "
              f"{any('email' in x for x in asg)}")
        print(f"  closed_at nao-nulo: {sum(bool(i.get('closed_at')) for i in allissues)}; "
              f"closed_by nao-nulo: {sum(bool(i.get('closed_by')) for i in allissues)}")
        cb = next((i['closed_by'] for i in allissues if isinstance(i.get('closed_by'), dict)), None)
        print(f"  closed_by (campo da issue) chaves: {sorted(cb) if cb else 'nenhum observado'}")
        by_state = Counter((i.get('state'), bool(i.get('closed_by'))) for i in allissues)
        print(f"  (state, closed_by preenchido): {dict(by_state)}")
        refs = next((i['references'] for i in allissues if isinstance(i.get('references'), dict)), {})
        print(f"  references chaves: {sorted(refs)}; formato short: "
              f"{'#<n>' if str(refs.get('short', '')).startswith('#') else 'outro'}; "
              f"relative tem '#': {'#' in str(refs.get('relative', ''))}; full tem '#': {'#' in str(refs.get('full', ''))}")
        print(f"  id != iid em {sum(i['id'] != i['iid'] for i in allissues)}/{len(allissues)}; "
              f"project_id bate com o projeto consultado em "
              f"{sum(i['project_id'] == pid for pid, v in by_proj.items() for i in v)}/{len(allissues)}")
        wu = next((i.get('web_url', '') for i in allissues), '')
        print(f"  web_url formato: mesma instancia={urlparse(wu).hostname == urlparse(sp.base).hostname}; "
              f"caminho contem '/-/issues/': {'/-/issues/' in wu}")
        for k in ("created_at", "updated_at", "closed_at"):
            v = next((i[k] for i in allissues if i.get(k)), None)
            print(f"  exemplo de formato {k}: {v}")
        print(f"  merge_requests_count presente: {sum('merge_requests_count' in i for i in allissues)}; "
              f"valores>0: {sum((i.get('merge_requests_count') or 0) > 0 for i in allissues)}")
    # paginacao: projeto com X-Next-Page
    section("1b. Paginacao")
    pag_done = False
    for pid, v in by_proj.items():
        if len(v) >= PAGE_SIZE:
            r = sp.get(f"/projects/{pid}/issues", scope="all", state="all", per_page=PAGE_SIZE, page=2)
            print(f"  projeto {pid} pagina 2 -> {r.status_code} {pag_headers(r)}")
            pag_done = True
            break
    if not pag_done:
        print("  nenhum projeto enche a pagina de 100: a ultima pagina observada e a 1a.")
    for pid, v in list(by_proj.items())[:1]:
        r = sp.get(f"/projects/{pid}/issues", scope="all", state="all", per_page=PAGE_SIZE, page=1)
        print(f"  ultima pagina (projeto {pid}): X-Next-Page vazio="
              f"{r.headers.get('X-Next-Page', '<ausente>') == ''}; X-Total presente="
              f"{'X-Total' in r.headers}; {pag_headers(r)}")
        r = sp.get(f"/projects/{pid}/issues", scope="all", state="all", per_page=PAGE_SIZE, page=1,
                   order_by="updated_at", sort="asc")
        print(f"  order_by=updated_at&sort=asc -> {r.status_code}")

    section("2. updated_after")
    best = max(by_proj, key=lambda k: len(by_proj[k]), default=None)
    if best is None or len(by_proj[best]) < 2:
        print("  nao observado: nenhum projeto com >=2 issues.")
    else:
        ups = sorted(i["updated_at"] for i in by_proj[best])
        print(f"  projeto {best}: {len(ups)} issues; updated_at min={ups[0]} max={ups[-1]}")
        def n(**kw: Any) -> str:
            r = sp.get(f"/projects/{best}/issues", scope="all", state="all", per_page=PAGE_SIZE, **kw)
            return f"{r.status_code} n={len(r.json()) if r.status_code == 200 else '-'} {pag_headers(r)}"
        mid = ups[len(ups) // 2]
        print(f"  sem filtro: {n()}")
        print(f"  updated_after={mid} (mediana): {n(updated_after=mid)}")
        print(f"  updated_after={ups[-1]} (ultimo updated_at): {n(updated_after=ups[-1])}")
        print(f"  updated_after=2099-01-01T00:00:00Z (futuro): {n(updated_after='2099-01-01T00:00:00Z')}")
        print(f"  updated_after=2000-01-01T00:00:00Z (passado): {n(updated_after='2000-01-01T00:00:00Z')}")
        print(f"  updated_before={mid}: {n(updated_before=mid)}")

    section("3. Confidenciais")
    conf = [i for i in allissues if i.get("confidential")]
    print(f"  issues com confidential=true visiveis ao bot: {len(conf)}/{len(allissues)}")
    if not conf:
        print("  nao observado: nenhuma issue confidencial visivel (ou inexistente).")
    r = sp.get(f"/projects/{projects[0]['id']}/issues", scope="all", state="all", confidential="true",
               per_page=PAGE_SIZE) if projects else None
    if r is not None:
        print(f"  filtro confidential=true (1o projeto) -> {r.status_code} n={len(r.json()) if r.status_code == 200 else '-'}")

    section("4. /projects/:id/issues/:iid/closed_by")
    seen: Counter = Counter()
    for pid, v in by_proj.items():
        samples: list[tuple[str, dict]] = []
        op = [i for i in v if i["state"] == "opened"][:2]
        manual = [i for i in v if i["state"] == "closed" and not (i.get("merge_requests_count") or 0)][:2]
        viamr = [i for i in v if i["state"] == "closed" and (i.get("merge_requests_count") or 0)][:3]
        anymr = [i for i in v if i["state"] == "opened" and (i.get("merge_requests_count") or 0)][:2]
        for tag, group in (("aberta", op), ("fechada sem MR relacionado", manual),
                           ("fechada com MR relacionado", viamr), ("aberta com MR relacionado", anymr)):
            for i in group:
                samples.append((tag, i))
        for tag, i in samples:
            if seen[tag] >= 3:
                continue
            seen[tag] += 1
            r = sp.get(f"/projects/{pid}/issues/{i['iid']}/closed_by")
            ratelimit.setdefault("closed_by", ratelimit_headers(r))
            line = f"  projeto {pid} iid {i['iid']} [{tag}] -> {r.status_code}"
            if r.status_code == 200:
                j = r.json()
                line += f" tipo={tname(j)} n={len(j) if isinstance(j, list) else '-'}"
                print(line)
                if isinstance(j, list) and j:
                    print(f"    MR campos: {sorted(j[0])}")
                    print(f"    MR state: {dict(Counter(m.get('state') for m in j))}; "
                          f"merged_at nao-nulo={sum(bool(m.get('merged_at')) for m in j)}; "
                          f"project_id do MR == do projeto: {all(m.get('project_id') == pid for m in j)}")
            else:
                print(line)
    if not seen:
        print("  nao observado: nenhuma issue amostrada.")
    print(f"  amostras por categoria: {dict(seen)}")
    # inexistente
    if best is not None:
        r = sp.get(f"/projects/{best}/issues/999999999/closed_by")
        print(f"  iid inexistente -> {r.status_code}")

    section("5. Issues desativadas / sem acesso")
    off = [p for p in projects if p.get("issues_enabled") is False]
    print(f"  projetos com issues_enabled=false: {len(off)}; "
          f"issues_access_level: {dict(Counter(p.get('issues_access_level') for p in projects))}")
    for p in off[:3]:
        r = sp.get(f"/projects/{p['id']}/issues", scope="all", state="all", per_page=PAGE_SIZE)
        print(f"  projeto {p['id']} (desativado) -> {r.status_code} corpo chaves="
              f"{sorted(r.json()) if r.status_code != 200 and isinstance(r.json(), dict) else '-'}")
    if not off:
        print("  nao observado: nenhum projeto com issues desativadas no grupo de teste.")
    r = sp.get("/projects/999999999/issues", scope="all", state="all")
    print(f"  projeto inexistente (999999999) -> {r.status_code}")
    r = sp.get("/projects", membership="false", visibility="private", per_page=1, simple="true")
    print(f"  (contexto) GET /projects?visibility=private -> {r.status_code}")

    section("6. Rate limit")
    for k, v in ratelimit.items():
        print(f"  {k}: {v or 'nenhum header RateLimit/Retry-After'}")
    r = sp.get(f"/projects/{projects[0]['id']}/merge_requests", per_page=1) if projects else None
    if r is not None:
        print(f"  merge_requests (comparacao): {ratelimit_headers(r) or 'nenhum'}")
        print(f"  iguais aos de issues: {ratelimit_headers(r).keys() == ratelimit.get('issues', {}).keys()}")


if __name__ == "__main__":
    sys.exit(main())
