"""Modelos Pydantic do JSON da API v4 do GitLab.

Uso restrito a `connectors/gitlab/`: o resto do sistema só conhece os modelos
canônicos de `domain/`, produzidos pelo mapper.

Diferente do ClickUp, os modelos aqui **ignoram** os campos que não usamos
(`extra="ignore"`): um projeto traz mais de 100 campos, e o `raw` guarda só o
que o mapper usa. Para a coluna `raw`, o mapper usa
`model_dump(mode="json", exclude_unset=True)`, que não inventa campos que não
vieram. As datas ficam como texto ISO 8601; a conversão para `datetime` UTC é
trabalho do mapper.
"""

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _optional_text(value: Any) -> Any:
    """Texto vazio vira `None` (por exemplo `public_email: ""`)."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


OptionalText = Annotated[str | None, BeforeValidator(_optional_text)]


class GitLabModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class GitLabUser(GitLabModel):
    """Autor, assignee ou reviewer. `public_email` quase sempre vem vazio."""

    id: int
    username: str | None = None
    public_email: OptionalText = None


class GitLabProject(GitLabModel):
    id: int
    name: str
    path_with_namespace: str
    web_url: str | None = None
    default_branch: str | None = None  # nulo em repositório vazio
    archived: bool = False
    last_activity_at: str | None = None


class GitLabMergeRequest(GitLabModel):
    id: int
    iid: int
    title: str
    state: str
    draft: bool = False
    # Nome antigo do `draft` (instâncias mais velhas).
    work_in_progress: bool = False
    source_branch: str | None = None
    target_branch: str | None = None
    web_url: str | None = None
    author: GitLabUser | None = None
    # Só no `raw`: ganham tabelas próprias quando for preciso filtrar por eles.
    assignees: list[GitLabUser] = Field(default_factory=list)
    reviewers: list[GitLabUser] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    merged_at: str | None = None
    closed_at: str | None = None


class GitLabCommit(GitLabModel):
    id: str  # sha completo
    short_id: str | None = None
    title: str
    author_name: str | None = None
    author_email: str | None = None
    authored_date: str | None = None
    committed_date: str | None = None
    web_url: str | None = None
