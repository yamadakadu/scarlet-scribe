# Plano de execução — scarlet-scribe

Este plano diz o que será executado, por quem e em que ordem, para que o orquestrador acompanhe o andamento. O desenho técnico de cada item está em `ARCHITECTURE.md`; este documento não o repete.

**Status:** Fase 1 em andamento (falta a F1-11). A Fase M (multi-integração: barra lateral de apps e GitLab) foi planejada em 2026-10-15 e começa junto com a F1-11. A arquitetura foi revisada com o Carlos; o andamento de cada tarefa está em "Acompanhamento".

## Agentes

| Agente | Papel | Área de atuação (arquivos que pode alterar) |
|---|---|---|
| **Maestro** | Orquestrador, que é a sessão principal. Distribui tarefas, acompanha dependências, integra as entregas e mantém `ARCHITECTURE.md`, `CLAUDE.md` e este plano atualizados. É o único que conversa com o Carlos | Documentação na raiz e integração das branches |
| **Alicerce** | Infraestrutura e estrutura do repositório | `backend/pyproject.toml`, `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/README`, `backend/alembic/versions/.gitkeep` (a pasta e as migrations são do Arquivista), `docker-compose.yml`, `.env.example`, Dockerfiles, `backend/src/scarlet_scribe/config.py`. O `.gitignore` é do Maestro: mudanças nele são pedidas ao Maestro |
| **Batedor** | Spike: valida o comportamento real da API do ClickUp com o token do bot. Não escreve código de produção | Só `backend/scripts/clickup_spike.py` (os demais scripts de `backend/scripts/` são do Conector) e o relatório que entrega ao Maestro |
| **Conector** | Integração com o ClickUp: cliente HTTP, schemas, mapper e conector | `backend/src/scarlet_scribe/connectors/` |
| **Arquivista** | Modelo canônico, tabelas e migrations | `backend/src/scarlet_scribe/domain/`, `backend/src/scarlet_scribe/db/`, `backend/alembic/versions/` e `backend/alembic/env.py` (compartilhado com o Alicerce, para ligar o `Base.metadata` às migrations) |
| **Sincronista** | Serviço de sincronização e worker | `backend/src/scarlet_scribe/sync/` |
| **Portal** | API HTTP (FastAPI) | `backend/src/scarlet_scribe/api/` |
| **Vitrine** | Frontend (Vite + React + TS) | `frontend/` |
| **Revisor** | Revisa cada entrega antes da integração. Só lê, não altera código | — |
| **Carlos** (humano) | Fornece credenciais, toma as decisões de produto e aprova as fases | — |

Fase 2: **Guardião** (login LDAP e sessões) e **Ponte** (OAuth e conexão com o ClickUp).

## Regras de operação

1. **Fronteiras de arquivos:** cada agente só altera a própria área. Se precisar de algo de outra área (por exemplo, o Portal precisar de um campo novo numa tabela), pede ao Maestro, que repassa ao dono da área.
2. **Branches e commits:**
   - Cada agente trabalha num git worktree próprio, na branch **`<agente>/<feature>`**, por exemplo `conector/cliente-http` ou `arquivista/modelos-fase1`.
   - Antes de acionar o agente, o Maestro cria o worktree com `python3 .claude/scripts/novo_worktree.py <agente> <feature>`. O worktree fica em `.claude/worktrees/<agente>-<feature>`, sai da `main` e recebe um symlink `.env` para o `.env` da raiz principal, que não existe nos worktrees por estar fora do git. O agente trabalha nele com caminhos absolutos e `git -C <worktree>`: um subagente disparado da raiz não consegue trocar de diretório com `EnterWorktree`.
   - O worktree parte do último commit da `main`: mudanças ainda não commitadas na `main` não aparecem nele.
   - O assunto de cada commit começa com o nome da branch: `conector/cliente-http: adiciona retries com backoff`.
   - Os agentes fazem commits livremente na própria branch.
   - Commits e merges na `main` e qualquer push pedem a confirmação do Carlos.
   - O Maestro integra na `main` depois da revisão.
3. **Entrega:** ao terminar, o agente informa ao Maestro:
   - os arquivos alterados;
   - os comandos de verificação que rodou e o resultado deles;
   - as divergências em relação ao `ARCHITECTURE.md`.

   O agente **não edita** o `ARCHITECTURE.md`. Divergências passam pelo Maestro, que decide com o Carlos quando necessário.
