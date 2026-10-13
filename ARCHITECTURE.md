# Arquitetura — scarlet-scribe

Camada intermediária para integrar ferramentas corporativas. A primeira integração é o **ClickUp**. A aplicação web centraliza tarefas, datas, marcos e registros de horas. Visão original em `PROJECT.md`.

Os dados do ClickUp chegam por dois caminhos:
- **Bot (token do serviço):** um usuário "bot" com permissão somente de leitura traz a estrutura do workspace (spaces, folders, lists), os membros, as tarefas e os marcos.
- **Token OAuth de cada pessoa (Fase 2):** as horas vêm daqui. A pessoa entra na aplicação com o **LDAP** da empresa e conecta a própria conta do ClickUp. A partir daí o worker busca as horas dela com o token dela. O ClickUp só deixa Owners e Admins lerem as horas de outras pessoas, e o bot não terá esse papel (ver "Riscos").

Itens marcados com **(a confirmar)** dependem do comportamento real da API do ClickUp. Eles serão verificados no spike (tarefa F1-04 do `PLANO_DE_EXECUCAO.md`) e este documento será corrigido em seguida.

## Fases

O projeto é construído em duas fases. **A autenticação é uma fase à parte e não faz parte da estrutura inicial.**

| Fase | Escopo | Fora do escopo |
|---|---|---|
| **Fase 1: estrutura inicial** | Monorepo e Docker Compose; cliente do ClickUp com o token do bot; modelo canônico e banco; sync de estrutura, tarefas e marcos (passos 1 a 3); worker e fila; API de leitura (`/projects`, `/people`, `/tasks`, `/milestones`, `/sync`); front com listagens e botão de sincronizar | Login, sessões, OAuth e **registro de horas**. As horas dependem do token de cada pessoa, que só existe depois da autenticação |
| **Fase 2: autenticação e horas (à parte)** | Login LDAP e sessões; proteção das rotas; conexão OAuth com o ClickUp; tabelas `app_users`, `sessions`, `clickup_connections` e `time_entries`; passo 4 do sync (horas por pessoa); rotas `/auth/*`, `/integrations/clickup/*` e `/time-entries*`; telas de login, "Conectar ClickUp" e "Minhas horas" | Verificação de identidade LDAP × ClickUp (etapa futura) |

**Na Fase 1 a API não tem login.** Todas as rotas ficam abertas, então a aplicação só deve rodar localmente ou em rede interna até a Fase 2. O código da Fase 1 não deve antecipar a Fase 2: não cria tabelas, rotas ou dependências de autenticação. A Fase 2 entra depois, por cima da estrutura pronta: um `Depends(current_user)` nos routers, as tabelas novas numa migration própria e um passo novo no `SyncService`.

As seções marcadas com **(Fase 2)** abaixo descrevem o desenho já acordado para essa fase e não são implementadas na Fase 1.

A divisão das tarefas entre agentes está em `PLANO_DE_EXECUCAO.md`.

## Decisões

| Tema | Decisão |
|---|---|
| Backend | Python 3.12 + FastAPI, `httpx` (async), Pydantic v2 + `pydantic-settings`, SQLAlchemy 2 (async) + Alembic |
| Banco | PostgreSQL |
| Frontend | Vite + React + TypeScript, TanStack Query; cliente TS gerado a partir do OpenAPI do backend |
| Frescor dos dados | Sync periódico (alguns minutos de atraso) + botão "Sincronizar agora" na UI |
| Login na web app | **Fase 2.** **LDAP** da empresa (usuário e senha), com sessão no servidor via cookie. Na Fase 1 não há login |
| Vínculo pessoa ↔ ClickUp | **Fase 2.** **OAuth do ClickUp**: cada pessoa conecta a própria conta. O id do usuário no ClickUp vem do próprio token, via `GET /v2/user`. A verificação cruzada de identidade (LDAP × ClickUp) fica para uma etapa futura |
| Deploy | Indefinido. Docker Compose para desenvolvimento local |
| Testes | Fora do escopo até existir um MVP |
| Auth do bot no ClickUp | Token pessoal (`pk_...`) do usuário bot, via variável de ambiente; nunca vai para o repositório |
| Horas | **Fase 2.** Somente via token OAuth de cada pessoa. O bot **nunca** consulta horas de outros usuários |

## Visão geral

```
                ┌──────────── worker (processo próprio) ─────────────┐
 ClickUp API ◄──┤ APScheduler ─┐                                     │
   (só GET)     │              ├─► SyncService ─► Connector(ClickUp) ├──► PostgreSQL ◄── API (FastAPI) ◄── Front (React)
                │ fila sync_runs┘   token do bot: estrutura/tarefas  │                    │   ▲   │
                │                   tokens OAuth: horas de cada um   │                    │   │   └─ login ─► LDAP
                └────────────────────────────────────────────────────┘                    │   │
 ClickUp OAuth ◄────────────── troca code → token (callback) ─────────────────────────────┘   │
 (tela de login do ClickUp) ◄──────── navegador redirecionado em "Conectar ClickUp" ──────────┘
```

