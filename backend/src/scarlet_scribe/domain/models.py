"""Modelos canônicos, independentes de ferramenta.

Os conectores convertem os dados de cada ferramenta para estes modelos, e o
sync grava a partir deles. As referências entre registros usam os ids da
origem (`external_*`), porque o conector não conhece os UUIDs internos do
banco. Todos os instantes são `datetime` com fuso (UTC); durações em ms.
"""

from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, Field


class ContainerKind(StrEnum):
    """Nível de um container na árvore. A UI chama qualquer um de "projeto"."""

    SPACE = "space"
    FOLDER = "folder"
    LIST = "list"


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


__all__ = [
    "Container",
    "ContainerKind",
    "Person",
    "SourceRecord",
    "Task",
    "Workspace",
]
