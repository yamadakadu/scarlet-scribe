"""Cria o conector de uma fonte a partir das `Settings`.

É o ponto de entrada para o sync: quem está fora de `connectors/` usa
`create_connector` e o protocolo `Connector`, sem importar tipos de uma
ferramenta. `create_code_connector` faz o mesmo para as fontes de código (GitLab),
com o protocolo `CodeConnector`. O import de cada conector é feito aqui dentro,
sob demanda.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from scarlet_scribe.connectors.base import CodeConnector, Connector, ConnectorConfigError

if TYPE_CHECKING:
    from scarlet_scribe.config import Settings

DEFAULT_SOURCE = "clickup"
CODE_SOURCE = "gitlab"


def create_connector(settings: Settings, source: str = DEFAULT_SOURCE, **kwargs: Any) -> Connector:
    """Conector da fonte `source`, pronto para `async with`.

    Para o ClickUp, `kwargs` vai para `ClickUpConnector.from_settings`
    (por exemplo `space_ids=[]` para ignorar `CLICKUP_SPACE_IDS`).
    """
    if source == "clickup":
        from scarlet_scribe.connectors.clickup.connector import ClickUpConnector

        return ClickUpConnector.from_settings(settings, **kwargs)
    raise ConnectorConfigError(f"fonte de dados desconhecida: {source!r}")


def create_code_connector(
    settings: Settings, source: str = CODE_SOURCE, **kwargs: Any
) -> CodeConnector:
    """Conector de código (repositórios, merge requests e commits), pronto para `async with`.

    Levanta `ConnectorConfigError` se a fonte não estiver configurada
    (`settings.gitlab_enabled` falso). `kwargs` vai para
    `GitLabConnector.from_settings` (por exemplo `transport=...`).
    """
    if source == "gitlab":
        if not settings.gitlab_enabled:
            raise ConnectorConfigError(
                "GitLab não configurado: defina GITLAB_URL, GITLAB_API_TOKEN e "
                "GITLAB_GROUP_IDS ou GITLAB_PROJECT_IDS"
            )
        from scarlet_scribe.connectors.gitlab.connector import GitLabConnector

        return GitLabConnector.from_settings(settings, **kwargs)
    raise ConnectorConfigError(f"fonte de código desconhecida: {source!r}")


__all__ = ["CODE_SOURCE", "DEFAULT_SOURCE", "create_code_connector", "create_connector"]
