"""Modelos canônicos, independentes de ferramenta.

Os conectores convertem os dados de cada ferramenta para estes modelos, e o
sync grava a partir deles. As referências entre registros usam os ids da
origem (`external_*`), porque o conector não conhece os UUIDs internos do
banco. Todos os instantes são `datetime` com fuso (UTC); durações em ms.
"""

from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, Field, model_validator


class ContainerKind(StrEnum):
    """Nível de um container na árvore. A UI chama qualquer um de "projeto"."""

    SPACE = "space"
    FOLDER = "folder"
    LIST = "list"


class MergeRequestState(StrEnum):
    """Estados canônicos de um merge request; hoje iguais aos do GitLab."""

    OPENED = "opened"
    CLOSED = "closed"
    MERGED = "merged"
    LOCKED = "locked"


class SourceRecord(BaseModel):
    """Campos comuns a todo registro vindo de uma ferramenta."""

    source: str = Field(description="Ferramenta de origem, por exemplo 'clickup'")
    external_id: str = Field(description="Id do registro na origem")
    raw: dict[str, Any] = Field(
        default_factory=dict,
        description="Payload original. Só o mapper do conector interpreta este campo",
    )


class Workspace(SourceRecord):
    name: str


class Container(SourceRecord):
    """Nó da árvore space/folder/list.

    Os ids de container (`external_id`, `external_parent_id` aqui e
    `Task.external_container_id`) levam o nível como prefixo, por exemplo
    `space:123`, `folder:456` e `list:789`, porque a origem não garante ids
    distintos entre níveis. Quem monta o prefixo é o mapper do conector.
    """

    kind: ContainerKind
    name: str
    external_workspace_id: str
    external_parent_id: str | None = Field(
        default=None,
        description="Id do container pai, com o prefixo do nível (por exemplo 'folder:456'); "
        "nulo para o nível mais alto (space)",
    )


class Person(SourceRecord):
    username: str | None = None
    email: str | None = None


class Task(SourceRecord):
    name: str
    status: str | None = Field(default=None, description="Nome do status na origem")
    status_type: str | None = Field(
        default=None,
        description="Categoria do status: 'open', 'custom', 'done' ou 'closed'. "
        "'done' e 'closed' contam como tarefa encerrada",
    )
    priority: str | None = Field(
        default=None, description="Rótulo da prioridade (por exemplo 'urgent', 'high')"
    )
    start_date: AwareDatetime | None = None
    due_date: AwareDatetime | None = None
    done_at: AwareDatetime | None = None
    time_estimate_ms: int | None = None
    url: str | None = None
    is_milestone: bool = False
    archived: bool = Field(
        default=False,
        description="Tarefa arquivada na origem. A API lista as ativas e as arquivadas em "
        "separado (filtro `archived`)",
    )
    source_updated_at: AwareDatetime | None = Field(
        default=None, description="Última alteração na origem; base do watermark do sync"
    )
    external_container_id: str | None = Field(
        default=None,
        description="Id do container (list) da tarefa, com o prefixo do nível (por exemplo 'list:789')",
    )
    external_parent_id: str | None = Field(
        default=None, description="Id na origem da tarefa-pai, se for subtarefa"
    )
    assignees: list[Person] = Field(
        default_factory=list,
        description="Responsáveis, com os dados que vieram na própria tarefa",
    )


class Repository(SourceRecord):
    """Repositório de código (no GitLab, um projeto)."""

    name: str
    path_with_namespace: str
    web_url: str | None = None
    default_branch: str | None = Field(
        default=None, description="Nulo em repositório vazio"
    )
    archived: bool = False
    last_activity_at: AwareDatetime | None = None
    avatar_url: str | None = Field(
        default=None, description="URL do ícone na origem; nulo sem ícone"
    )


class MergeRequest(SourceRecord):
    """Merge request. `external_id` é o id global; `iid` é o número no repositório."""

    external_repository_id: str = Field(description="Id na origem do repositório")
    iid: int
    title: str
    state: MergeRequestState
    draft: bool = False
    source_branch: str | None = None
    target_branch: str | None = None
    web_url: str | None = None
    external_author_id: str | None = Field(
        default=None, description="Id na origem do autor (uma Person)"
    )
    author: Person | None = Field(
        default=None,
        description="Dados do autor que vieram no próprio MR, para o sync gravar em `people`",
    )
    created_at_source: AwareDatetime | None = None
    merged_at: AwareDatetime | None = None
    closed_at: AwareDatetime | None = None
    source_updated_at: AwareDatetime | None = Field(
        default=None, description="Última alteração na origem; base do watermark do sync"
    )

    @model_validator(mode="after")
    def _author_ids_agree(self) -> "MergeRequest":
        """Com `author`, `external_author_id` é o `external_id` dele (preenchido se vazio)."""
        if self.author is not None:
            if self.external_author_id is None:
                self.external_author_id = self.author.external_id
            elif self.external_author_id != self.author.external_id:
                raise ValueError("external_author_id diverge de author.external_id")
        return self


class Commit(SourceRecord):
    """Commit. `external_id` é '<id do repositório>:<sha>'.

    O autor é a identidade do git (nome e e-mail), sem vínculo com `Person`.
    """

    external_repository_id: str = Field(description="Id na origem do repositório")
    sha: str
    short_sha: str | None = None
    title: str
    author_name: str | None = None
    author_email: str | None = None
    authored_at: AwareDatetime | None = None
    committed_at: AwareDatetime | None = None
    web_url: str | None = None


class RepositoryTag(SourceRecord):
    """Tag de um repositório. `external_id` é '<id do repositório>:<nome>'.

    `commit_sha` é o commit apontado (`commit.id` na origem, não o `target` da
    tag anotada). Não há vínculo com `Commit`: o commit pode estar fora da
    janela do sync.
    """

    external_repository_id: str = Field(description="Id na origem do repositório")
    name: str
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")


class RepositoryAvatar(BaseModel):
    """Ícone de repositório já baixado pelo conector (bytes), para o sync gravar.

    Não é um `SourceRecord`: não tem `external_id` nem `raw`; pertence ao
    repositório e é guardado em `repository_avatars`. O conector já validou
    host, tipo e tamanho.
    """

    content_type: str
    data: bytes
    source_url: str = Field(description="URL de onde veio (o `avatar_url` do repositório)")


__all__ = [
    "Commit",
    "Container",
    "ContainerKind",
    "MergeRequest",
    "MergeRequestState",
    "Person",
    "Repository",
    "RepositoryAvatar",
    "RepositoryTag",
    "SourceRecord",
    "Task",
    "Workspace",
]