- O **worker** é quem busca dados no ClickUp.
- A **API** fala com o ClickUp só em dois momentos do fluxo OAuth: no callback, para trocar o `code` pelo token, e para identificar o usuário (`GET /v2/user` e `GET /v2/team`). Fora disso, ela lê e escreve só no Postgres e consulta o LDAP no login.
- O front nunca fala com o ClickUp diretamente. Ele só redireciona o navegador para a tela de autorização.
- **Na Fase 1**, o diagrama se resume a: worker (token do bot) → Postgres ← API ← Front. Não existem LDAP, OAuth nem horas.

## Organização do código (backend)

```
backend/src/scarlet_scribe/
  config.py              # Settings (pydantic-settings), lidas do ambiente
  db/                    # engine/sessão async, modelos SQLAlchemy (tabelas)
  domain/                # modelos canônicos (Pydantic), independentes de ferramenta
  connectors/
    base.py              # protocolo Connector
    clickup/
      client.py          # cliente HTTP (httpx): auth, paginação, rate limit, retries
      schemas.py         # modelos Pydantic do JSON do ClickUp (só usados aqui dentro)
      mapper.py          # ClickUp → domain
      connector.py       # implementa Connector usando client + mapper
      oauth.py           # (Fase 2) URL de autorização e troca code → token
  auth/                  # (Fase 2)
    ldap.py              # autenticação no LDAP (ldap3): busca o usuário e valida a senha
    sessions.py          # criação, validação e expiração de sessões
    crypto.py            # criptografia dos tokens OAuth em repouso (Fernet)
  sync/
    service.py           # orquestra uma execução de sync (passos, upsert, contadores)
    worker.py            # entry point do worker: agendador + consumo da fila
  api/
    app.py               # cria o FastAPI e inclui os routers
    deps.py              # dependência de sessão do banco; current_user entra na Fase 2
    routes/              # Fase 1: tasks, milestones, people, projects, sync. Fase 2: auth, integrations, time_entries
    schemas.py           # modelos de request/response da API
backend/alembic/         # migrations
```

Entry points no `pyproject.toml`: a API roda com `uvicorn scarlet_scribe.api.app:app` e o worker com `scarlet-scribe-worker`, que aponta para `scarlet_scribe.sync.worker:main`.

## Configuração (variáveis de ambiente)

**Fase 1:**

| Variável | Padrão | Uso |
|---|---|---|
| `DATABASE_URL` | — | DSN do Postgres (`postgresql+asyncpg://...`) |
| `CLICKUP_API_TOKEN` | — | Token pessoal do bot (`pk_...`) |
| `CLICKUP_TEAM_ID` | — | Workspace a sincronizar. O ClickUp chama workspaces de "team" na API v2 |
| `CLICKUP_SPACE_IDS` | vazio = todos | Restringe o sync a alguns spaces (opcional) |
| `SYNC_INTERVAL_MINUTES` | `10` | Intervalo do sync agendado |
| `SYNC_MANUAL_COOLDOWN_SECONDS` | `60` | Tempo mínimo entre o início de dois syncs manuais |
| `SYNC_FULL_RECONCILE_HOURS` | `24` | Frequência da reconciliação completa de tarefas (detecta exclusões) |
| `CLICKUP_RATE_LIMIT_PER_MINUTE` | `100` | Limite preventivo do cliente, por token |

**Fase 2:**

| Variável | Padrão | Uso |
|---|---|---|
| `SYNC_TIME_ENTRIES_WINDOW_DAYS` | `30` | Janela de horas reprocessada a cada sync |
| `SYNC_BACKFILL_DAYS` | `180` | Histórico de horas importado na primeira vez de cada pessoa |
| `CLICKUP_OAUTH_CLIENT_ID` | — | `client_id` do app OAuth cadastrado no ClickUp |
| `CLICKUP_OAUTH_CLIENT_SECRET` | — | `client_secret` do app OAuth |
| `CLICKUP_OAUTH_REDIRECT_URI` | `http://localhost:5173/api/v1/integrations/clickup/callback` | URL de retorno registrada no app. Passa pelo proxy do Vite em desenvolvimento |
| `TOKEN_ENCRYPTION_KEY` | — | Chave Fernet para criptografar os tokens OAuth no banco |
| `LDAP_URL` | — | Por exemplo `ldaps://ldap.empresa.local:636` |
| `LDAP_START_TLS` | `false` | Usar StartTLS quando a URL for `ldap://` |
| `LDAP_BIND_DN` / `LDAP_BIND_PASSWORD` | — | Conta de serviço usada para buscar o DN do usuário |
| `LDAP_USER_BASE_DN` | — | Base de busca dos usuários |
| `LDAP_USER_FILTER` | `(uid={username})` | Filtro de busca. No Active Directory: `(sAMAccountName={username})` |
| `LDAP_ATTR_EMAIL` / `LDAP_ATTR_NAME` | `mail` / `cn` | Atributos lidos do usuário |
| `LDAP_REQUIRED_GROUP_DN` | vazio = qualquer usuário | Restringe o acesso a membros de um grupo (opcional) |
| `SESSION_TTL_HOURS` | `12` | Validade da sessão |
| `SESSION_COOKIE_SECURE` | `false` em dev | `true` em produção (HTTPS) |
| `SYNC_TIME_ENTRIES_CONCURRENCY` | `4` | Quantas pessoas têm as horas buscadas em paralelo |

Um arquivo `.env.example` vai documentar essas variáveis. O `.env` real fica no `.gitignore`.