4. **Revisão:** toda entrega passa pelo Revisor antes de ser integrada. Bloqueiam a integração:
   - violar as regras do `CLAUDE.md`, por exemplo escrever no ClickUp, deixar tipos do ClickUp fora de `connectors/` ou expor tokens;
   - um critério de pronto não atendido.
5. **Sem testes automatizados**, por decisão do Carlos, até existir o MVP. Os critérios de pronto são verificações manuais com comandos reproduzíveis.
6. **Fase 1 não antecipa a Fase 2:** nada de login, sessões, OAuth ou horas.
7. **Segredos:** o token do bot fica apenas no `.env` local, nunca em commits, logs ou relatórios.

## Modelos e esforço dos agentes

Decisão do Carlos (2026-10-14), para reduzir o consumo de tokens. O padrão de cada agente fica no cabeçalho do arquivo em `.claude/agents/` (`model` e `effort`). Os modelos usam o ID completo, que fixa a versão; os apelidos (`opus`, `sonnet`) mudariam de versão sozinhos.

| Agente | Modelo padrão | Esforço padrão | Variação por tarefa (o Maestro passa no disparo) |
|---|---|---|---|
| Revisor | `claude-opus-5-5` | `high` | `medium` para re-revisão de uma correção pequena |
| Sincronista | `claude-opus-5-5` | `high` | `medium` para ajustes depois da F1-07 |
| Conector | `claude-sonnet-5-5` | `medium` | `high` para lógica nova de paginação ou reconciliação |
| Portal | `claude-sonnet-5-5` | `medium` | `high` para mudança de contrato com regras novas |
| Arquivista | `claude-sonnet-5-5` | `medium` | `high` para migration que transforma dados existentes |
| Vitrine | `claude-sonnet-5-5` | `medium` | — |
| Batedor | `claude-sonnet-5-5` | `medium` | — |
| Alicerce | `claude-sonnet-5-5` | `medium` | `low` para ajuste de uma ou duas linhas |
| Qualquer agente, tarefa mecânica (1 a 2 linhas, sem lógica nova) | `claude-haiku-5-5` no disparo | `low` | — |

Regras:
- O Maestro aplica a coluna "Variação por tarefa" passando `model` e `effort` no disparo. Fora desses casos, vale o padrão do cabeçalho.
- Se um agente em Sonnet tiver bloqueios em duas revisões seguidas, o Maestro passa a dispará-lo com `claude-opus-5-5` e avisa o Carlos.
- Economias que não dependem do modelo:
  - **prompts curtos:** o disparo traz a tarefa, as portas, as restrições específicas e o critério de pronto, sem repetir regras que já estão no `CLAUDE.md` ou no `ARCHITECTURE.md`;
  - **leitura dirigida:** o agente lê só as seções do `ARCHITECTURE.md` indicadas no disparo;
  - **revisão proporcional:** uma mudança pequena e mecânica é conferida pelo Maestro no diff; a re-revisão de uma correção vai para o mesmo Revisor, que já tem o contexto; o Revisor completo fica para as entregas de tarefa;
  - **verificação enxuta:** os testes inline cobrem o critério de pronto e os casos de risco apontados, não dezenas de cenários;
  - **tarefas pequenas juntas:** ajustes pequenos da mesma área vão num único disparo.

## Hooks (imposição automática das regras)

As regras acima são impostas por hooks. A política está em `.claude/hooks/policy.json`: áreas de cada agente, fase atual, caminhos e tabelas da Fase 2. Só o Maestro altera esse arquivo.

