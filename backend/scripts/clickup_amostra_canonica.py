"""Amostra canônica: usa o `ClickUpConnector` com o token real e imprime a
estrutura e as primeiras tarefas já no formato de `domain/`.

Uso (a partir da raiz do repositório):

    uv run --directory backend python scripts/clickup_amostra_canonica.py [--todos-spaces]
        [--max-tarefas N] [--max-lotes N] [--sem-mascara]

Somente leitura: todas as requisições são GET (o transport deste script recusa
qualquer outro método e conta as requisições). O token vem do ambiente ou do
`.env` da raiz, pelo `config.py`, e nunca é impresso.

Por padrão, nomes, e-mails e usernames saem mascarados (tipo e tamanho). Só
`--sem-mascara` mostra os valores. Ids, datas, status, prioridade e a árvore
aparecem sempre.

`--todos-spaces` ignora `CLICKUP_SPACE_IDS` e percorre todos os spaces visíveis.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime
from typing import Any

import httpx

from scarlet_scribe.config import Settings
from scarlet_scribe.connectors.base import ConnectorError, ListingReport
from scarlet_scribe.connectors.factory import create_connector
from scarlet_scribe.domain.models import Container, Person, Task


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


def print_report(title: str, report: ListingReport) -> None:
    stats = report.to_stats()
    print(f"  {title}: modo={stats['mode']} | completa={stats['complete']} | "
          f"autoriza exclusões={stats['allows_deletions']} | erros={stats['errors']} | "
          f"descartados={stats['discarded']}")
    for name, part in report.parts.items():
        print(f"    busca {name}: terminou={part.finished}  recebidas={part.received}")
    for issue in report.errors:
        print(f"    erro: {issue.resource} {issue.external_id or ''} status={issue.status_code} — {issue.reason}")
    for issue in report.discarded:
        print(f"    descartado: {issue.resource} {issue.external_id or '(sem id)'} — {issue.reason}")


def print_tree(containers: list[Container], mask: Masker) -> None:
    children: dict[str | None, list[Container]] = {}
    known = {c.external_id for c in containers}
    for c in containers:
        parent = c.external_parent_id if c.external_parent_id in known else None
        children.setdefault(parent, []).append(c)

    def walk(parent: str | None, depth: int) -> None:
        for c in children.get(parent, []):
            orphan = " (pai fora da amostra)" if depth == 0 and c.external_parent_id else ""
            print(f"    {'  ' * depth}{c.external_id}  kind={c.kind.value}  pai={c.external_parent_id}  "
                  f"nome={mask(c.name)}  raw: {len(c.raw)} chaves{orphan}")
            walk(c.external_id, depth + 1)

    walk(None, 0)


def print_task(task: Task, mask: Masker) -> None:
    print(f"    {task.external_id}  nome={mask(task.name)}")
    print(f"      container={task.external_container_id}  pai={task.external_parent_id}  "
          f"is_milestone={task.is_milestone}  archived={task.archived}")
    print(f"      status={task.status!r}  status_type={task.status_type!r}  priority={task.priority!r}")
    print(f"      start={fmt_dt(task.start_date)}  due={fmt_dt(task.due_date)}  done={fmt_dt(task.done_at)}  "
          f"atualizada={fmt_dt(task.source_updated_at)}")
    print(f"      estimativa_ms={task.time_estimate_ms}  url={'presente' if task.url else 'None'}  "
          f"raw: {len(task.raw)} chaves")
    for p in task.assignees:
        print(f"      assignee {p.external_id}  username={mask(p.username)}  email={mask(p.email)}")


def raw_has_secret(records: list[Any], secret: str) -> bool:
    return secret in json.dumps([r.raw for r in records], ensure_ascii=False)


async def run(args: argparse.Namespace) -> int:
    settings = _ScriptSettings()
    if settings.clickup_api_token is None or not settings.clickup_team_id:
        print("Erro: CLICKUP_API_TOKEN e CLICKUP_TEAM_ID precisam estar definidos.", file=sys.stderr)
        return 2
    mask = Masker(enabled=not args.sem_mascara)
    transport = _CountingTransport()
    space_ids: list[str] | None = [] if args.todos_spaces else None
    escopo = "todos os spaces visíveis" if args.todos_spaces or not settings.clickup_space_ids else (
        f"{len(settings.clickup_space_ids)} space(s) de CLICKUP_SPACE_IDS"
    )
    print(f"Escopo: {escopo}; nomes/e-mails/usernames {'mascarados' if mask.enabled else 'SEM máscara'}")

    tasks: list[Task] = []
    people: list[Person] = []
    containers: list[Container] = []
    try:
        async with create_connector(settings, space_ids=space_ids, transport=transport) as connector:
            print(f"Fonte: {connector.source}")

            structure = await connector.fetch_structure()
            people, containers = structure.people, structure.containers
            ws = structure.workspace
            print(f"\n[Workspace] {ws.external_id}  nome={mask(ws.name)}")
            print(f"\n[Pessoas] {len(people)}")
            for p in people[:10]:
                print(f"    {p.external_id}  username={mask(p.username)}  email={mask(p.email)}")
            kinds = Counter(c.kind.value for c in containers)
            print(f"\n[Containers] {len(containers)} ({', '.join(f'{k}: {v}' for k, v in sorted(kinds.items()))})")
            print_tree(containers, mask)
            print_report("Estrutura", structure.report)

            listing = connector.iter_tasks()
            batches = 0
            async for batch in listing:
                batches += 1
                tasks.extend(batch)
                if batches >= args.max_lotes:
                    print(f"\n(iteração interrompida pelo script após {batches} lote(s): --max-lotes)")
                    break
            print(f"\n[Tarefas] {len(tasks)} em {batches} lote(s); arquivadas: {sum(t.archived for t in tasks)}; "
                  f"marcos: {sum(t.is_milestone for t in tasks)}; "
                  f"subtarefas: {sum(t.external_parent_id is not None for t in tasks)}; "
                  f"ids repetidos: {len(tasks) - len({t.external_id for t in tasks})}")
            print(f"  status_type: {dict(Counter(t.status_type for t in tasks))}")
            print(f"  containers das tarefas na estrutura: "
                  f"{sum(t.external_container_id in {c.external_id for c in containers} for t in tasks)}/{len(tasks)}")
            for task in tasks[: args.max_tarefas]:
                print_task(task, mask)
            print_report("Tarefas", listing.report)
            counters = {
                k: v for k, v in listing.report.to_stats().items() if not k.endswith("_details") and k != "parts"
            }
            print(f"  stats para o sync: {counters}")
    except ConnectorError as exc:
        print(f"Erro do conector: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        print(f"\nRequisições GET: {transport.total} (status: {dict(transport.by_status)})")

    secret = settings.clickup_api_token.get_secret_value()
    leaked = raw_has_secret([*people, *containers, *tasks], secret)
    print(f"raw sem o token: {'FALHOU' if leaked else 'ok'}")
    return 1 if leaked else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--todos-spaces", action="store_true", help="ignora CLICKUP_SPACE_IDS")
    parser.add_argument("--max-tarefas", type=int, default=8, help="quantas tarefas imprimir em detalhe")
    parser.add_argument("--max-lotes", type=int, default=5, help="teto de lotes (páginas) de tarefas")
    parser.add_argument("--sem-mascara", action="store_true", help="mostra nomes, e-mails e usernames")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