Em desenvolvimento, o **Vite faz proxy de `/api` para o backend**, desde a Fase 1. Assim o front e a API ficam na mesma origem, e não há configuração de CORS. Na Fase 2, isso também faz o cookie de sessão e o callback do OAuth funcionarem sem ajustes.

## Autenticação de usuários (LDAP) (Fase 2)

**Login (`POST /api/v1/auth/login`, com `username` e `password`):**
1. A API se conecta ao LDAP com a conta de serviço e busca o usuário com `LDAP_USER_FILTER`. O `username` passa por escape de caracteres especiais do LDAP antes de entrar no filtro.
2. Com o DN encontrado, faz um novo bind usando a senha informada. Se o bind funcionar, a senha está correta. **A senha nunca é armazenada nem registrada em log.**
3. Se `LDAP_REQUIRED_GROUP_DN` estiver configurado, verifica se o usuário pertence ao grupo.
4. Faz upsert em `app_users` com `ldap_username`, `ldap_dn`, nome e e-mail.
5. Cria uma linha em `sessions` e devolve o cookie `session_id`, com `HttpOnly`, `SameSite=Lax` e `Secure` em produção.

A resposta de erro é sempre um 401 genérico ("usuário ou senha inválidos"), sem dizer se o usuário existe. Se o LDAP estiver inacessível, a resposta é 503.

**Sessões:**
- Ficam no Postgres, o que permite revogar e fazer logout de verdade.
- Cada request autenticada passa pela dependência `current_user`, que valida o cookie e a expiração.
- O logout apaga a sessão.

**Proteção:** todas as rotas da API exigem sessão, exceto `/health`, `/auth/login` e o callback do OAuth. O callback é validado pelo parâmetro `state`, descrito na próxima seção.

## Conexão da conta ClickUp (OAuth) (Fase 2)

**O app OAuth:** é um cadastro feito no próprio ClickUp por um **Owner ou Admin**, que gera o `client_id` e o `client_secret` e registra a URL de retorno. Ele não é uma aplicação separada: o fluxo inteiro roda no nosso backend.

**Fluxo de conexão:**
1. A pessoa, já logada via LDAP, clica em "Conectar ClickUp". O front navega para `GET /api/v1/integrations/clickup/connect`.
2. A API gera um `state` aleatório, guarda-o na sessão (proteção contra CSRF) e redireciona o navegador para `https://app.clickup.com/api?client_id=...&redirect_uri=...&state=...` **(a confirmar o formato exato da URL e o suporte a `state`)**.
3. A pessoa entra no ClickUp e autoriza o acesso aos workspaces. Ela precisa incluir o workspace `CLICKUP_TEAM_ID`.
4. O ClickUp redireciona o navegador para `GET /api/v1/integrations/clickup/callback?code=...&state=...`. A API:
   - confere se o `state` bate com o da sessão;
   - troca o `code` pelo token em `POST https://api.clickup.com/api/v2/oauth/token`, enviando `client_id`, `client_secret` e `code`;
   - chama `GET /v2/user` com o token novo para obter o id do usuário no ClickUp;
   - chama `GET /v2/team` para verificar se `CLICKUP_TEAM_ID` foi autorizado. Se não foi, salva a conexão com status `workspace_not_authorized` e mostra na UI como corrigir;
   - grava a conexão em `clickup_connections`, com o token **criptografado**, e liga `app_users.person_id` à `person` cujo `external_id` é o id do ClickUp. Se essa person ainda não existir, ela é criada;
   - cria um `sync_run` manual, para que as horas da pessoa apareçam logo;
   - redireciona para o front (`/settings?clickup=connected`).

**Uso do token:** o token OAuth é enviado como `Authorization: Bearer <token>`, ao contrário do token pessoal do bot, que vai sem prefixo. A documentação diz que o token "currently does not expire", mas que isso pode mudar. Por isso:
- todo 401 com o token de uma pessoa marca a conexão como `revoked`;
- a UI pede para a pessoa reconectar;
- o sync segue normalmente para as outras pessoas.

**Desconectar (`DELETE /api/v1/integrations/clickup`):** apaga o token e marca a conexão como `disconnected`. As horas já sincronizadas continuam no banco. A documentação não mostra endpoint para revogar o token no ClickUp, então a UI orienta a pessoa a remover o app também na conta dela, se quiser **(a confirmar)**.

**Permissões:** o ClickUp não oferece escopos. O token OAuth tem os mesmos poderes da pessoa, inclusive escrita. Por isso:
- o código só usa GET;
- os tokens ficam criptografados em repouso;
- os tokens nunca aparecem em logs, respostas da API ou no `raw` dos registros.

**Verificação de identidade (etapa futura):** na Fase 2 aceitamos o vínculo feito pelo OAuth. Ele já garante que a pessoa entrou na conta do ClickUp que conectou, mas não garante que essa conta é dela segundo o LDAP. A etapa futura compara o e-mail do LDAP com o e-mail do ClickUp, e uma divergência bloqueia o vínculo ou o marca para revisão. O campo `identity_verified_at` em `clickup_connections` já fica reservado para isso.

## Integração com o ClickUp

### Autenticação e cliente HTTP