| Camada | Arquivo | O que verifica |
|---|---|---|
| Claude Code (`PreToolUse`) | `.claude/hooks/guard_edits.py` | Edição fora da área do agente (identificado pela branch), peças da Fase 2 durante a Fase 1, arquivos de teste, chamadas de escrita em qualquer conector (ClickUp e GitLab), segredos no conteúdo (inclusive tokens `pk_` do ClickUp e `glpat-` do GitLab) e arquivos internos do `.git` |
| Claude Code (`PreToolUse`) | `.claude/hooks/guard_reads.py` | Leitura de `.env` e de chaves |
| Claude Code (`PreToolUse`) | `.claude/hooks/guard_bash.py` | **Bloqueia:** ler `.env` ou exibir variáveis de ambiente; `--no-verify` e mudanças em `core.hooksPath`; comandos git destrutivos; commit em branch fora do padrão; dependências de teste; escrita na API do ClickUp e na do GitLab (um cliente HTTP, como `curl` ou `glab`, com o caminho `/api/v4/` ou a palavra `gitlab` e um método ou corpo de escrita; o host do GitLab varia entre o gitlab.com e o self-hosted). **Pede confirmação:** push, commit ou merge na `main` e remoções recursivas. O texto literal das mensagens de commit (`-m` ou heredoc com `-F -`) não é verificado; mensagens com `$(...)`, crase ou `$VAR` continuam sendo |
| Claude Code (`SubagentStop`) | `.claude/hooks/log_subagent.py` | Registra o fim de cada subagente em `.claude/logs/agents.log` (fora do git) |
| git (`pre-commit`) | `.githooks/pre-commit` | Branch `<agente>/<feature>`, arquivos só da área do agente, arquivos proibidos (segredos, artefatos, arquivos locais, acima de 1 MB), segredos nas linhas adicionadas e as regras de fase, testes e ClickUp |
| git (`commit-msg`) | `.githooks/commit-msg` | Assunto começando com `<agente>/<feature>: ` |

**Se o pre-commit bloquear:**
1. Ninguém contorna o bloqueio: nada de `--no-verify`, nada de mudar `core.hooksPath`, nada de renomear o arquivo.
2. O agente tira o arquivo do commit e relata ao Maestro.
3. O Maestro consulta o Carlos.
4. Exceções de segredo legítimas, como falsos positivos, só entram em `.githooks/secrets-allowlist.txt` com a aprovação do Carlos.

**Manutenção:** depois de mudar a política ou um hook, o Maestro roda `python3 .claude/hooks/selfcheck.py`, que confere os casos de `selfcheck_cases.json`.

**Limitações conhecidas:**
- Comandos Bash que escrevem arquivos (`>`, `sed -i`, `cp`, `mv`) não passam pela verificação de área na hora. O pre-commit pega o problema no commit.
- O CI/CD com as mesmas verificações fica para depois.

## Fase 1: estrutura inicial

