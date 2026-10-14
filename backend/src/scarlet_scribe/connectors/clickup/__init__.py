"""Conector do ClickUp (API v2, somente GET).

- `client.py`: cliente HTTP assíncrono (auth, rate limit, retries, paginação).
- `schemas.py`: modelos Pydantic do JSON do ClickUp, usados só dentro deste pacote.
- `mapper.py`: funções puras ClickUp → modelos canônicos de `domain/`.
- `connector.py`: `ClickUpConnector`, que implementa `connectors.base.Connector`.

Fora de `connectors/`, use `connectors.factory.create_connector` e o protocolo
`Connector`; nenhum tipo deste pacote deve ser importado lá.
"""