- A base é `https://api.clickup.com/api/v2`.
- O cliente aceita dois tipos de credencial:
  - o token pessoal do bot, que vai **sem** prefixo: `Authorization: pk_...`. Tokens pessoais começam com `pk_`, não expiram e são gerados em *Settings > Apps > API Token*;
  - (Fase 2) o token OAuth de uma pessoa, que vai com prefixo: `Authorization: Bearer ...`. Na Fase 1, o cliente já recebe o esquema de autenticação como parâmetro, para que essa adição não exija refatoração.

  Cada token tem uma instância própria do cliente, com seu próprio controle de ritmo, porque o rate limit é contado por token.
- A documentação não fala em escopos nem em tokens "somente leitura". O token enxerga o que o usuário dono dele enxerga: "You can only view task information of tasks you can access". Por isso, a restrição de leitura depende do **papel do bot no workspace** e da regra de só usar GET no código.
- O cliente expõe **apenas métodos GET**. Não existe nenhuma função de escrita, o que reforça por código a regra de "somente leitura".
- Usa um único `httpx.AsyncClient` por execução de sync, com timeout de 30 s.
- Datas do ClickUp chegam como **Unix em milissegundos**, muitas vezes em string. O mapper converte para `datetime` em UTC. Durações também vêm em milissegundos.
- Na API v2, "team" significa **workspace**. A v3 já usa "workspace". `team_id` e `workspace_id` são o mesmo id.

### Rate limit, retries e erros

- O limite é por token e depende do plano do workspace:

  | Plano | Limite |
  |---|---|
  | Free Forever, Unlimited e Business | 100 req/min |
  | Business Plus | 1.000 req/min |
  | Enterprise | 10.000 req/min |

  O plano da empresa ainda precisa ser confirmado. O endpoint `getworkspaceplan` informa o plano, e o spike pode consultá-lo.
- Ao estourar o limite, a API responde **HTTP 429**. Os headers são `X-RateLimit-Limit`, `X-RateLimit-Remaining` e `X-RateLimit-Reset`.
  - A documentação só garante esses headers na resposta de erro.
  - A unidade do `Reset` não é dita, apenas "Unix timestamp". Na prática deve ser em segundos.
  - **No spike:** verificar se os headers vêm também nas respostas 200 e qual a unidade do `Reset`.
- Com base nisso, o cliente faz um controle preventivo: limita a si mesmo a 100 req/min por padrão, com valor configurável. Quando os headers aparecerem numa resposta, ele os usa para ajustar o ritmo.
- Retries com backoff exponencial e jitter (até 5 tentativas):
  - **HTTP 429:** espera até o `X-RateLimit-Reset`. Se o valor for maior que 10¹², trata como milissegundos. Sem o header, usa backoff.
  - **HTTP 5xx, timeout ou erro de rede:** backoff 1s, 2s, 4s, 8s...
  - **HTTP 401 com o token do bot:** sem retry. O run falha com a mensagem "token do bot inválido ou revogado".
  - **(Fase 2) HTTP 401 com o token de uma pessoa:** sem retry. A conexão dela vira `revoked` e o sync continua com as outras pessoas.
  - **HTTP 403 ou 404 num recurso específico:** sem retry. O recurso é registrado como erro do passo e o sync segue para o próximo.

### Endpoints de leitura do ClickUp

Fonte: a referência oficial em <https://developer.clickup.com/reference>, consultada em 2026-10-13. Todos os caminhos são relativos a `https://api.clickup.com/api` e são da v2, salvo indicação em contrário.

#### Usados nas Fases 1 e 2

| Dado | Endpoint | Detalhes da documentação e como usamos |
|---|---|---|
| Usuário dono do token | `GET /v2/user` | Retorna `id`, `username`, `email`, timezone e outros dados. Com o token do bot, valida o token no início do sync. Com o token OAuth, identifica a pessoa no callback |
| Workspaces e membros | `GET /v2/team` | Retorna `teams[]`, e cada item traz `id`, `name` e `members[].user`. Com o token do bot, **é a fonte das `people`**. Com o token OAuth, confirma no callback que `CLICKUP_TEAM_ID` foi autorizado. A documentação não mostra o papel de cada membro |
| Troca do código OAuth (Fase 2) | `POST /v2/oauth/token` | A única chamada não-GET do sistema. Não altera dados do ClickUp: só obtém o token da pessoa. Envia `client_id`, `client_secret` e `code` |
| Spaces | `GET /v2/team/{team_id}/space?archived=false` | |
| Folders | `GET /v2/space/{space_id}/folder?archived=false` | Subfolders vêm na mesma lista, sem aninhamento, cada uma com `parent_folder`. O mapper monta a árvore a partir desse campo |
| Lists em folders | `GET /v2/folder/{folder_id}/list?archived=false` | |
| Lists fora de folders | `GET /v2/space/{space_id}/list?archived=false` | |
| Tarefas | `GET /v2/team/{team_id}/task` | Ver os detalhes logo abaixo da tabela |
| Horas (Fase 2) | `GET /v2/team/{team_id}/time_entries` | Chamado **com o token OAuth de cada pessoa**. Ver os detalhes logo abaixo da tabela |
| Tipos de tarefa | `GET /v2/team/{team_id}/custom_item` | Retorna `custom_items[]` com `id`, `name`, `name_plural` e `description`. Usamos para mostrar o nome do tipo (por exemplo "Bug") |