| ID | Tarefa | Agente | Depende de | Onda | Entregável e critério de pronto |
|---|---|---|---|---|---|
| F1-01 | Reorganizar em monorepo: mover o pacote uv para `backend/`; adicionar as dependências da Fase 1 (fastapi, uvicorn, httpx, pydantic-settings, sqlalchemy[asyncio], asyncpg, alembic, apscheduler); criar `config.py` com as variáveis da Fase 1 (o `.env` fica na raiz do repositório, então o `config.py` precisa achá-lo também quando o comando roda em `backend/`, o que foi resolvido com um caminho calculado a partir do próprio `config.py`), `.env.example`, `docker-compose.yml` (postgres, api, worker) e a inicialização do Alembic (com `backend/alembic/versions/.gitkeep`); registrar os entry points; trocar a `description` padrão do `pyproject.toml` | Alicerce | — | 0 | `docker compose up -d postgres` sobe saudável; `uv run --directory backend python -c "import scarlet_scribe"` funciona; `uv run --directory backend alembic upgrade head` roda sem erro |
| F1-02 | Fornecer no `.env` local o token do bot (`CLICKUP_API_TOKEN`) e o `CLICKUP_TEAM_ID`. Confirmar o papel do bot no workspace e, se possível, o plano do ClickUp | Carlos | — | 0 | `.env` preenchido (fora do git). O Maestro confirma que as variáveis existem, sem ler os valores |
| F1-03 | Cliente HTTP do ClickUp (`client.py`): só GET; o esquema de auth como parâmetro; limite preventivo de requisições; retries e backoff (429, 5xx, timeout); paginação de tarefas parando na página com menos de 100 itens. Schemas Pydantic para user, team, space, folder, list e task | Conector | F1-01 | 1 | O módulo importa sem erro. O cliente não tem nenhum método de escrita. Um script de exemplo lista os workspaces com o token do `.env` (roda depois de F1-02) |
| F1-04 | Spike: com o cliente de F1-03, responder aos itens "a confirmar": se tarefas arquivadas aparecem no endpoint de tarefas; se marcos vêm sem `custom_items[]`; se os headers `X-RateLimit-*` vêm em respostas 200 e a unidade do `Reset`; qual é o plano do workspace; se o bot enxerga todos os spaces esperados | Batedor | F1-02, F1-03 | 2 | Relatório entregue ao Maestro com uma resposta por item, mostrando a evidência (status HTTP, campos observados), sem dados sensíveis. O Maestro atualiza o `ARCHITECTURE.md` |
| F1-05 | Modelos canônicos em `domain/` (Workspace, Container, Person, Task) e tabelas da Fase 1 (`workspaces`, `containers`, `people`, `tasks`, `task_assignees`, `sync_runs`, `sync_state`), seguindo as convenções `source`/`external_id`/`raw`/`synced_at`/`deleted_at`, mais a primeira migration. Inclui `external_container_id` e `external_parent_id` em `tasks` (com `container_id` e `parent_id` aceitando nulo) e o índice único parcial de `sync_runs` | Arquivista | F1-01 | 1 | `alembic upgrade head` cria as tabelas, e `\d` no psql mostra os índices e constraints únicos previstos; `alembic downgrade base` volta ao estado limpo |
| F1-06 | Mapper ClickUp → domain (datas em ms para UTC; árvore de folders via `parent_folder`; `is_milestone` a partir de `custom_item_id == 1`), o protocolo `Connector` em `base.py` e o `connector.py` do ClickUp | Conector | F1-03, F1-04, F1-05 | 3 | Um script imprime as primeiras tarefas e os containers já no formato canônico. Nenhum tipo do ClickUp aparece fora de `connectors/clickup/` |
| F1-07 | `SyncService` com os passos 1 a 3 (estrutura, tarefas incrementais e reconciliação completa), upsert por `(source, external_id)`, `sync_state` e contadores em `stats`. Worker com APScheduler, consumo da fila `sync_runs` (`FOR UPDATE SKIP LOCKED`), advisory lock e recuperação de runs interrompidos | Sincronista | F1-05, F1-06 | 4 | Com o worker rodando, um run `pending` inserido no banco termina `succeeded`, com tarefas e containers no banco. Um segundo sync atualiza sem duplicar. Matar o worker no meio deixa o run marcado como `failed` ao reiniciar |
| F1-08 | API FastAPI da Fase 1: `/health`, `/projects`, `/people`, `/tasks`, `/tasks/{id}`, `/milestones`, `POST /sync` (202, 200 ou 429 com cooldown), `/sync/runs` e `/sync/runs/latest`. Paginação `limit`/`offset` e OpenAPI em `/api/v1/openapi.json` | Portal | F1-05 | 4 | `curl` em cada rota retorna o formato documentado; `POST /sync` duas vezes seguidas devolve 202 e depois 200; dentro do cooldown, 429 com `Retry-After`; o OpenAPI é gerado |
| F1-09a | Scaffold do front: Vite + React + TS, TanStack Query, proxy de `/api` para o backend, layout base e rotas. O destino do proxy vem de `VITE_API_PROXY_TARGET` (padrão `http://localhost:8000`), para funcionar fora e dentro do Docker | Vitrine | F1-01 | 1 | `npm run dev` sobe e a página inicial abre; o proxy responde `/api/v1/health` depois de F1-08; trocar `VITE_API_PROXY_TARGET` muda o destino do proxy |
| F1-09b | Telas da Fase 1: lista de tarefas com filtros, lista de marcos por data, árvore de projetos e botão "Sincronizar agora", que acompanha o status do run. Cliente TS gerado do OpenAPI | Vitrine | F1-08, F1-09a | 5 | Com o backend rodando, as telas mostram os dados sincronizados; o botão dispara o sync, mostra o progresso e trata o 429 do cooldown |
| F1-12 | Serviço `frontend` no `docker-compose.yml` e `frontend/Dockerfile` (dev server do Vite com `VITE_API_PROXY_TARGET=http://api:8000`). Também uma imagem única para `migrate`, `api` e `worker` (um `image:` comum na âncora `x-backend`), para que um rebuild não deixe serviços com dependências diferentes (sugestão do Revisor na F1-01) | Alicerce | F1-01, F1-09a | 2 | `docker compose up` sobe postgres, api, worker e frontend; a página do front abre pelo container |
| F1-10 | Revisão de cada entrega: F1-01, F1-03, F1-05, F1-06, F1-07, F1-08, F1-09a, F1-09b e F1-12 | Revisor | cada entrega | contínua | Parecer "aprovado" ou uma lista de bloqueios. Só o aprovado é integrado |
| F1-11 | Verificação ponta a ponta: `docker compose up`, sync agendado e manual, dados visíveis no front. Atualizar a seção "Commands" do `CLAUDE.md` e o status deste plano | Maestro + Carlos | todas, incluindo F1-12 | 6 | O Carlos valida a Fase 1 no navegador e libera o início da Fase 2 |

