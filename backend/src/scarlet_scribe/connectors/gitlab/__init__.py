"""Conector do GitLab (API v4, somente GET), para gitlab.com ou self-hosted.

- `client.py`: cliente HTTP assíncrono (auth, rate limit, retries, paginação).
- `schemas.py`: modelos Pydantic do JSON do GitLab, usados só dentro deste pacote.
- `mapper.py`: funções puras GitLab → modelos canônicos de `domain/`.
- `connector.py`: `GitLabConnector`, que implementa `connectors.base.CodeConnector`.

Fora de `connectors/`, use `connectors.factory.create_code_connector` e o
protocolo `CodeConnector`; nenhum tipo deste pacote deve ser importado lá.
"""
