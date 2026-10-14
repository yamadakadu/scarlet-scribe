"""Cria o conector de uma fonte a partir das `Settings`.

É o ponto de entrada para o sync: quem está fora de `connectors/` usa
`create_connector` e o protocolo `Connector`, sem importar tipos de uma
ferramenta. O import de cada conector é feito aqui dentro, sob demanda.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from scarlet_scribe.connectors.base import Connector, ConnectorConfigError

if TYPE_CHECKING:
    from scarlet_scribe.config import Settings

DEFAULT_SOURCE = "clickup"


def create_connector(settings: Settings, source: str = DEFAULT_SOURCE, **kwargs: Any) -> Connector:
    """Conector da fonte `source`, pronto para `async with`.

    Para o ClickUp, `kwargs` vai para `ClickUpConnector.from_settings`
    (por exemplo `space_ids=[]` para ignorar `CLICKUP_SPACE_IDS`).
    """
    if source == "clickup":
        from scarlet_scribe.connectors.clickup.connector import ClickUpConnector

        return ClickUpConnector.from_settings(settings, **kwargs)
    raise ConnectorConfigError(f"fonte de dados desconhecida: {source!r}")


__all__ = ["DEFAULT_SOURCE", "create_connector"]
