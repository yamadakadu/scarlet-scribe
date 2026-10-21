"""Funções puras GitLab → modelos canônicos de `domain/`.

Regras (ver `ARCHITECTURE.md` › "Fase M: multi-integração" › "Banco"):

- Datas ISO 8601 (com `Z` ou deslocamento, com ou sem milissegundos) viram
  `datetime` UTC; `None` e vazio viram `None`. Uma data sem fuso é tratada como
  UTC (o GitLab sempre manda o fuso). Um valor que não converte levanta
  `MappingError` (o conector descarta só aquele registro).
- `Repository.external_id` = id do projeto; `MergeRequest.external_id` = `id`
  global do MR (o `iid` é o número dentro do repositório);
  `Commit.external_id` = `<id do projeto>:<sha>`, porque o mesmo sha pode existir
  em projetos diferentes (forks).
- O autor do MR vira uma `Person` (`source='gitlab'`, `external_id` = id do
  usuário, `username`, `email` = `public_email` só se vier preenchido). O
  autor do commit é a identidade do git (nome e e-mail), sem `Person`.
- `RepositoryTag.external_id` = `<id do projeto>:<nome>`; `commit_sha` = `commit.id`
  (nunca o `target`, que nas tags anotadas é o objeto tag). Tag sem `commit.id`
  levanta `MappingError`; um sha fora de 40/64 hex minúsculos falha na validação
  do modelo (`ValidationError`). O `raw` da tag guarda `name`, `target`,
  `commit.id`, `created_at`, `protected` e `message` truncada a 200 caracteres.
- `Repository.avatar_url` = `avatar_url` do projeto (nulo sem ícone).
- `raw` = `model_dump(mode="json", exclude_unset=True)` do schema, que só tem os
  campos usados. Assignees e reviewers dos MRs ficam só aqui.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from scarlet_scribe.connectors.gitlab.schemas import (
    GitLabCommit,
    GitLabIssue,
    GitLabMergeRequest,
    GitLabModel,
    GitLabProject,
    GitLabTag,
    GitLabUser,
)
from scarlet_scribe.domain.models import (
    Commit,
    Issue,
    IssueState,
    MergeRequest,
    MergeRequestState,
    Person,
    Repository,
    RepositoryTag,
)

SOURCE = "gitlab"

_SHORT_SHA_LENGTH = 8
# `message` das tags anotadas pode ser longa: no `raw` fica truncada.
_TAG_MESSAGE_RAW_LIMIT = 200


class MappingError(ValueError):
    """Um campo não pôde ser convertido. A mensagem traz o campo, nunca o valor."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason


# --- Conversões básicas ------------------------------------------------------


def parse_datetime(value: str | None, *, field: str = "data") -> datetime | None:
    """ISO 8601 → `datetime` UTC. `None` e texto vazio viram `None`."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise MappingError(field, "não é uma data ISO 8601") from None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    try:
        return parsed.astimezone(UTC)
    except (OverflowError, ValueError):
        raise MappingError(field, "fora do intervalo de datas") from None


def format_instant(value: datetime) -> str:
    """`datetime` com fuso → texto ISO 8601 em UTC com `Z` (para `updated_after` e `since`)."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("o datetime precisa ter fuso (UTC)")
    utc = value.astimezone(UTC)
    return utc.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def repository_ref(project_id: int | str) -> str:
    return str(project_id)


def commit_ref(project_id: int | str, sha: str) -> str:
    """`external_id` canônico de um commit: `<id do projeto>:<sha>`."""
    return f"{project_id}:{sha}"


def raw_payload(model: GitLabModel) -> dict[str, Any]:
    """`raw` de um registro: só os campos do schema que vieram no JSON."""
    return model.model_dump(mode="json", exclude_unset=True)


# --- Registros ----------------------------------------------------------------


def map_repository(project: GitLabProject) -> Repository:
    return Repository(
        source=SOURCE,
        external_id=repository_ref(project.id),
        name=project.name,
        path_with_namespace=project.path_with_namespace,
        web_url=project.web_url,
        default_branch=project.default_branch,
        archived=project.archived,
        last_activity_at=parse_datetime(project.last_activity_at, field="last_activity_at"),
        avatar_url=project.avatar_url,
        raw=raw_payload(project),
    )