**Tarefas (`GET /v2/team/{team_id}/task`, "Get Filtered Team Tasks"):**
- Retorna **100 tarefas por página**, com `page` começando em 0.
- **A resposta deste endpoint não tem `last_page`.** O campo só existe em `GET /v2/list/{list_id}/task`. Por isso, o cliente para de paginar quando uma página volta com menos de 100 tarefas.
- Por padrão, subtarefas e tarefas fechadas ficam de fora. Por isso enviamos `subtasks=true&include_closed=true`.
- Filtros úteis:
  - `date_updated_gt` e `date_updated_lt`, para o sync incremental;
  - `order_by` (`id`, `created`, `updated` ou `due_date`) e `reverse`;
  - `space_ids[]`, `project_ids[]` (que são folders) e `list_ids[]`;
  - `statuses[]`, `assignees[]` e `tags[]`;
  - `due_date_gt`/`_lt`, `date_created_gt`/`_lt` e `date_done_gt`/`_lt`;
  - `custom_items[]` (`0` = tarefa, `1` = marco, outros valores = tipos customizados);
  - `parent`, `custom_fields` e `include_markdown_description`.
- Todas as datas são em ms, inteiros de 64 bits.
- Cada tarefa traz `custom_fields` só com os campos aplicáveis ao seu `custom_item_id`.
- A documentação não fala de tarefas arquivadas neste endpoint. O endpoint por list aceita `archived`. **No spike:** verificar se tarefas arquivadas aparecem.

**Horas (Fase 2) (`GET /v2/team/{team_id}/time_entries`, "Get time entries within a date range"):**
- Sem `assignee`, retorna as horas **do próprio dono do token**. Sem datas, o período padrão são os últimos 30 dias.
- É exatamente esse comportamento que usamos: cada chamada é feita com o token OAuth de uma pessoa e **nunca envia `assignee`**. O filtro `assignee` com outros usuários é restrito a Owners e Admins e não é usado no sistema.
- Outros parâmetros:
  - `start_date` e `end_date`, em ms;
  - `include_location_names`, que traz os nomes de list, folder e space;
  - `include_task_tags`;
  - `is_billable`;
  - um único filtro de localização por chamada: `space_id`, `folder_id`, `list_id` **ou** `task_id`.
- **Não há paginação documentada.** Por isso dividimos o período em blocos (por exemplo, de 7 dias) para limitar o tamanho das respostas.
- Uma duração negativa indica um timer em andamento.

**Marcos:** confirmado. Um marco é uma tarefa com `custom_item_id = 1`, enquanto `0` é uma tarefa comum. Os marcos vêm pelo mesmo endpoint de tarefas e o mapper marca `is_milestone = (custom_item_id == 1)`. **No spike:** confirmar se a busca sem `custom_items[]` já traz os marcos. Se não trouxer, enviamos `custom_items[]=0&custom_items[]=1` e mais os tipos customizados que a empresa usa.

#### Úteis em versões futuras

| Endpoint | Para quê | Observações |
|---|---|---|
| `GET /v2/list/{list_id}/task` | Tarefas de uma list específica | Tem `last_page` e o parâmetro `archived`. Só inclui tarefas cuja list "principal" é aquela; `include_timl=true` traz também as tarefas que estão em várias lists |
| `GET /v2/task/{task_id}` | Detalhe de uma tarefa | Aceita `include_subtasks`, `include_markdown_description` e `custom_task_ids` (este exige `team_id`). Não retorna Docs anexados |
| `GET /v2/list/{list_id}/field` | Definições de campos customizados | Também existem as variantes por folder, space e workspace (`getfolderavailablefields`, `getspaceavailablefields`, `getteamavailablefields`) |
| `GET /v2/space/{space_id}/tag` | Tags de um space, com cores | |
| `GET /v2/task/{task_id}/time_in_status` e `GET /v2/task/bulk_time_in_status/task_ids` | Tempo de cada tarefa em cada status (o bulk aceita até 100 tarefas) | Exige que a ClickApp "Total time in Status" esteja ativada por um Owner ou Admin |
| `GET /v2/team/{team_id}/time_entries/current` | Timer em andamento | Aceita `assignee` |
| `GET /v2/team/{team_id}/time_entries/{timer_id}` e `.../{timer_id}/history` | Uma entrada de horas e o histórico de alterações dela | |
| `GET /v2/task/{task_id}/comment` | Comentários de uma tarefa | 25 por página, do mais novo para o mais antigo. Para paginar, envia `start` e `start_id` do último comentário recebido |
| `GET /v2/team/{team_id}/shared` | Tarefas, lists e folders compartilhados diretamente com o bot | Útil se o bot entrar como guest |
| `GET /v2/list/{list_id}/member` e `GET /v2/task/{task_id}/member` | Quem tem acesso explícito a uma list ou tarefa | Não inclui acessos herdados |
| Goals (`getgoals`, `getgoal`) | Metas e targets | Caminho a confirmar |
| Views (`getteamviews`, `getviewtasks` e outros) | Views salvas e as tarefas de cada view | Caminho a confirmar |
| `getworkspaceplan` e `getworkspaceseats` | Plano do workspace (define o rate limit) e assentos | Caminho a confirmar |
| `GET /v2/task/{task_id}/time` | Horas registradas numa tarefa | **Legado.** A documentação recomenda os endpoints de time tracking. Permissões não documentadas |

#### Fora de escopo ou indisponíveis