### Ondas (o que roda em paralelo)

| Onda | Tarefas | Observação |
|---|---|---|
| 0 | F1-01 (Alicerce) e F1-02 (Carlos) | Tudo depende da F1-01 |
| 1 | F1-03 (Conector), F1-05 (Arquivista) e F1-09a (Vitrine) | Áreas de arquivo separadas: podem ir em paralelo |
| 2 | F1-04 (Batedor), F1-08 (Portal) e F1-12 (Alicerce) | O Batedor depende do token do Carlos, e o resultado pode alterar o mapper. O Portal só depende das tabelas, porque `POST /sync` apenas insere em `sync_runs` |
| 3 | F1-06 (Conector) | |
| 4 | F1-07 (Sincronista) | |
| 5 | F1-09b (Vitrine) | Precisa do OpenAPI da F1-08 |
| 6 | F1-11 (Maestro + Carlos) | Encerramento da Fase 1 |

### Notas das revisões para as próximas tarefas

Pontos levantados pelo Revisor na onda 1, que os agentes das próximas tarefas devem seguir:

- **F1-06 (Conector):**
  - o `external_id` dos containers leva o nível como prefixo (`space:123`, `folder:456`, `list:789`), também em `external_parent_id` e `external_container_id` (ver `ARCHITECTURE.md` › "Mapeamento");
  - o `raw` é gerado com `model_dump(by_alias=True, mode="json", exclude_unset=True)`, como diz o `ARCHITECTURE.md` (decisão do Maestro, recomendada pelo Revisor);
  - uma data inválida numa tarefa não pode derrubar a página inteira.
- **F1-07 (Sincronista):**
  - use o conector só por `create_connector(settings)` e capture `ConnectorError` em `fetch_structure` (run `failed`); a interface está em `ARCHITECTURE.md` › "Sincronização";
  - o upsert envia `synced_at = now()` e `deleted_at = NULL` explicitamente, para que um registro que reaparece perca o soft delete;
  - `sync_state.updated_at` vai no `set_` do upsert, porque o `onupdate` não vale para `on_conflict_do_update`;
  - quando o id externo do pai ou do container muda (por exemplo, uma subtarefa que vira tarefa), o `parent_id`/`container_id` antigo precisa ser limpo;
  - use `report.allows_deletions` (e não `complete`) para marcar exclusões; no incremental, avance o watermark só se `report.complete`;
  - a reconciliação de tarefas só marca exclusões se a estrutura do mesmo run veio completa, e considera vistas as tarefas das três buscas (padrão, arquivadas e marcos) e as descartadas;
  - o agendador usa `ON CONFLICT DO NOTHING` contra o índice único parcial de `sync_runs`;
  - em processos que chamam `asyncio.run` mais de uma vez, fazer `dispose` do engine em cache.
- **F1-08 (Portal):**
  - toda consulta filtra `deleted_at IS NULL`;
  - `include_closed=false` exclui as tarefas com `status_type` `done` ou `closed`;
  - `order_by=updated_at` usa a coluna `source_updated_at`.

## Fase M: multi-integração (barra lateral de apps e GitLab)

A plataforma passa a reunir várias ferramentas, e o GitLab é a segunda. O desenho está em `ARCHITECTURE.md` › "Fase M: multi-integração".

Decisões do Carlos (2026-10-15):
- **por enquanto, os apps só ficam visíveis no painel**, e o usuário alterna entre eles por uma barra lateral. Nada de cruzar dados nem de escrever nas ferramentas;
- a barra lateral tem **só os aplicativos, com um ícone para cada um**, sem os grupos de telas de cada app;
- o GitLab é **o gitlab.com ou o self-hosted da empresa, conforme o que for disponibilizado**; o código serve para os dois, e começar no gitlab.com e passar depois para o self-hosted é a FM-11. O primeiro recorte é **merge requests e commits**;
- a Fase M **começa junto com a F1-11**: a barra lateral entra já, e o GitLab vem antes da Fase 2;
- no futuro os apps vão se integrar, com **escrita em pontos específicos**. Isso muda a regra de somente leitura e é decidido ponto a ponto, numa etapa própria.

### Checklist

