"""Amostra canônica: usa o `GitLabConnector` com o token real e imprime os
repositórios e os primeiros merge requests e commits já no formato de `domain/`.

Uso (a partir da raiz do repositório):

    uv run --directory backend python scripts/gitlab_amostra_canonica.py
        [--max-repos N] [--max-itens N] [--max-lotes N] [--desde-dias N] [--sem-mascara]
        [--project-id ID]

Somente leitura: todas as requisições são GET (o transport deste script recusa
qualquer outro método e conta as requisições). O token e a URL vêm do ambiente
ou do `.env` da raiz, pelo `config.py`, e o token nunca é impresso.

Por padrão, títulos, nomes e usernames saem mascarados (tipo e tamanho). Só
`--sem-mascara` mostra os valores. E-mails **nunca** são impressos (só se
estão presentes). Ids, datas, estados, branches e os caminhos dos repositórios
aparecem sempre.

`--desde-dias N` pede só o que mudou nos últimos N dias (modo incremental).
Os MRs, issues e commits são buscados nos `--max-repos` primeiros repositórios.

`--project-id ID` também valida o mapper de issues num projeto avulso (por
exemplo um projeto público, como 1794617): lista issues, mapeia algumas e chama
`closed_by` de uma delas. Só mostra contagens e campos estruturais.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from scarlet_scribe.config import Settings
from scarlet_scribe.connectors.base import (
    AvatarUnavailable,
    ConnectorError,
    ConnectorResourceError,
    ListingReport,
)
from scarlet_scribe.connectors.factory import create_code_connector
from scarlet_scribe.domain.models import Commit, Issue, MergeRequest, Repository, RepositoryTag


class _ScriptSettings(Settings):
    # Este script não usa o banco: não exige DATABASE_URL.
    database_url: str | None = None


class _CountingTransport(httpx.AsyncBaseTransport):
    """Conta as requisições e recusa qualquer método que não seja GET."""

    def __init__(self) -> None:
        self._inner = httpx.AsyncHTTPTransport()
        self.total = 0
        self.by_status: Counter[int] = Counter()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            raise RuntimeError("este script só faz GET")
        self.total += 1
        response = await self._inner.handle_async_request(request)
        self.by_status[response.status_code] += 1
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


class Masker:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, value: str | None) -> str:
        if value is None:
            return "None"
        if not self.enabled:
            return repr(value)
        return f"<str len={len(value)}>" if value else "<str vazia>"


def fmt_dt(value: datetime | None) -> str:
    return value.isoformat() if value is not None else "None"


def presence(value: str | None) -> str:
    return "presente" if value else "ausente"


def print_report(title: str, report: ListingReport) -> None:
    stats = report.to_stats()
    print(f"  {title}: modo={stats['mode']} | completa={stats['complete']} | "
          f"autoriza exclusões={stats['allows_deletions']} | erros={stats['errors']} | "
          f"descartados={stats['discarded']}")
    for name, part in report.parts.items():
        print(f"    busca {name}: terminou={part.finished}  recebidos={part.received}")
    for issue in report.errors:
        print(f"    erro: {issue.resource} {issue.external_id or ''} status={issue.status_code} — {issue.reason}")
    for issue in report.discarded:
        print(f"    descartado: {issue.resource} {issue.external_id or '(sem id)'} — {issue.reason}")


def print_repository(repo: Repository) -> None:
    print(f"    {repo.external_id}  {repo.path_with_namespace}  default_branch={repo.default_branch!r}  "
          f"archived={repo.archived}  atividade={fmt_dt(repo.last_activity_at)}  "
          f"avatar_url={presence(repo.avatar_url)}  raw: {len(repo.raw)} chaves")


def print_merge_request(mr: MergeRequest, mask: Masker) -> None:
    print(f"    {mr.external_id}  iid={mr.iid}  repo={mr.external_repository_id}  state={mr.state.value}  "
          f"draft={mr.draft}  titulo={mask(mr.title)}")
    print(f"      {mr.source_branch!r} -> {mr.target_branch!r}  url={'presente' if mr.web_url else 'None'}  "
          f"raw: {len(mr.raw)} chaves")
    print(f"      criado={fmt_dt(mr.created_at_source)}  atualizado={fmt_dt(mr.source_updated_at)}  "
          f"merged={fmt_dt(mr.merged_at)}  closed={fmt_dt(mr.closed_at)}")
    if mr.author is not None:
        print(f"      autor {mr.author.external_id}  source={mr.author.source}  "
              f"username={mask(mr.author.username)}  email={presence(mr.author.email)}")
    else:
        print("      autor: None")


def print_issue(issue: Issue, mask: Masker) -> None:
    raw = issue.raw
    print(f"    {issue.external_id}  iid={issue.iid}  repo={issue.external_repository_id}  "
          f"state={issue.state.value}  confidencial={issue.confidential}  tipo={issue.issue_type!r}  "
          f"titulo={mask(issue.title)}")
    print(f"      url={'presente' if issue.web_url else 'None'}  raw: {len(raw)} chaves "
          f"(description={'description' in raw})  labels={len(raw.get('labels', []))}  "
          f"assignees={len(raw.get('assignees', []))}  closed_by={'presente' if raw.get('closed_by') else 'None'}")
    print(f"      criado={fmt_dt(issue.created_at_source)}  atualizado={fmt_dt(issue.source_updated_at)}  "
          f"closed={fmt_dt(issue.closed_at)}")
    if issue.author is not None:
        print(f"      autor {issue.author.external_id}  source={issue.author.source}  "
              f"username={mask(issue.author.username)}  email={presence(issue.author.email)}")
    else:
        print("      autor: None")


async def issues_section(
    connector: Any, repo_id: str, args: argparse.Namespace, mask: Masker, since: datetime | None,
    sink: list[Issue], *, closed_by_sample: bool = False,
) -> None:
    repo_issues: list[Issue] = []
    listing = connector.iter_issues(repo_id, updated_since=since)
    batches = 0
    async for batch in listing:
        batches += 1
        repo_issues.extend(batch)
        if batches >= args.max_lotes:
            print(f"(iteração de issues interrompida pelo script após {batches} lote(s): --max-lotes)")
            break
    sink.extend(repo_issues)
    ordered = [i.source_updated_at for i in repo_issues if i.source_updated_at is not None]
    print(f"[Issues] {len(repo_issues)} em {batches} lote(s); "
          f"estados: {dict(Counter(i.state.value for i in repo_issues))}; "
          f"confidenciais: {sum(i.confidential for i in repo_issues)}; "
          f"com autor: {sum(i.author is not None for i in repo_issues)}; "
          f"ids repetidos: {len(repo_issues) - len({i.external_id for i in repo_issues})}; "
          f"ordem asc por updated_at: {ordered == sorted(ordered)}")
    for issue in repo_issues[: args.max_itens]:
        print_issue(issue, mask)
    print_report("Issues", listing.report)
    if closed_by_sample and repo_issues:
        target = next((i for i in repo_issues if i.state.value == "closed"), repo_issues[0])
        mrs = await connector.fetch_issue_closed_by(repo_id, target.iid)
        print(f"  closed_by da issue {target.external_id} (iid={target.iid}, state={target.state.value}): "
              f"{len(mrs)} MR(s); estados: {dict(Counter(m.state.value for m in mrs))}")
        for mr in mrs[: args.max_itens]:
            print_merge_request(mr, mask)
        try:
            await connector.fetch_issue_closed_by(repo_id, 2_000_000_000)
            print("  closed_by de iid inexistente: SEM ERRO (inesperado)")
        except ConnectorResourceError as exc:
            print(f"  closed_by de iid inexistente: {type(exc).__name__} status={getattr(exc, 'status_code', None)}")


def print_commit(commit: Commit, mask: Masker) -> None:
    print(f"    {commit.external_id[:30]}…  short={commit.short_sha}  titulo={mask(commit.title)}")
    print(f"      autor={mask(commit.author_name)}  email={presence(commit.author_email)}  "
          f"authored={fmt_dt(commit.authored_at)}  committed={fmt_dt(commit.committed_at)}  "
          f"url={'presente' if commit.web_url else 'None'}  raw: {len(commit.raw)} chaves")


def raw_has_secret(records: list[Any], secret: str) -> bool:
    return secret in json.dumps([r.raw for r in records], ensure_ascii=False)


async def run(args: argparse.Namespace) -> int:
    settings = _ScriptSettings()
    if not settings.gitlab_enabled or settings.gitlab_api_token is None:
        print("Erro: GITLAB_URL, GITLAB_API_TOKEN e GITLAB_GROUP_IDS ou GITLAB_PROJECT_IDS "
              "precisam estar definidos.", file=sys.stderr)
        return 2
    mask = Masker(enabled=not args.sem_mascara)
    transport = _CountingTransport()
    since = datetime.now(UTC) - timedelta(days=args.desde_dias) if args.desde_dias else None
    print(f"Escopo: {len(settings.gitlab_group_ids)} grupo(s) e {len(settings.gitlab_project_ids)} "
          f"projeto(s) avulso(s); {'incremental desde ' + fmt_dt(since) if since else 'listagem completa'}; "
          f"títulos/nomes/usernames {'mascarados' if mask.enabled else 'SEM máscara'}; e-mails nunca impressos")

    repositories: list[Repository] = []
    mrs: list[MergeRequest] = []
    commits: list[Commit] = []
    issues: list[Issue] = []
    tags: list[RepositoryTag] = []
    try:
        async with create_code_connector(settings, transport=transport) as connector:
            print(f"Fonte: {connector.source}")

            snapshot = await connector.fetch_repositories()
            repositories = snapshot.repositories
            print(f"\n[Repositórios] {len(repositories)}  arquivados: {sum(r.archived for r in repositories)}  "
                  f"vazios (sem default_branch): {sum(r.default_branch is None for r in repositories)}  "
                  f"ids repetidos: {len(repositories) - len({r.external_id for r in repositories})}")
            for repo in repositories[: args.max_itens]:
                print_repository(repo)
            print_report("Repositórios", snapshot.report)

            with_avatar = [r for r in repositories if r.avatar_url]
            print(f"\n[Ícones] {len(with_avatar)} repositório(s) com avatar_url")
            for repo in with_avatar[: args.max_itens]:
                try:
                    avatar = await connector.fetch_avatar(repo)
                    print(f"    {repo.external_id}: content_type={avatar.content_type}  bytes={len(avatar.data)}")
                except AvatarUnavailable as exc:
                    print(f"    {repo.external_id}: indisponível ({exc.reason})")

            print("\n[Tags]")
            for repo in repositories:
                if repo.archived or repo.default_branch is None:
                    continue
                tag_listing = connector.iter_tags(repo.external_id)
                repo_tags: list[RepositoryTag] = []
                async for batch in tag_listing:
                    repo_tags.extend(batch)
                if repo_tags or tag_listing.report.errors or tag_listing.report.discarded:
                    print(f"  repo {repo.external_id}: {len(repo_tags)} tag(s)")
                    for tag in repo_tags[: args.max_itens]:
                        print(f"    {tag.external_id}  nome={mask(tag.name)}  sha={tag.commit_sha[:12]}…  "
                              f"raw: {sorted(tag.raw)}")
                    print_report("Tags", tag_listing.report)
                    tags.extend(repo_tags)

            for repo in repositories[: args.max_repos]:
                print(f"\n--- Repositório {repo.external_id} ({repo.path_with_namespace}) ---")

                repo_mrs: list[MergeRequest] = []
                mr_listing = connector.iter_merge_requests(repo.external_id, updated_since=since)
                batches = 0
                async for batch in mr_listing:
                    batches += 1
                    repo_mrs.extend(batch)
                    if batches >= args.max_lotes:
                        print(f"(iteração de MRs interrompida pelo script após {batches} lote(s): --max-lotes)")
                        break
                mrs.extend(repo_mrs)
                print(f"[Merge requests] {len(repo_mrs)} em {batches} lote(s); "
                      f"estados: {dict(Counter(m.state.value for m in repo_mrs))}; "
                      f"com autor: {sum(m.author is not None for m in repo_mrs)}; "
                      f"ids repetidos: {len(repo_mrs) - len({m.external_id for m in repo_mrs})}")
                for mr in repo_mrs[: args.max_itens]:
                    print_merge_request(mr, mask)
                print_report("MRs", mr_listing.report)

                await issues_section(connector, repo.external_id, args, mask, since, issues)

                repo_commits: list[Commit] = []
                commit_listing = connector.iter_commits(repo.external_id, since=since)
                batches = 0
                async for batch in commit_listing:
                    batches += 1
                    repo_commits.extend(batch)
                    if batches >= args.max_lotes:
                        print(f"(iteração de commits interrompida pelo script após {batches} lote(s): --max-lotes)")
                        break
                commits.extend(repo_commits)
                print(f"[Commits] {len(repo_commits)} em {batches} lote(s); "
                      f"shas repetidos: {len(repo_commits) - len({c.sha for c in repo_commits})}")
                for commit in repo_commits[: args.max_itens]:
                    print_commit(commit, mask)
                print_report("Commits", commit_listing.report)
            if args.project_id:
                print(f"\n--- Projeto avulso {args.project_id} (só issues) ---")
                await issues_section(connector, args.project_id, args, mask, since, issues,
                                     closed_by_sample=True)
    except ConnectorError as exc:
        print(f"Erro do conector: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        print(f"\nRequisições GET: {transport.total} (status: {dict(transport.by_status)})")

    secret = settings.gitlab_api_token.get_secret_value()
    people = [x.author for x in (*mrs, *issues) if x.author is not None]
    leaked = raw_has_secret([*repositories, *mrs, *issues, *commits, *tags, *people], secret)
    print(f"raw sem o token: {'FALHOU' if leaked else 'ok'}")
    return 1 if leaked else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-repos", type=int, default=2, help="em quantos repositórios buscar MRs e commits")
    parser.add_argument("--max-itens", type=int, default=5, help="quantos itens imprimir em detalhe")
    parser.add_argument("--max-lotes", type=int, default=3, help="teto de lotes (páginas) por listagem")
    parser.add_argument("--desde-dias", type=int, default=0, help="só o que mudou nos últimos N dias")
    parser.add_argument("--sem-mascara", action="store_true", help="mostra títulos, nomes e usernames")
    parser.add_argument("--project-id", default="", help="projeto avulso para validar issues e closed_by")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