- **Escrita de qualquer tipo**, ou seja, todo POST, PUT e DELETE. Isso inclui webhooks, que exigem criação (ver o risco 3). A única exceção é `POST /v2/oauth/token`, que só obtém um token.
- `getuser` e `getguest`: exigem plano **Enterprise**.
- Audit logs: só o Owner pode consultá-los, e exigem plano Enterprise.
- Checklists e relacionamentos de tarefas (dependências e links): não há endpoint GET dedicado. Esses dados vêm, quando vêm, dentro do payload da tarefa.
- Chat, Docs e Attachments (API v3): fora do contexto de tarefas, horas e marcos.

### Mapeamento ClickUp → modelo canônico

| Canônico | Origem no ClickUp | Notas |
|---|---|---|
| `Workspace` | team | |
| `Container` | space / folder / list | Árvore com `kind` (`space`, `folder` ou `list`) e `parent_id`. A UI chama de "projeto" |
| `Person` | membro do team (`user.id`, `username`, `email`) | |
| `Task` | task | `name`, `status.status` e o tipo do status, `priority`, `start_date`, `due_date`, `date_done`, `time_estimate`, assignees, list (container), `parent` (subtarefa), `url`, `is_milestone`, `date_updated` |
| `TimeEntry` (Fase 2) | time entry, buscada com o token da pessoa | `user` → person (deve ser sempre o dono do token; se vier outro, a entrada é descartada e o caso vai para o log), `task.id` → task (pode ser nulo), `start`, `end`, `duration`, `billable`, `description`. Uma duração negativa indica timer em andamento: salva com `end=null` e `is_running=true`. Se a tarefa ainda não existir no banco (por exemplo, numa list que o bot não enxerga), `task_id` fica nulo e o id original fica guardado em `external_task_id` |

## Banco de dados

Convenções para todas as tabelas sincronizadas:
- `id` é um UUID interno. A API expõe só esse id, nunca o id do ClickUp como chave.
- Guardam `source` (`'clickup'`) e `external_id`, com `UNIQUE (source, external_id)`; o upsert usa `INSERT ... ON CONFLICT`.
- `raw` (JSONB) guarda o payload original. Serve para depuração e para remapear campos sem novo sync. Só o mapper lê esse campo.
- `synced_at` registra o último sync que viu o registro. `deleted_at` faz soft delete quando o registro some na origem.

Tabelas da **Fase 1**:
- `workspaces`, `containers`, `people`
- `tasks`, mais `task_assignees` (N:N com `people`)
- `sync_runs`: `id`, `trigger` (`scheduled` | `manual`), `status` (`pending` | `running` | `succeeded` | `partial` | `failed`), `requested_at`, `started_at`, `finished_at`, `stats` (JSONB com contadores por entidade: criados, atualizados, removidos), `error`
- `sync_state`: o "watermark" de cada `(source, resource)`, por exemplo o último `date_updated` visto nas tarefas e a data da última reconciliação completa

Tabelas da **Fase 2**, criadas numa migration própria:
- `time_entries`, com `person_id`, `task_id` (pode ser nulo) e `external_task_id`
- `app_users`: usuários da aplicação, vindos do LDAP. Campos: `id`, `ldap_username` (único), `ldap_dn`, `display_name`, `email`, `person_id` (FK para `people`, que pode ser nulo até a pessoa conectar o ClickUp), `created_at` e `last_login_at`. **Não é uma tabela sincronizada:** não tem `source` nem `external_id`
- `sessions`: `id` (valor aleatório do cookie, guardado como hash), `user_id`, `created_at`, `expires_at`
- `clickup_connections`: uma por `app_user`. Campos:
  - `user_id` (único);
  - `clickup_user_id`;
  - `access_token_encrypted`;
  - `status` (`active`, `revoked`, `workspace_not_authorized` ou `disconnected`);
  - `connected_at`, `last_synced_at` e `last_error`;
  - `identity_verified_at`, reservado para a etapa futura de verificação de identidade

Índices principais: `tasks (due_date)`, `tasks (container_id)` e `tasks (is_milestone)`. Na Fase 2 entram também `time_entries (person_id, start)` e `time_entries (task_id)`.

## Sincronização

### Passos de uma execução

Os passos rodam em ordem. Cada um faz commit próprio, então uma falha num passo não desfaz os anteriores.

1. **Estrutura:** workspace, members, spaces, folders e lists. Sempre completo, porque são poucas chamadas. Containers que sumiram ganham `deleted_at`.
2. **Tarefas, modo incremental:** `date_updated_gt = watermark − 5 min`. A margem cobre diferenças de relógio e atualizações concorrentes. Upsert de tudo o que vier, depois o watermark avança.
3. **Tarefas, reconciliação completa:** roda a cada `SYNC_FULL_RECONCILE_HOURS` e no primeiro sync. Busca todas as tarefas e marca com `deleted_at` as que não voltaram. Esse passo é necessário porque o modo incremental não detecta exclusões.
4. **(Fase 2) Horas, uma vez por conexão `active`:** roda para todas as conexões, até `SYNC_TIME_ENTRIES_CONCURRENCY` pessoas em paralelo. Para cada pessoa:
   - decifra o token e cria um cliente próprio, que tem seu próprio rate limit;
   - busca a janela `[agora − SYNC_TIME_ENTRIES_WINDOW_DAYS, agora]` em `GET /v2/team/{team_id}/time_entries`, **sem `assignee`**. Na primeira vez dessa pessoa, a janela usa `SYNC_BACKFILL_DAYS`;
   - divide a janela em blocos (por exemplo, de 7 dias), porque o endpoint não pagina;
   - faz upsert e remove da janela **as entradas daquela pessoa** que não voltaram. Reprocessar a janela captura edições e exclusões, que não têm filtro "updated since";
   - em caso de 401, marca a conexão como `revoked` e segue para a próxima pessoa.

   Pessoas sem conexão simplesmente não têm horas. A UI mostra a cobertura, por exemplo "8 de 12 pessoas conectadas".