- [x] Decisões do Carlos registradas (2026-10-15)
- [x] Plano de etapas definido (tabela abaixo)
- [x] Base multi-fonte já existente: protocolo `Connector`, `create_connector`, chave `(source, external_id)` e `sync_state` por recurso
- [x] Documentação atualizada: este plano, `ARCHITECTURE.md` e `CLAUDE.md`
- [x] Hooks estendidos ao GitLab: só GET em `connectors/gitlab/`, sem escrita na API do GitLab, tokens do GitLab tratados como segredo, `gitlab_spike.py` na área do Batedor e `selfcheck.py` passando (58/58)
- [x] FM-01: barra lateral de apps (Vitrine), integrada em a237fc1
- [x] Decisão: usar o gitlab.com ou o self-hosted, conforme o que for disponibilizado (2026-10-15)
- [x] FM-02: pré-requisitos do GitLab, na instância disponível (Carlos): gitlab.com, personal access token só com `read_api` e um grupo de teste
- [x] Variáveis do GitLab documentadas no `.env.example` (Alicerce, integrada em 47fb095)
- [x] FM-03: spike do GitLab (Batedor), integrado em 5a31907
- [x] Decisões pós-spike (Carlos, 2026-10-15): commits de todos os branches (`all=true`); assignees e reviewers dos MRs só no `raw` por enquanto
- [x] FM-04: modelo e tabelas do GitLab (Arquivista), integrada em 3cc8bad
- [x] FM-05: conector GitLab e variáveis de ambiente (Conector e Alicerce), integrada em 4f0fee6
- [ ] FM-06: sync do GitLab (Sincronista)
- [x] FM-07: rotas `/sources`, `/repositories`, `/merge-requests` e `/commits` (Portal), integrada em 4cf2003
- [ ] FM-08: telas do GitLab e a sidebar lendo `/sources` (Vitrine)
- [ ] FM-09: revisão de cada entrega (Revisor)
- [ ] FM-10: verificação ponta a ponta (Maestro e Carlos)
- [ ] FM-11: troca para o self-hosted, se a FM-02 começar no gitlab.com (Maestro e Carlos)

### Tarefas

| ID | Tarefa | Agente | Depende de | Onda | Entregável e critério de pronto |
|---|---|---|---|---|---|
| FM-01 | Barra lateral de apps: registro estático em `frontend/src/apps.ts` (`id`, `label`, `icon`, `basePath`, `nav`, `enabled`); `AppSidebar` com um botão de ícone por app (nome em `title`/`aria-label`), destaque no ativo, GitLab desabilitado com "em breve"; o header mostra as abas do app ativo; rotas com prefixo `/clickup/...` e redirecionamento das antigas; ícones SVG inline (paths do Simple Icons, CC0) sem dependência nova; em tela estreita, a sidebar vira uma faixa no topo | Vitrine | F1-09b | M0 | `npm run typecheck`, `npm run lint` e `npm run build` passam; no `npm run dev`, a sidebar mostra o ClickUp ativo e o GitLab desabilitado; as abas funcionam em `/clickup/...`; `/tarefas` redireciona; sem scroll horizontal na largura de celular |
| FM-02 | Fornecer, na instância disponível (gitlab.com ou self-hosted), o `GITLAB_URL`, um usuário bot e um token só com `read_api` no `.env` (no gitlab.com, um personal access token; no self-hosted, o bot com papel Reporter), os grupos ou projetos a sincronizar e, só no self-hosted, se o certificado TLS é interno | Carlos | — | M0 | `.env` preenchido (fora do git). O Maestro confirma que as variáveis existem, sem ler os valores |
| FM-03 | Spike do GitLab (`backend/scripts/gitlab_spike.py`, só GET): autenticação e escopo do token, projetos por grupo, MRs com `updated_after`, commits por projeto, paginação e headers de rate limit | Batedor | FM-02 | M1 | Relatório com uma resposta por item e a evidência, sem dados sensíveis. O Maestro atualiza o `ARCHITECTURE.md` |
| FM-04 | Modelos canônicos `Repository`, `MergeRequest` e `Commit` e a migration `0003` com `repositories`, `merge_requests` e `commits` | Arquivista | FM-03 | M2 | `alembic upgrade head` e `alembic downgrade -1` rodam limpos; `\d` mostra os índices únicos |
| FM-05 | `connectors/gitlab/` (cliente só GET, schemas, mapper e conector) e a generalização mínima de `base.py`/`factory.py` para mais de uma fonte. Variáveis `GITLAB_*` em `config.py` e `.env.example` (Alicerce) | Conector e Alicerce | FM-03, FM-04 | M3 | Um script imprime repositórios, MRs e commits no formato canônico; o cliente não tem método de escrita; sem as variáveis do GitLab, nada muda para o ClickUp; o código não distingue gitlab.com de self-hosted e segue o caminho mais compatível com versões antigas (ver `ARCHITECTURE.md` › "Compatibilidade entre instâncias") |
| FM-06 | Passos do GitLab no `SyncService`: repositórios, MRs incrementais e commits por repositório; uma falha numa fonte deixa o run `partial` | Sincronista | FM-05 | M4 | Um sync termina `succeeded` com dados do GitLab no banco; um segundo sync não duplica; sem GitLab configurado, o sync do ClickUp segue igual |
| FM-07 | Rotas `GET /sources`, `/repositories`, `/merge-requests` e `/commits` | Portal | FM-04 | M3 | `curl` em cada rota retorna o formato documentado; o OpenAPI é gerado |
| FM-08 | Sidebar lendo `/sources`; telas Merge Requests, Commits e Repositórios em `/gitlab/...`; cliente TS regenerado | Vitrine | FM-01, FM-07 | M5 | Com o backend rodando, o GitLab fica habilitado na sidebar e mostra os dados sincronizados |
| FM-09 | Revisão de cada entrega: FM-01, FM-03 a FM-08 | Revisor | cada entrega | contínua | Parecer "aprovado" ou uma lista de bloqueios |
| FM-10 | Verificação ponta a ponta e atualização deste plano e do `CLAUDE.md` | Maestro e Carlos | todas | M6 | O Carlos valida no navegador a alternância entre ClickUp e GitLab |
| FM-11 | Troca de instância, só se a FM-02 começar no gitlab.com: trocar o `.env`, refazer o spike contra o self-hosted, apagar os dados do GitLab com um script dedicado (`backend/scripts/`, do Conector) e sincronizar de novo. Procedimento em `ARCHITECTURE.md` › "Troca de instância" | Maestro e Carlos (Conector no script) | FM-10 e o self-hosted disponível | — | Sync `succeeded` contra o self-hosted, sem dados do gitlab.com no banco, e o Carlos confere no navegador |

