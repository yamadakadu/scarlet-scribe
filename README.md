# scarlet-scribe

Camada intermediária para integrar ferramentas corporativas. A primeira integração é o ClickUp: um usuário "bot" com permissão somente de leitura traz tarefas, datas e marcos para o nosso banco, e uma aplicação web mostra tudo num só lugar.

O projeto está na Fase 1. A infraestrutura já existe (pacote Python em `backend/`, Docker Compose, configuração e Alembic); o código da aplicação está sendo construído. O status de cada tarefa fica no `PLANO_DE_EXECUCAO.md`.

- `PROJECT.md`: a ideia original.
- `ARCHITECTURE.md`: decisões, fases, contrato da API, banco e sincronização.
- `PLANO_DE_EXECUCAO.md`: tarefas, agentes responsáveis, dependências e status.
- `CLAUDE.md`: regras para o Claude Code neste repositório, incluindo os comandos de desenvolvimento.