Status final:
- `succeeded`: todos os passos passaram;
- `partial`: algum passo falhou, mas outros dados foram gravados. Na Fase 2 isso inclui falhas nas horas de alguma pessoa; os erros de cada pessoa ficam em `stats.time_entries.errors` e em `clickup_connections.last_error`;
- `failed`: nada foi gravado, ou houve erro fatal (por exemplo, 401).

### Worker e fila

- O worker roda em processo próprio: `scarlet-scribe-worker`.
- O **APScheduler** cria um `sync_run` com `trigger=scheduled` e `status=pending` a cada `SYNC_INTERVAL_MINUTES`. Ele não cria um run novo se já houver um `pending` ou `running`.
- Um loop consulta a fila a cada ~3 s e "pega" o run `pending` mais antigo com `SELECT ... FOR UPDATE SKIP LOCKED`, marcando-o como `running`.
- Um **advisory lock do Postgres** (chave fixa) envolve a execução. Isso garante um único sync por vez mesmo se, por engano, subirem dois workers.
- Ao iniciar, o worker marca como `failed` ("interrompido") os runs que ficaram em `running`, que seriam sobras de um crash.

## API HTTP

Todas as rotas usam o prefixo `/api/v1` e respondem em JSON, com datas em ISO 8601 UTC. O OpenAPI fica em `/api/v1/openapi.json` e é dele que o cliente TypeScript do front é gerado.

**Paginação** nas listagens: `?limit=50&offset=0` (limite máximo de 200). A resposta tem o formato `{ "items": [...], "total": 123 }`.

**Erros:** formato padrão do FastAPI (`{ "detail": ... }`):
- 404 para id inexistente;
- 422 para parâmetro inválido;
- (Fase 2) 401 sem sessão válida.

**Acesso:**
- **Fase 1:** todas as rotas são abertas, sem login.
- **Fase 2:** todas as rotas passam a exigir sessão, exceto `/health`, `/auth/login` e `/integrations/clickup/callback` (validado pelo `state`).

### Autenticação e conexão com o ClickUp (Fase 2)

| Método e rota | Comportamento |
|---|---|
| `POST /auth/login` | Recebe `{ "username", "password" }`. Faz bind no LDAP. Se der certo, define o cookie de sessão e retorna o usuário. Senão, retorna 401 genérico. Com o LDAP fora do ar, retorna 503 |
| `POST /auth/logout` | Apaga a sessão e o cookie |
| `GET /auth/me` | Usuário logado mais o status da conexão: `{ "user": {...}, "clickup": { "status": "active", "clickup_user_id": "...", "last_synced_at": "..." } }`. O front usa essa rota para saber se mostra o botão "Conectar ClickUp" |
| `GET /integrations/clickup/connect` | Gera o `state` e redireciona (302) para a tela de autorização do ClickUp |
| `GET /integrations/clickup/callback` | Recebe `code` e `state`, troca o código pelo token, identifica a pessoa, grava a conexão, agenda um sync e redireciona (302) para o front. Os detalhes estão em "Conexão da conta ClickUp" |
| `DELETE /integrations/clickup` | Desconecta: apaga o token. As horas já sincronizadas são mantidas |

### Leitura

| Método e rota | Filtros (query) | Retorno |
|---|---|---|
| `GET /health` | — | Status da API, do banco e do último sync |
| `GET /projects` | `kind`, `parent_id` | Árvore space/folder/list |
| `GET /people` | `q` | Members |
| `GET /tasks` | `container_id`, `status`, `assignee_id`, `due_from`, `due_to`, `is_milestone`, `include_closed` (padrão `false`), `q` (busca no nome), `order_by` (`due_date`, `updated_at` ou `name`) | Lista paginada |
| `GET /tasks/{id}` | — | Detalhe da tarefa, com assignees e subtarefas. (Fase 2) Ganha o total de horas, que soma **só as entradas sincronizadas**, ou seja, as das pessoas conectadas. Por isso vem acompanhado de `time_tracked_coverage`, que diz quantos assignees estão conectados. Enquanto a regra de visibilidade não for definida, mostra só o total, sem detalhar por pessoa |
| `GET /milestones` | `container_id`, `due_from`, `due_to` | Atalho para `GET /tasks?is_milestone=true`, ordenado por `due_date` |
| (Fase 2) `GET /time-entries` | `task_id`, `container_id`, `from`, `to` | Lista paginada **das horas do usuário logado** |
| (Fase 2) `GET /time-entries/summary` | `from`, `to` (obrigatórios), `group_by` (`container`, `task` ou `day`), filtros iguais aos de `GET /time-entries` | Totais de horas agrupados **do usuário logado** (`[{ key, label, total_ms }]`) |