A FM-01 roda em paralelo à F1-11 e não depende do GitLab. A conferência visual da barra lateral entra na própria F1-11.

**Fora da Fase M:** cruzar dados entre apps (por exemplo, MRs que citam uma tarefa do ClickUp), a escrita pontual nas ferramentas (quais pontos, qual token, auditoria e a mudança das regras), o Discord e outros apps, e o uso de tokens por pessoa no GitLab (a decidir junto com a Fase 2).

## Fase 2: autenticação e horas (à parte)

Só começa depois da F1-11. Esta tabela é uma visão prévia e será detalhada quando a Fase 2 for liberada.

| ID | Tarefa | Agente | Depende de |
|---|---|---|---|
| F2-01 | Passar os dados do LDAP (tipo de servidor, filtro, TLS, conta de serviço, grupo), conseguir que um Owner ou Admin cadastre o app OAuth no ClickUp e decidir a visibilidade das horas | Carlos | F1-11 |
| F2-02 | Tabelas `app_users`, `sessions`, `clickup_connections` e `time_entries`, numa migration própria | Arquivista | F1-11 |
| F2-03 | Login LDAP, sessões, a dependência `current_user` e a proteção de todas as rotas | Guardião | F2-01, F2-02 |
| F2-04 | Fluxo OAuth (connect, callback e desconectar), criptografia dos tokens e as rotas `/integrations/clickup/*` | Ponte | F2-01, F2-02, F2-03 |
| F2-05 | Passo 4 do sync: horas por pessoa conectada | Sincronista | F2-04 |
| F2-06 | Rotas `/time-entries` e `/time-entries/summary`, e o total de horas com cobertura em `/tasks/{id}` | Portal | F2-02, F2-03 |
| F2-07 | Telas de login, "Conectar ClickUp", "Minhas horas" e o indicador de cobertura | Vitrine | F2-03, F2-04, F2-06 |
| F2-08 | Revisão de cada entrega | Revisor | cada entrega |
| F2-09 | Verificação ponta a ponta da Fase 2 | Maestro + Carlos | todas |

## Acompanhamento

O Maestro atualiza a coluna de status a cada mudança. Os status possíveis são: `pendente`, `em andamento`, `em revisão`, `integrado` e `bloqueado` (com o motivo).