def map_person(user: GitLabUser) -> Person:
    """Pessoa a partir do autor de um MR. O e-mail só entra se o usuário o tornou público."""
    return Person(
        source=SOURCE,
        external_id=str(user.id),
        username=user.username,
        email=user.public_email,
        raw=raw_payload(user),
    )


def map_merge_request(mr: GitLabMergeRequest, *, project_id: int | str) -> MergeRequest:
    try:
        state = MergeRequestState(mr.state)
    except ValueError:
        raise MappingError("state", "estado desconhecido") from None
    author = map_person(mr.author) if mr.author is not None else None
    return MergeRequest(
        source=SOURCE,
        external_id=str(mr.id),
        external_repository_id=repository_ref(project_id),
        iid=mr.iid,
        title=mr.title,
        state=state,
        draft=mr.draft or mr.work_in_progress,
        source_branch=mr.source_branch,
        target_branch=mr.target_branch,
        web_url=mr.web_url,
        external_author_id=author.external_id if author is not None else None,
        author=author,
        created_at_source=parse_datetime(mr.created_at, field="created_at"),
        merged_at=parse_datetime(mr.merged_at, field="merged_at"),
        closed_at=parse_datetime(mr.closed_at, field="closed_at"),
        source_updated_at=parse_datetime(mr.updated_at, field="updated_at"),
        raw=raw_payload(mr),
    )


def map_issue(issue: GitLabIssue, *, project_id: int | str) -> Issue:
    """Issue canônica. `raw` sem `description`; labels, assignees e `closed_by` ficam nele."""
    try:
        state = IssueState(issue.state)
    except ValueError:
        raise MappingError("state", "estado desconhecido") from None
    author = map_person(issue.author) if issue.author is not None else None
    return Issue(
        source=SOURCE,
        external_id=str(issue.id),
        external_repository_id=repository_ref(project_id),
        iid=issue.iid,
        title=issue.title,
        state=state,
        confidential=issue.confidential,
        issue_type=issue.issue_type,
        web_url=issue.web_url,
        external_author_id=author.external_id if author is not None else None,
        author=author,
        created_at_source=parse_datetime(issue.created_at, field="created_at"),
        closed_at=parse_datetime(issue.closed_at, field="closed_at"),
        source_updated_at=parse_datetime(issue.updated_at, field="updated_at"),
        raw=raw_payload(issue),
    )


def map_commit(commit: GitLabCommit, *, project_id: int | str) -> Commit:
    sha = commit.id.strip()
    if not sha:
        raise MappingError("id", "sha vazio")
    return Commit(
        source=SOURCE,
        external_id=commit_ref(project_id, sha),
        external_repository_id=repository_ref(project_id),
        sha=sha,
        short_sha=commit.short_id or sha[:_SHORT_SHA_LENGTH],
        title=commit.title,
        author_name=commit.author_name,
        author_email=commit.author_email,
        authored_at=parse_datetime(commit.authored_date, field="authored_date"),
        committed_at=parse_datetime(commit.committed_date, field="committed_date"),
        web_url=commit.web_url,
        raw=raw_payload(commit),
    )


def tag_ref(project_id: int | str, name: str) -> str:
    """`external_id` canônico de uma tag: `<id do projeto>:<nome>`."""
    return f"{project_id}:{name}"


def map_tag(tag: GitLabTag, *, project_id: int | str) -> RepositoryTag:
    if not tag.name.strip():
        raise MappingError("name", "nome vazio")
    if tag.commit is None or not tag.commit.id.strip():
        raise MappingError("commit.id", "ausente")
    raw = raw_payload(tag)
    message = raw.get("message")
    if isinstance(message, str) and len(message) > _TAG_MESSAGE_RAW_LIMIT:
        raw["message"] = message[:_TAG_MESSAGE_RAW_LIMIT]
    return RepositoryTag(
        source=SOURCE,
        external_id=tag_ref(project_id, tag.name),
        external_repository_id=repository_ref(project_id),
        name=tag.name,
        commit_sha=tag.commit.id.strip(),
        raw=raw,
    )