Registros com `deleted_at` preenchido nunca aparecem nas respostas.

**(Fase 2) Visibilidade das horas:** cada pessoa vê **só as próprias horas**. Ver as horas de outras pessoas, com filtro `person_id` e `group_by=person`, depende de uma regra de permissão que ainda não foi definida, por exemplo um grupo LDAP de gestores. Ver "Riscos". Os parâmetros ficam reservados até essa decisão.

### Sincronização

| Método e rota | Comportamento |
|---|---|
| `POST /sync` | Pede um sync manual. **202** com o run criado (`pending`). Se já houver um run `pending` ou `running`, devolve **200** com esse run, e o front só passa a acompanhá-lo. Se o último sync manual começou há menos de `SYNC_MANUAL_COOLDOWN_SECONDS`, responde **429** com o header `Retry-After` |
| `GET /sync/runs/latest` | O run mais recente, que o front consulta a cada ~2 s enquanto ele estiver `pending` ou `running` |
| `GET /sync/runs` | Histórico paginado dos runs |

O sync manual sincroniza tudo: estrutura e tarefas e, na Fase 2, as horas de todas as pessoas conectadas. Não existe sync "só das minhas horas".

Formato de um run:
```json
{
  "id": "uuid",
  "trigger": "manual",
  "status": "running",
  "requested_at": "2026-10-13T12:00:00Z",
  "started_at": "2026-10-13T12:00:02Z",
  "finished_at": null,
  "stats": { "tasks": { "created": 3, "updated": 41, "deleted": 0 } },
  "error": null
}
```

## Estrutura do repositório (alvo)

```
backend/            # pacote uv (src/scarlet_scribe/...), alembic/
frontend/           # Vite + React + TS
docker-compose.yml  # postgres, api, worker, frontend
.env.example
```

## Riscos a validar

1. **Horas de outras pessoas (decidido).** O filtro `assignee` com outros usuários em `GET /v2/team/{team_id}/time_entries` é restrito a **Owners e Admins**, e o bot não terá esse papel. **Decisão:** as horas vêm do token OAuth de cada pessoa, conectado após o login LDAP. Consequências:
   - as horas cobrem **só quem conectou** a conta, e a UI mostra essa cobertura;
   - os tokens OAuth dão acesso de escrita, porque o ClickUp não tem escopos. Por isso ficam criptografados em repouso, fora dos logs, e o código só usa GET.
2. **Itens a verificar no spike com o token real:**
   - se tarefas arquivadas aparecem em `GET /v2/team/{team_id}/task`;
   - se marcos vêm sem o filtro `custom_items[]`;
   - se os headers `X-RateLimit-*` aparecem nas respostas 200, e a unidade do `X-RateLimit-Reset`;
   - qual é o plano do workspace.

   Já resolvido pela documentação: `last_page` não existe nesse endpoint, então paramos quando a página tiver menos de 100 tarefas; e marco é `custom_item_id = 1`.
3. **Webhooks:** fora do MVP. A documentação diz que webhooks pertencem ao usuário que os cria, mas não diz qual papel é necessário para criá-los. Criar um webhook também é uma escrita.
4. **Rate limit:** 100 req/min nos planos até Business, contados **por token**.
   - O token do bot cobre a estrutura e as tarefas. Um sync incremental típico gasta poucas dezenas de chamadas, e a reconciliação completa custa cerca de N/100 chamadas para N tarefas.
   - As horas usam o limite do token de cada pessoa: cerca de 5 chamadas por pessoa, numa janela de 30 dias com blocos de 7. Assim, as horas não disputam o limite do bot.
   - Ponto de atenção: se a pessoa usar o mesmo token em outras integrações, o limite é compartilhado com elas.
5. **(Fase 2) App OAuth no ClickUp:**
   - um Owner ou Admin precisa cadastrar o app;
   - falta confirmar se o ClickUp aceita `localhost` como URL de retorno em desenvolvimento;
   - falta confirmar o formato exato da URL de autorização, o suporte ao parâmetro `state` e se existe forma de revogar o token pela API.
6. **(Fase 2) LDAP:** falta saber o tipo de servidor (Active Directory ou OpenLDAP), o filtro de usuário, se a conexão é via LDAPS ou StartTLS, se há um grupo que restringe o acesso e se existe uma conta de serviço para a busca.
7. **(Fase 2) Visibilidade das horas (decisão pendente):** cada pessoa vê só as próprias horas. Falta definir quem pode ver as horas de outras pessoas, por exemplo gestores identificados por um grupo LDAP.
8. **Verificação de identidade (etapa futura):** comparar o e-mail do LDAP com o e-mail do ClickUp no momento da conexão. Até lá, o vínculo vale como foi feito pelo OAuth.

## Ordem de construção

A ordem das tarefas, o agente responsável por cada uma, as dependências e os critérios de pronto estão em **`PLANO_DE_EXECUCAO.md`**. Resumo:
- **Fase 1:** monorepo, cliente do ClickUp com spike, banco, mapper, sync e worker, API de leitura e front.
- **Fase 2 (à parte):** LDAP, OAuth, horas e as telas correspondentes. Começa só depois que a Fase 1 estiver validada e que os itens 5 a 7 dos riscos estiverem resolvidos.