| ID | Status | Observação |
|---|---|---|
| F1-01 | integrado | Branch `alicerce/monorepo` (3941f53, 1fd9d44, 54e5ee1), integrada na `main` em 525c114 |
| F1-02 | integrado | `.env` preenchido pelo Carlos; o Maestro conferiu as variáveis sem ler os valores |
| F1-03 | integrado | Branch `conector/cliente-http` (8e4ca77, 1d807ac), integrada em d0dd46a |
| F1-04 | integrado | Script integrado (6c0fe59). Pendentes: tarefas arquivadas e marcos, porque o workspace testado não tem nenhum dos dois |
| F1-05 | integrado | Branch `arquivista/modelos-fase1` (d07ffd7, aa47dfd), integrada em 3823108 |
| F1-06 | integrado | Branch `conector/mapper` (ae19032, ccdca5b, 37a6397). Sugestões S1-S5 do Revisor aguardando o Carlos |
| F1-07 | integrado | Branch `sincronista/sync-worker` (c1f746c, 999f520), integrada em bc3bab4. Sync real verificado contra o ClickUp; marcos e exclusões reais não exercitados (workspace sem marcos). Sugestões 1-5 do Revisor aguardando o Carlos |
| F1-08 | integrado | Branch `portal/rotas-leitura` (828f1d3 a b326de7, com os ajustes aprovados e o filtro `archived`) |
| F1-09a | integrado | Branch `vitrine/scaffold` (f90301a, 1282231), integrada em 358dda4 |
| F1-09b | integrado | Branch `vitrine/telas-fase1` (5c77ab6, 4f90196), integrada em 67f9854. Sugestões do Revisor aguardando o Carlos |
| F1-12 | integrado | Branch `alicerce/frontend-compose` (55d6e05). Pendente: ver `api` e `worker` subindo, o que depende da F1-07 e da F1-08 (fica para a F1-11) |
| F1-11 | pendente | Inclui a conferência visual da FM-01 |
| FM-01 | integrado | Branch `vitrine/sidebar-apps` (ddbc799, c19dc48, 1d67ee2), integrada em a237fc1. Aprovada pelo Revisor após 2 bloqueios corrigidos; os ajustes do Carlos (link do GitHub no header, controles menores, barra de sync fluida) foram conferidos pelo Maestro no diff. A conferência visual final fica para a F1-11 |
| FM-02 | integrado | gitlab.com com personal access token só com `read_api` e o grupo de teste `yamada-group3`. Variáveis no `.env.example` em 47fb095 |
| FM-03 | integrado | Branch `batedor/spike-gitlab` (3856d6b), integrada em 5a31907. Achados no `ARCHITECTURE.md` › "GitLab": `RateLimit-Reset` em epoch, commits sem `X-Total`, autor do MR sem e-mail. Pendentes: `Retry-After` no 429, group e project access tokens no gitlab.com e o que um bot Reporter enxerga |
| FM-04 | integrado | Branch `arquivista/modelos-gitlab` (1b810a2, d6e36b8), integrada em 3cc8bad. Migration `0003`. Aprovada pelo Revisor sem bloqueios; aplicados o validator do autor do MR e as docstrings. Ficaram de fora o índice redundante `merge_requests (repository_id)` e um índice só em `commits (authored_at)` para a lista global, que só entra se a tela ficar lenta |
| FM-05 | integrado | Variáveis no `config.py` em 7b5adf9. Conector na branch `conector/gitlab` (a3c540c, f9b65fe), integrada em 4f0fee6. O Revisor bloqueou uma vez (falha de TLS entrava no retry), e a correção foi aprovada. Decisões do Carlos aplicadas: arquivados com `archived=true` e `with_shared=false`. Pendente: decidir se o cliente recusa `http://` fora de localhost (antes do self-hosted) |
| FM-06 | em andamento | |
| FM-07 | integrado | Branch `portal/rotas-gitlab` (dd74814, d6ee014), integrada em 4cf2003. Aprovada pelo Revisor sem bloqueios, testada com dados numa transação desfeita. Ajustes do Carlos: `source` em `/people` (padrão `clickup`), `author_id` sem pessoas removidas, `/repositories` ordenado sem diferenciar maiúsculas. Ficaram para depois: `/sources` sem índice em `tasks.synced_at` e a busca de commits por sha ou autor |
| FM-08 | pendente | |
| FM-09 | pendente | |
| FM-10 | pendente | |
| FM-11 | pendente | Só se a FM-02 começar no gitlab.com |
