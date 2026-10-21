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
| **Fase M: multi-integração** (começa junto com a F1-11, antes da Fase 2) | Barra lateral com os apps conectados; GitLab (gitlab.com ou self-hosted, conforme o disponível) como segunda fonte (repositórios, merge requests e commits), só leitura, com token de bot; rotas `/sources`, `/repositories`, `/merge-requests` e `/commits` | Cruzar dados entre apps; escrita nas ferramentas; login; Discord e outros apps |
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
    base.py              # protocolo Connector, StructureSnapshot, TaskListing, ListingReport, FetchIssue e as exceções ConnectorError/AuthError/ConfigError
    factory.py           # create_connector(settings): único ponto por onde o sync obtém um conector
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

`CLICKUP_API_TOKEN` e `CLICKUP_TEAM_ID` são opcionais no `Settings`, para que a API e as migrations funcionem antes de o token existir; quem usa o ClickUp (conector e sync) exige que estejam preenchidos. Uma variável vazia conta como ausente.

**Só do Docker Compose** (não são lidas pelo `config.py`; o compose monta o `DATABASE_URL` dos containers a partir delas):

| Variável | Padrão | Uso |
|---|---|---|
| `POSTGRES_PASSWORD` | `postgres` | Senha do Postgres de desenvolvimento (o usuário é fixo: `postgres`) |
| `POSTGRES_DB` | `scarlet_scribe` | Nome do banco |
| `POSTGRES_PORT` | `5432` | Porta do Postgres exposta no host |
| `API_PORT` | `8000` | Porta da API exposta no host |
| `FRONTEND_PORT` | `5173` | Porta do frontend (Vite) exposta no host |

Mudar `POSTGRES_PASSWORD`, `POSTGRES_DB` ou `POSTGRES_PORT` exige ajustar também o `DATABASE_URL`, que é o usado fora do Docker. Os serviços `migrate`, `api` e `worker` usam uma única imagem do backend, `<projeto>-backend`.

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

O arquivo `.env.example`, na raiz, documenta essas variáveis. O `.env` real fica na raiz do repositório e no `.gitignore`; o `config.py` o encontra pela própria posição, de qualquer diretório.

**Só do frontend** (lida pelo Vite, que não lê o `.env` da raiz; só os arquivos `frontend/.env*` e o ambiente do processo):

| Variável | Padrão | Uso |
|---|---|---|
| `VITE_API_PROXY_TARGET` | `http://localhost:8000` | Destino do proxy de `/api/` no servidor de desenvolvimento. No Docker Compose: `http://api:8000` |

Variáveis `VITE_*` ficam visíveis no bundle do navegador: nenhuma delas pode carregar segredo.

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

  O plano é informado por `GET /v2/team/{team_id}/plan`, que responde `{plan_id, plan_name}` (confirmado no spike; o workspace de teste é Free Forever, `plan_id` 21, 100 req/min). O plano do workspace da empresa ainda precisa ser confirmado.
- Ao estourar o limite, a API responde **HTTP 429**. Os headers são `X-RateLimit-Limit`, `X-RateLimit-Remaining` e `X-RateLimit-Reset`.
  - **Confirmado no spike:** os três headers vêm também em todas as respostas 200.
  - `X-RateLimit-Reset` é Unix em **segundos**. A janela parece fixa (de 60 s), não deslizante.
  - `X-RateLimit-Remaining` não é estritamente decrescente entre chamadas seguidas: o contador do ClickUp parece ter consistência eventual. Por isso o cliente mantém também o próprio controle preventivo.
- Com base nisso, o cliente faz um controle preventivo: limita a si mesmo a 100 req/min por padrão, com valor configurável. Quando os headers aparecem numa resposta, ele os usa para ajustar o ritmo, mas **só para baixo**: o limite efetivo é o menor entre `CLICKUP_RATE_LIMIT_PER_MINUTE` e `X-RateLimit-Limit`. Num plano com limite maior, o ritmo sobe aumentando a variável. Uma resposta com `X-RateLimit-Remaining` zerado faz as chamadas seguintes esperarem até o `Reset`.
- Retries com backoff exponencial e jitter (até 5 tentativas):
  - **HTTP 429:** espera até o `X-RateLimit-Reset`. Se o valor for maior que 10¹², trata como milissegundos. A espera tem teto de 90 s, contra relógio dessincronizado ou valor estranho, e nunca é menor que o backoff da tentativa, para o caso de o `Reset` já estar no passado. Sem o header, usa backoff.
  - **HTTP 5xx, timeout ou erro de rede:** backoff 1s, 2s, 4s, 8s...
  - **HTTP 401 com o token do bot:** sem retry. O run falha com a mensagem "token do bot inválido ou revogado".
  - **(Fase 2) HTTP 401 com o token de uma pessoa:** sem retry. A conexão dela vira `revoked` e o sync continua com as outras pessoas.
  - **HTTP 403 ou 404 num recurso específico:** sem retry. O recurso é registrado como erro do passo e o sync segue para o próximo.
  - **Outros erros do httpx que não são de rede** (por exemplo, corpo corrompido ou redirect inesperado): sem retry, viram um erro do cliente do ClickUp. Nenhuma exceção do httpx sai do cliente.
- **Paginação de tarefas:** além de parar na página curta, o cliente tem um teto de 1000 páginas (100 mil tarefas) e detecta uma página que repete a anterior (a API estaria ignorando `page`). Nos dois casos, levanta um erro em vez de terminar em silêncio.
- **`raw`:** o mapper gera o `raw` a partir do schema com `model_dump(by_alias=True, mode="json", exclude_unset=True)`. Ele preserva os nomes e os campos extras do JSON, mas não é uma cópia exata: datas em ms já vêm como inteiros e ids como texto.

### Endpoints de leitura do ClickUp

Fonte: a referência oficial em <https://developer.clickup.com/reference>, consultada em 2026-10-13. Todos os caminhos são relativos a `https://api.clickup.com/api` e são da v2, salvo indicação em contrário.

#### Usados nas Fases 1 e 2

| Dado | Endpoint | Detalhes da documentação e como usamos |
|---|---|---|
| Usuário dono do token | `GET /v2/user` | Retorna `id`, `username`, `email`, timezone e outros dados. Com o token do bot, não é chamado: o `GET /v2/team` já valida o token (um 401 ali faz o sync falhar). Com o token OAuth, identifica a pessoa no callback |
| Workspaces e membros | `GET /v2/team` | Retorna `teams[]`, e cada item traz `id`, `name` e `members[].user`. Com o token do bot, **é a fonte das `people`**. Com o token OAuth, confirma no callback que `CLICKUP_TEAM_ID` foi autorizado. A documentação não mostra, mas o spike confirmou que `members[].user` traz `role`, `role_key` (por exemplo `owner`), `role_subtype` e `custom_role` |
| Troca do código OAuth (Fase 2) | `POST /v2/oauth/token` | A única chamada não-GET do sistema. Não altera dados do ClickUp: só obtém o token da pessoa. Envia `client_id`, `client_secret` e `code` |
| Spaces | `GET /v2/team/{team_id}/space?archived=false` | |
| Folders | `GET /v2/space/{space_id}/folder?archived=false` | Subfolders vêm na mesma lista, sem aninhamento, cada uma com `parent_folder`. O mapper monta a árvore a partir desse campo. No spike, `parent_folder` veio **ausente** numa folder sem pai (formato com pai ainda não observado). A resposta já traz as `lists` de cada folder embutidas, o que pode economizar as chamadas a `/folder/{id}/list` |
| Lists em folders | `GET /v2/folder/{folder_id}/list?archived=false` | |
| Lists fora de folders | `GET /v2/space/{space_id}/list?archived=false` | |
| Tarefas | `GET /v2/team/{team_id}/task` | Ver os detalhes logo abaixo da tabela |
| Horas (Fase 2) | `GET /v2/team/{team_id}/time_entries` | Chamado **com o token OAuth de cada pessoa**. Ver os detalhes logo abaixo da tabela |

**Tarefas (`GET /v2/team/{team_id}/task`, "Get Filtered Team Tasks"):**
- Retorna **100 tarefas por página**, com `page` começando em 0.
- A documentação não lista `last_page` neste endpoint, mas **o spike viu a chave na resposta**. Como não foi possível avaliar se ela é confiável (havia uma página só), o cliente continua parando quando uma página volta com menos de 100 tarefas.
- Por padrão, subtarefas e tarefas fechadas ficam de fora. Por isso enviamos `subtasks=true&include_closed=true`.
- Quando `CLICKUP_SPACE_IDS` está definido, enviamos também `space_ids[]` com esses spaces. Um space configurado que o token não enxerga vira erro da estrutura, e a estrutura fica sempre parcial até a variável ser corrigida.
- A listagem de tarefas faz, nos dois modos e com os mesmos filtros, as buscas abaixo, nesta ordem, unidas sem repetir ids (vale a primeira aparição, então `archived = true` prevalece): `archived` (`archived=true`); `archived_milestones` (`archived=true&custom_items[]=1`); `milestones` (`custom_items[]=1`); e `tasks` (a padrão, sem `archived`). As duas buscas de marcos são ligadas por `FETCH_MILESTONES_SEPARATELY` em `connectors/clickup/connector.py`, até ficar confirmado que as buscas sem `custom_items[]` trazem os marcos. Custo: até 3 requisições a mais por sync, normalmente páginas vazias. `Task.archived` é verdadeiro se a tarefa veio de uma busca com `archived=true` ou se o payload traz `archived: true`; o payload não desmarca. Uma tarefa desarquivada volta a `archived = false` na próxima reconciliação (no incremental, só se desarquivar alterar o `date_updated`, a confirmar). Uma tarefa arquivada entre uma busca e outra pode não vir em nenhuma e ganhar um `deleted_at` falso, corrigido no sync seguinte que a trouxer.
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
- **`archived=true` é um filtro de "só arquivadas"**, tanto aqui quanto em `GET /v2/list/{list_id}/task` (confirmado no spike: sem o parâmetro, todas as tarefas vieram com `archived: false`; com ele, só as arquivadas). **Decisão (Carlos, 2026-10-14): as tarefas arquivadas ficam disponíveis, separadas das ativas.** Por isso o sync faz, nos dois modos, uma busca extra com `archived=true` (mesmos filtros, cerca de uma página a mais), e as tarefas que vêm dela são gravadas com `archived = true`. Na reconciliação, uma tarefa vista em qualquer das buscas (padrão, arquivadas ou marcos) conta como vista; assim, arquivar não vira `deleted_at`. O comportamento com uma tarefa arquivada de verdade ainda não foi observado.
- Formatos observados no spike: datas como string numérica e `null` frequente (inclusive `due_date` e `date_done`); `priority` como objeto ou `null`, com `priority.id` em string; `status.type` com `open` e `custom` (além de `done` e `closed`, pela documentação); tarefas de lists fora de folder trazem `folder.hidden = true` (essa referência não é uma folder de verdade); e chaves como `locations` e `top_level_parent`, que por ora só vão para o `raw`.

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

**Marcos:** confirmado. Um marco é uma tarefa com `custom_item_id = 1`, enquanto `0` é uma tarefa comum. Os marcos vêm pelo mesmo endpoint de tarefas e o mapper marca `is_milestone = (custom_item_id == 1)`. **Ainda não confirmado se a busca sem `custom_items[]` traz os marcos:** o workspace de teste não tem nenhum marco (todas as tarefas vieram com `custom_item_id = 0`). Se não trouxer, enviamos `custom_items[]=0&custom_items[]=1` e mais os tipos customizados que a empresa usa.

#### Úteis em versões futuras

| Endpoint | Para quê | Observações |
|---|---|---|
| `GET /v2/team/{team_id}/custom_item` | Tipos de tarefa, para mostrar o nome do tipo (por exemplo "Bug") | Retorna `custom_items[]` com `id`, `name`, `name_plural` e `description`. Fora da Fase 1, que só precisa saber se a tarefa é marco (`custom_item_id == 1`); o `custom_item_id` de cada tarefa continua no `raw` |
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
| `GET /v2/team/{team_id}/plan` e `getworkspaceseats` | Plano do workspace (define o rate limit) e assentos | O caminho do plano foi confirmado no spike; o de assentos continua a confirmar |
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
| `Container` | space / folder / list | Árvore com `kind` (`space`, `folder` ou `list`) e `parent_id`. A UI chama de "projeto". **O `external_id` leva o nível como prefixo** (`space:123`, `folder:456`, `list:789`), porque o ClickUp não garante que ids de níveis diferentes sejam distintos. O mesmo vale para `containers.external_parent_id` e `tasks.external_container_id`. O id original continua no `raw` |
| `Person` | membro do team (`user.id`, `username`, `email`) | |
| `Task` | task | `name`, `status.status` e o tipo do status, `priority`, `start_date`, `due_date`, `date_done`, `time_estimate`, assignees, list (container), `parent` (subtarefa), `url`, `is_milestone`, `archived` (busca de origem com `archived=true` ou `archived` do payload), `date_updated`. O id da list e o id do pai ficam também como ids externos, porque o container ou a tarefa-pai podem não estar no banco (ver "Banco de dados"). Um assignee que não está nos members do team vira uma `Person` com os dados que vêm na própria tarefa (`id`, `username`, `email`) |
| `TimeEntry` (Fase 2) | time entry, buscada com o token da pessoa | `user` → person (deve ser sempre o dono do token; se vier outro, a entrada é descartada e o caso vai para o log), `task.id` → task (pode ser nulo), `start`, `end`, `duration`, `billable`, `description`. Uma duração negativa indica timer em andamento: salva com `end=null` e `is_running=true`. Se a tarefa ainda não existir no banco (por exemplo, numa list que o bot não enxerga), `task_id` fica nulo e o id original fica guardado em `external_task_id` |

## Banco de dados

Convenções para todas as tabelas sincronizadas:
- `id` é um UUID interno. A API expõe só esse id, nunca o id do ClickUp como chave.
- Guardam `source` (`'clickup'`) e `external_id`, com `UNIQUE (source, external_id)`; o upsert usa `INSERT ... ON CONFLICT`.
- `raw` (JSONB) guarda o payload original. Serve para depuração e para remapear campos sem novo sync. Só o mapper lê esse campo.
- `synced_at` registra o último sync que viu o registro. `deleted_at` faz soft delete quando o registro some na origem.

Tabelas da **Fase 1**:
- `workspaces`, `containers`, `people`
- `tasks`, mais `task_assignees` (N:N com `people`). Duas FKs aceitam nulo e têm um id externo ao lado:
  - `container_id` e `external_container_id`: a tarefa pode estar numa list que não está no banco (arquivada, ou num space fora de `CLICKUP_SPACE_IDS`). A UI mostra essas tarefas como "sem projeto";
  - `parent_id` e `external_parent_id`: a subtarefa pode chegar antes da tarefa-pai, ou o pai pode não ser visível ao bot. Ao fim de cada passo de tarefas, um único `UPDATE` preenche `parent_id` (e `container_id`) a partir dos ids externos.
- `sync_runs`: `id`, `trigger` (`scheduled` | `manual`), `status` (`pending` | `running` | `succeeded` | `partial` | `failed`), `requested_at`, `started_at`, `finished_at`, `stats` (JSONB com contadores por entidade: criados, atualizados, removidos), `error`. Um **índice único parcial** garante no máximo um run `pending` ou `running` por vez (`CREATE UNIQUE INDEX ... ON sync_runs ((true)) WHERE status IN ('pending', 'running')`)
- `sync_state`: o "watermark" de cada `(source, resource)`, por exemplo o último `date_updated` visto nas tarefas e a data da última reconciliação completa

Colunas principais (além de `id`, `source`, `external_id`, `raw`, `synced_at` e `deleted_at` nas tabelas sincronizadas):
- `workspaces`: `name`.
- `containers`: `workspace_id` (obrigatório), `parent_id` e `external_parent_id`, `kind` e `name`.
- `people`: `username` e `email`.
- `tasks`: `name`, `status`, `status_type`, `priority` (rótulo em texto), `start_date`, `due_date`, `done_at` (de `date_done`), `time_estimate_ms`, `url`, `is_milestone`, `source_updated_at` (de `date_updated`; é a coluna usada por `order_by=updated_at`), `archived` (booleano, padrão `false`), `container_id` e `external_container_id`, `parent_id` e `external_parent_id`.
- `task_assignees`: `task_id` e `person_id` (PK composta).
- `sync_runs`: `status` com padrão `pending`, `requested_at` com padrão `now()`, `stats` com padrão `{}`.
- `sync_state`: PK `(source, resource)`, `watermark`, `last_full_sync_at` e `updated_at`.

`kind`, `trigger` e `status` são texto com `CHECK`, sem enum nativo do Postgres: um valor novo exige só trocar o `CHECK`.

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

Índices principais: `tasks (due_date)`, `tasks (container_id)`, `tasks (is_milestone)`, `tasks (parent_id)` e `task_assignees (person_id)`. Na Fase 2 entram também `time_entries (person_id, start)` e `time_entries (task_id)`.

## Sincronização

### Passos de uma execução

Os passos rodam em ordem. Cada um faz commit próprio, então uma falha num passo não desfaz os anteriores.

1. **Estrutura:** workspace, members, spaces, folders e lists. Sempre completo, porque são poucas chamadas. Containers que sumiram ganham `deleted_at`.
2. **Tarefas, modo incremental:** `date_updated_gt = watermark − 5 min`. A margem cobre diferenças de relógio e atualizações concorrentes. Upsert de tudo o que vier, depois o watermark avança.
3. **Tarefas, reconciliação completa:** roda a cada `SYNC_FULL_RECONCILE_HOURS` e no primeiro sync. Busca todas as tarefas e marca com `deleted_at` as que não voltaram. Esse passo é necessário porque o modo incremental não detecta exclusões. **Quando a reconciliação roda, ela substitui o passo 2** naquele sync, para não buscar as tarefas duas vezes, e o watermark avança do mesmo jeito.

**Exclusões só com listagem completa (passos 1 e 3):** um registro só ganha `deleted_at` se a listagem daquele passo terminou sem nenhum erro. Se alguma chamada falhou (página no meio da paginação, 403/404 num space ou folder, timeout), o passo grava os upserts normalmente, **não marca nenhuma exclusão** e registra `deletions_skipped: true` em `stats`. Sem essa regra, uma falha parcial apagaria dados que continuam existindo no ClickUp. **Além disso, a reconciliação de tarefas (passo 3) só marca exclusões se a estrutura do mesmo run (passo 1) também veio completa** (decisão do Carlos, 2026-10-14): o endpoint de tarefas omite em silêncio as tarefas de spaces e folders que o token deixou de enxergar, então uma estrutura parcial pode conviver com uma listagem de tarefas que parece completa.

Como o conector informa isso (`connectors/base.py`):
- `fetch_structure()` devolve um `StructureSnapshot` (workspace, pessoas, containers em ordem de pai para filho, inclusive subfolders, e um `report`). Uma folder cujo pai não veio na resposta sai no fim, e esse pai pode não existir no banco.
- `iter_tasks(updated_since=...)` devolve lotes de tarefas; o `report` é lido no fim da iteração.
- Cada `report` traz `mode` (`full` ou `incremental`), `parts` (o estado de cada busca), `complete` (a iteração terminou, não houve erros, todas as buscas terminaram e todo descartado tem id) e `allows_deletions` (= `complete` e `full`). **Só `allows_deletions` autoriza exclusões.** Na estrutura, ele é igual a `complete`. Nas tarefas, a reconciliação exige `allows_deletions` da listagem de tarefas **e** da estrutura do mesmo run. Por segurança, o serviço também exige que o `mode` do report seja o que ele pediu: um report `full` numa busca pedida como incremental é tratado como erro do conector e não autoriza exclusões. Quando as exclusões são puladas, `stats.task_listing` grava `deletions_skipped: true` e `deletions_skipped_reason` (por exemplo "estrutura parcial", "listagem de tarefas parcial" ou "modo da listagem diferente do pedido"). `last_full_sync_at` só avança quando a reconciliação de fato pôde marcar exclusões; senão o sync seguinte refaz a reconciliação completa. Custo conhecido: se a estrutura ficar parcial de forma permanente (por exemplo, um id em `CLICKUP_SPACE_IDS` que o bot não enxerga), todo sync vira completo e termina `partial`. O watermark do incremental só avança se `report.complete`. Os ids dos lotes e os de `report.discarded_ids` (tarefas com dados inválidos) contam como vistos. `report.to_stats()` vai para `stats`.
- Exceções: `fetch_structure` levanta `ConnectorError` (inclusive `ConnectorAuthError` no 401) quando o workspace não pode ser lido, e o run termina `failed`. Na estrutura, um 403/404 ou uma resposta 200 fora do formato num recurso (a listagem de spaces, um space ou uma folder) vira erro daquele recurso, e a busca segue; um 5xx, 429 ou timeout persistente a interrompe; se a listagem de spaces falhar, há um erro só. Na iteração das tarefas, só 401 e erro de configuração saem como exceção; um erro numa busca (inclusive uma resposta sem a chave `tasks`) encerra só aquela busca e deixa a listagem parcial.
4. **(Fase 2) Horas, uma vez por conexão `active`:** roda para todas as conexões, até `SYNC_TIME_ENTRIES_CONCURRENCY` pessoas em paralelo. Para cada pessoa:
   - decifra o token e cria um cliente próprio, que tem seu próprio rate limit;
   - busca a janela `[agora − SYNC_TIME_ENTRIES_WINDOW_DAYS, agora]` em `GET /v2/team/{team_id}/time_entries`, **sem `assignee`**. Na primeira vez dessa pessoa, a janela usa `SYNC_BACKFILL_DAYS`;
   - divide a janela em blocos (por exemplo, de 7 dias), porque o endpoint não pagina;
   - faz upsert e remove da janela **as entradas daquela pessoa** que não voltaram. Reprocessar a janela captura edições e exclusões, que não têm filtro "updated since";
   - em caso de 401, marca a conexão como `revoked` e segue para a próxima pessoa.

   Pessoas sem conexão simplesmente não têm horas. A UI mostra a cobertura, por exemplo "8 de 12 pessoas conectadas".

Status final:
- `succeeded`: todos os passos passaram;
- `partial`: algum passo falhou, ou a listagem da estrutura ou das tarefas veio incompleta, mas outros dados foram gravados. Na Fase 2 isso inclui falhas nas horas de alguma pessoa; os erros de cada pessoa ficam em `stats.time_entries.errors` e em `clickup_connections.last_error`;
- `failed`: nada foi gravado, ou houve erro fatal (por exemplo, 401).

Formato de `stats`: `source`, `mode`, `structure` (o `to_stats()` da estrutura), `task_listing` (o `to_stats()` das tarefas mais `reconciled`, `watermark_advanced` e, quando for o caso, `deletions_skipped` e `deletions_skipped_reason`) e `errors`. Os contadores `updated` contam todo registro visto, mesmo sem mudança, porque o upsert sempre grava `synced_at`.

Limitação conhecida: o passo de tarefas roda numa transação só, que fica aberta enquanto espera o HTTP e o rate limit. Um `idle_in_transaction_session_timeout` no servidor derrubaria esse passo; hoje ele não é configurado.

### Worker e fila

- O worker roda em processo próprio: `scarlet-scribe-worker`.
- O **APScheduler** cria um `sync_run` com `trigger=scheduled` e `status=pending` a cada `SYNC_INTERVAL_MINUTES`. Ele não cria um run novo se já houver um `pending` ou `running`: o conflito no índice único parcial de `sync_runs` é simplesmente ignorado.
- Um loop consulta a fila a cada ~3 s e "pega" o run `pending` mais antigo com `SELECT ... FOR UPDATE SKIP LOCKED`, marcando-o como `running`.
- Um **advisory lock do Postgres** (chave fixa, de sessão, `pg_try_advisory_lock`) envolve a execução. Ele fica numa conexão própria, separada das que gravam dados, e é liberado explicitamente; se o unlock falhar, a conexão é invalidada. Isso garante um único sync por vez mesmo se, por engano, subirem dois workers.
- Sempre que obtém o advisory lock, o worker marca como `failed` ("interrompido") os runs que ficaram em `running`, que seriam sobras de um crash. Assim um worker vivo destrava a fila deixada por outro que morreu, sem esperar um restart.
- Com SIGTERM ou SIGINT, o worker interrompe o run em andamento, grava-o como `failed` ("interrompido"), libera o lock e encerra.

## API HTTP

Todas as rotas usam o prefixo `/api/v1` e respondem em JSON, com datas em ISO 8601 UTC. O OpenAPI fica em `/api/v1/openapi.json` e é dele que o cliente TypeScript do front é gerado.

**Paginação** nas listagens: `?limit=50&offset=0` (limite máximo de 200). A resposta tem o formato `{ "items": [...], "total": 123 }`. A exceção é `GET /projects`: ele devolve a árvore inteira, sem `limit`/`offset`, mas no mesmo formato `{ items, total }`.

**Erros:** formato padrão do FastAPI (`{ "detail": ... }`):
- 404 para id inexistente;
- 422 para parâmetro inválido;
- 429 no cooldown do `POST /sync`;
- 503 em qualquer rota quando o banco está inacessível (falha de conexão). Os outros erros de banco continuam 500, com traceback só no log.

404, 429 e 503 usam o schema `ErrorDetail` (`{ "detail": "..." }`). O 404 vale só para o id no caminho; ids desconhecidos em filtros devolvem lista vazia. No OpenAPI, todos os campos de resposta são obrigatórios, e o `operationId` é o nome da função da rota (`list_tasks`, `request_sync`...), para o cliente TS gerado ter nomes limpos. A documentação interativa fica em `/api/v1/docs`.
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
| `GET /health` | — | `{ status, database, latest_sync }`, com `status` e `database` em `ok` ou `error`; 503 com o mesmo corpo quando o banco não responde |
| `GET /projects` | `kind`, `parent_id` | Árvore space/folder/list, sem paginação |
| `GET /people` | `q` (busca em `username` ou `email`, sem diferenciar maiúsculas; `%` e `_` são literais), `source` (padrão `clickup`; Fase M) | Members, ordenados por `username` |
| `GET /tasks` | `container_id`, `status`, `assignee_id`, `due_from`, `due_to`, `is_milestone`, `include_closed` (padrão `false`), `archived` (padrão `false`: só as ativas; `true`: só as arquivadas), `q` (busca no nome), `order_by` (`due_date`, `updated_at` ou `name`) | Lista paginada |
| `GET /tasks/{id}` | — | Detalhe da tarefa, com assignees e subtarefas. (Fase 2) Ganha o total de horas, que soma **só as entradas sincronizadas**, ou seja, as das pessoas conectadas. Por isso vem acompanhado de `time_tracked_coverage`, que diz quantos assignees estão conectados. Enquanto a regra de visibilidade não for definida, mostra só o total, sem detalhar por pessoa |
| `GET /milestones` | `container_id`, `due_from`, `due_to` (nunca inclui arquivadas) | Atalho para `GET /tasks?is_milestone=true`, ordenado por `due_date` |
| (Fase 2) `GET /time-entries` | `task_id`, `container_id`, `from`, `to` | Lista paginada **das horas do usuário logado** |
| (Fase 2) `GET /time-entries/summary` | `from`, `to` (obrigatórios), `group_by` (`container`, `task` ou `day`), filtros iguais aos de `GET /time-entries` | Totais de horas agrupados **do usuário logado** (`[{ key, label, total_ms }]`) |

Registros com `deleted_at` preenchido nunca aparecem nas respostas (uma referência a um registro removido sai como `null`).

Detalhes do contrato de leitura (decididos na F1-08):
- **`/projects`:** sem filtros, os nós de primeiro nível com `children` aninhados; `parent_id` traz os filhos diretos daquele container, cada um com a sua subárvore; `kind` traz todos os nós daquele nível no escopo, cada um com a sua subárvore. `total` é o número de itens no primeiro nível. Um container cujo pai não está no banco vira raiz.
- **`/tasks`:** `container_id` inclui as tarefas de toda a subárvore; `status` pode ser repetido, ignora maiúsculas e valores vazios; `due_from` e `due_to` são inclusivos e aceitam instante ISO 8601 ou data pura (`AAAA-MM-DD` vale meia-noite UTC em `due_from` e o fim do dia UTC em `due_to`; instante sem fuso é UTC); `include_closed=false` exclui `status_type` `done` e `closed` (sem `status_type`, a tarefa não conta como encerrada); `archived=false` (padrão) traz só as ativas e `true` só as arquivadas. Ordem padrão `due_date` crescente com nulos no fim; `updated_at` usa `source_updated_at` decrescente; `name` ignora maiúsculas; o `id` desempata.
- **Formato da tarefa:** `container: { id, kind, name } | null`, `parent_id`, `assignees`, `archived`, `source_updated_at` e os demais campos. O detalhe acrescenta `parent: { id, name, archived } | null` e `subtasks` (filhas diretas, inclusive encerradas e arquivadas).
- **`/milestones`:** nunca traz arquivadas nem encerradas; para ver os marcos encerrados, use `/tasks?is_milestone=true&include_closed=true`.
- **`/sync/runs/latest`:** 200 com `null` quando ainda não houve run.

**(Fase 2) Visibilidade das horas:** cada pessoa vê **só as próprias horas**. Ver as horas de outras pessoas, com filtro `person_id` e `group_by=person`, depende de uma regra de permissão que ainda não foi definida, por exemplo um grupo LDAP de gestores. Ver "Riscos". Os parâmetros ficam reservados até essa decisão.

### Sincronização

| Método e rota | Comportamento |
|---|---|
| `POST /sync` | Pede um sync manual. As verificações seguem esta ordem: (1) se já houver um run `pending` ou `running`, devolve **200** com esse run, e o front só passa a acompanhá-lo; (2) senão, se o `requested_at` do último run manual foi há menos de `SYNC_MANUAL_COOLDOWN_SECONDS`, responde **429** com `Retry-After` igual aos segundos que faltam; (3) senão, cria o run e devolve **202** com ele (`pending`). Se a inserção bater no índice único parcial de `sync_runs` (dois pedidos ao mesmo tempo), devolve **200** com o run que já existe |
| `GET /sync/runs/latest` | O run mais recente (ou `null`), que o front consulta a cada ~2 s enquanto ele estiver `pending` ou `running` |
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

## Fase M: multi-integração

Decisões do Carlos (2026-10-15). A plataforma passa a reunir várias ferramentas, e o GitLab é a segunda, depois do ClickUp. **Por enquanto, os apps só ficam visíveis no painel:** cada um tem a própria área, não há cruzamento de dados e nada é escrito nas ferramentas. No futuro os apps vão se integrar, com escrita em pontos específicos; essa mudança na regra de somente leitura será decidida ponto a ponto, numa etapa própria, e atualizará este documento, o `CLAUDE.md` e os hooks. As tarefas estão em `PLANO_DE_EXECUCAO.md` › "Fase M".

### Navegação por app (front)

- Uma **barra lateral** à esquerda lista só os aplicativos, cada um com o seu ícone (SVG inline, paths do Simple Icons, licença CC0), sem os grupos de telas de cada app. O nome do app vai em `title` e `aria-label`.
- O app ativo fica destacado. As abas dele (no ClickUp: Projetos, Tarefas, Arquivadas e Marcos; no GitLab: Repositórios, Merge Requests, Issues e Commits) ficam no header, ao lado de `ApiStatus` e `SyncButton`.
- Um registro estático em `frontend/src/apps.ts` define, para cada app, `id`, `label`, `icon`, `basePath`, `nav` e `enabled`. **Desde a FM-08, o `enabled` vem de `GET /sources`.** Enquanto `/sources` carrega ou se falhar, vale o `enabled` estático, com o GitLab desabilitado. O `title` do item mostra o último sync ("nunca sincronizado" quando `null`) ou "não configurado".
- As rotas têm o prefixo do app:
  - ClickUp: `/clickup/tarefas`, `/clickup/tarefas/:id`, `/clickup/arquivadas`, `/clickup/marcos` e `/clickup/projetos`;
  - GitLab: `/gitlab/merge-requests`, `/gitlab/issues`, `/gitlab/commits` e `/gitlab/repositorios`, com `/gitlab` levando a `/gitlab/repositorios`.

  As rotas antigas redirecionam para as novas, e `/` e `/clickup` vão para `/clickup/projetos`: cada app abre na primeira aba (decisão do Carlos, 2026-10-15).
- **Telas do GitLab (FM-08):** os filtros ficam na URL, e mudar um filtro volta à página 1; a paginação é de 50 por página, exceto em Commits.
  - **Merge Requests:** filtros de repositório, estado (padrão "Abertos", sem parâmetro na URL, e "Todos" com `estado=todos`, que não manda `state`) e busca.
  - **Commits:** filtros de repositório, período e busca; seletor de 10, 25, 50 ou 100 por página (padrão 25, `por_pagina` na URL só quando diferente) e botão de copiar o sha.
  - **Issues (FM-17):** filtros de repositório, estado (padrão "Abertas", sem parâmetro na URL, e "Todas" com `estado=todas`, que não manda `state`) e busca; 50 por página; colunas `#iid`, título (link para o GitLab), estado, tipo, repositório, autor, atualizada e fechada.
  - **Repositórios:** a alternância "Mostrar só arquivados" (`archived=true`) e o link "Ver", que abre os MRs do repositório com "Todos".
- O "Sincronizar agora" continua global (as duas fontes) e, depois de um sync, recarrega também `sources`, `repositories`, `merge-requests`, `issues` e `commits`.
- Em telas estreitas, a barra lateral vira uma faixa de ícones no topo.
- **Tarefa em modal (ML-03, decisão do Carlos):** a tarefa abre só em modal (`<dialog>`), sem tela cheia, na URL `/clickup/tarefas/:id`. Os links passam `location.state` com `background` (a location da lista) e `depth`; a lista de origem continua atrás com os filtros dela, e o acesso direto ou o F5 mostram Tarefas atrás. Fechar (X, Esc, backdrop) ou o Voltar do navegador voltam à lista e devolvem o foco ao link. A preferência `taskOpenMode` (`modal`, o padrão, ou `drawer`) fica em `frontend/src/lib/preferences.ts`, sem tela de configuração até a Fase 2.

### GitLab (gitlab.com ou self-hosted)

**Decisão do Carlos (2026-10-15):** a instância é a que estiver disponível, o gitlab.com ou o self-hosted da empresa. As duas usam a mesma API (`{GITLAB_URL}/api/v4`), com o mesmo token e os mesmos endpoints, e o código não as distingue. Começar no gitlab.com e passar depois para o self-hosted segue "Troca de instância", abaixo.

- **Autenticação:** token de um usuário bot, só com o escopo **`read_api`**, enviado no header `PRIVATE-TOKEN`. No gitlab.com, uma conta bot gratuita (ou a do Carlos, só durante o desenvolvimento) com um *personal access token*; os group e project access tokens podem exigir plano pago lá **(a confirmar)**. No self-hosted, um bot com papel **Reporter** nos grupos e projetos sincronizados, com um personal, group ou project access token. Ao contrário do ClickUp, o GitLab tem escopos: o `read_api` garante a leitura pelo próprio token, além da regra de só usar GET no código.
- **Base:** `{GITLAB_URL}/api/v4`, com `GITLAB_URL` igual a `https://gitlab.com` ou à URL do self-hosted. O cliente aceita um bundle de CA próprio para certificados internos (só no self-hosted).
- **Spike (FM-03, 2026-10-15, `backend/scripts/gitlab_spike.py`):** feito no gitlab.com (versão 19.6, `enterprise=true`) com um personal access token só com `read_api`, num grupo de teste pequeno (3 projetos, 4 MRs, 1 membro). Os campos e formatos abaixo estão confirmados; volumes e paginação longa não foram exercitados.
- **Endpoints (confirmados no spike):**

  | Dado | Endpoint | Notas |
  |---|---|---|
  | Escopo do token | `GET /personal_access_tokens/self` | Traz `scopes`, `active`, `revoked` e `expires_at` |
  | Projetos de um grupo | `GET /groups/:id/projects?include_subgroups=true&with_shared=false` | **Decisões do Carlos (2026-10-15):** sem filtro de arquivados, porque os arquivados vêm com `archived=true` em vez de sumir e virar `deleted_at`; e `with_shared=false`, porque os projetos compartilhados de outros grupos só entram por `GITLAB_PROJECT_IDS`. Objeto completo, com mais de 100 campos: o mapper guarda só `id`, `name`, `path_with_namespace`, `web_url`, `default_branch` (nulo em repositório vazio), `archived`, `last_activity_at` e `avatar_url` |
  | Projeto avulso | `GET /projects/:id` | Para `GITLAB_PROJECT_IDS` |
  | Merge requests | `GET /projects/:id/merge_requests?state=all&scope=all&updated_after=...` | O `updated_after` filtra de fato. `author`, `assignees` e `reviewers` trazem `id` e `username`, **sem e-mail** (só `public_email`, muitas vezes vazio) |
  | Commits | `GET /projects/:id/repository/commits?all=true&since=...` | **Decisão do Carlos (2026-10-15): todos os branches (`all=true`)**, para mostrar também o trabalho ainda não mesclado. No projeto testado, 44 commits contra 36 só do branch padrão, com o mesmo custo. Um commit visto em vários branches vem uma vez por sha. Traz `author_name` e `author_email` |
  | Membros do grupo | `GET /groups/:id/members/all` | O `read_api` permite. Sem e-mail privado. Fora do recorte atual |
  | Issues (FM-12) | `GET /projects/:id/issues?scope=all&state=all&updated_after=...` (ordem padrão, como nos MRs) | Ver "Issues (FM-12 a FM-17)". Ao contrário dos commits, traz `X-Total` |
  | MRs que fecham uma issue (FM-12) | `GET /projects/:id/issues/:iid/closed_by` | Lista de MRs completos; 404 para `iid` inexistente. Ver "Issues (FM-12 a FM-17)" |

  Todas as datas vêm em ISO 8601 com milissegundos e `Z`, e `updated_after`/`since` aceitam o mesmo formato.
- **Paginação (confirmada):** offset com `per_page=100`, seguindo `X-Next-Page` (presente e **vazio na última página**) ou o `Link rel="next"`. Na listagem de commits, `X-Total` e `X-Total-Pages` **nunca vêm**, nem com poucos itens: o cliente não usa o total em nenhuma listagem. A keyset funciona em `/projects`, mas não é usada (ver "Compatibilidade").
- **Rate limit (confirmado no gitlab.com):** os headers vêm em toda resposta 200: `RateLimit-Limit` (2000 por minuto no gitlab.com, por usuário autenticado), `RateLimit-Remaining`, `RateLimit-Observed`, `RateLimit-Name` e `RateLimit-Reset`. **O `RateLimit-Reset` é um epoch absoluto em segundos**, não os segundos que faltam. O 429 não foi observado, então o `Retry-After` continua **(a confirmar)**. O cliente segue o padrão do ClickUp: limite preventivo `GITLAB_RATE_LIMIT_PER_MINUTE`, ajustado só para baixo pelos headers, e retries com backoff.
  - **Burst observado no spike FM-12 (2026-10-21):** `RateLimit-Limit: 100` com `RateLimit-Name: burst_traffic_per_user_free_plan`, nas rotas de issues, de `closed_by` e de MRs. O gitlab.com free aplica um limite de rajada por usuário menor que os 2000/min vistos na FM-03. **Decisão do Carlos (2026-10-21):** o padrão de `GITLAB_RATE_LIMIT_PER_MINUTE` passa a ser **100**; no self-hosted, aumentar pela variável.
- **Variáveis (FM-05):** `GITLAB_URL`, `GITLAB_API_TOKEN`, `GITLAB_GROUP_IDS`, `GITLAB_PROJECT_IDS`, `GITLAB_CA_BUNDLE` (opcional) e `GITLAB_RATE_LIMIT_PER_MINUTE`. Cada fonte é opcional: sem as variáveis do GitLab, o sync e a API seguem só com o ClickUp.
- **Compatibilidade entre instâncias:** o gitlab.com roda sempre a versão mais nova, e o self-hosted pode ser mais antigo. Por isso:
  - o conector segue o caminho mais compatível: paginação por offset com `X-Next-Page`/`Link`, sem depender de keyset nem de `X-Total`. Recurso que dependa de versão só entra com checagem da versão (`GET /version`);
  - o rate limit vem dos headers `RateLimit-*` e do 429, porque ele é fixo no gitlab.com e configurável no self-hosted. O único valor no código é o limite preventivo `GITLAB_RATE_LIMIT_PER_MINUTE`;
  - `GITLAB_CA_BUNDLE` é opcional e ignorado quando vazio.
- **Troca de instância (FM-11):** os ids do gitlab.com não têm relação com os do self-hosted, e as duas instâncias não convivem no mesmo banco (a instância não entra no `external_id`). A troca é:
  1. trocar `GITLAB_URL`, `GITLAB_API_TOKEN` e os ids de grupos e projetos no `.env`;
  2. refazer o spike (FM-03) contra a instância nova e corrigir este documento se algo divergir (versão, paginação, rate limit);
  3. apagar os dados do GitLab no banco (`commits`, `merge_requests`, `repositories`, as `people` com `source = 'gitlab'` e os `sync_state` com `resource` começando em `gitlab:`) com um script dedicado em `backend/scripts/`, que só toca nessas linhas;
  4. rodar um sync e conferir no navegador.
- **Código (FM-05):** `connectors/gitlab/` com `client.py`, `schemas.py`, `mapper.py` e `connector.py`, como no ClickUp. O protocolo `Connector` tem o formato do ClickUp (estrutura e tarefas), então as fontes de código têm um protocolo canônico próprio em `connectors/base.py`:
  - `CodeConnector`: `source`, `async with`, `fetch_repositories() -> RepositorySnapshot`, `iter_merge_requests(repository_id, *, updated_since=None) -> BatchListing[MergeRequest]` e `iter_commits(repository_id, *, since=None) -> BatchListing[Commit]`. O `repository_id` é o `Repository.external_id`;
  - `RepositorySnapshot` (repositórios e um `ListingReport` sempre `full`) e `BatchListing[T]` (lotes num `async for` de uma vez só, com o `report` lido no fim, como no `TaskListing`);
  - `create_code_connector(settings)` em `factory.py`, que levanta `ConnectorConfigError` se `gitlab_enabled` for falso. O `create_connector` do ClickUp não mudou.
  - Com `since`/`updated_since` nulo, a listagem é `full` e completa e pode autorizar exclusões naquele repositório; com data, é incremental e nunca autoriza. Erros por recurso (403/404, 5xx persistente, paginação que não termina) vão para `report.errors`; só `ConnectorAuthError` (401) e `ConnectorConfigError` saem como exceção. Falha de TLS não tem retry.
  - O `raw` guarda só os campos usados: 8 no projeto, 16 no MR (`author`, `assignees` e `reviewers` só com `id`, `username` e `public_email`) e 8 no commit.
  - `backend/scripts/gitlab_amostra_canonica.py` mostra os dados no formato canônico, sem token nem e-mails.

### Banco (migration `0003`)

Mesmas convenções das tabelas sincronizadas (`id` UUID, `source = 'gitlab'`, `external_id`, `raw`, `synced_at`, `deleted_at`, `UNIQUE (source, external_id)`). O `raw` guarda o payload já reduzido pelo mapper (os projetos têm mais de 100 campos).
- `repositories`: `external_id` = id do projeto; `name`, `path_with_namespace`, `web_url`, `default_branch` (aceita nulo), `archived` (padrão `false`) e `last_activity_at`.
- `merge_requests`:
  - `external_id` = `id` global do MR; `repository_id` (FK obrigatória) e `iid` (inteiro), únicos por `(repository_id, iid)`;
  - `title`, `state` (texto com `CHECK`: `opened`, `closed`, `merged` e `locked`), `draft` (booleano), `source_branch`, `target_branch` e `web_url`;
  - `author_id` (FK para `people`, aceita nulo) e `external_author_id`, no padrão das tarefas;
  - `created_at_source`, `merged_at`, `closed_at` e `source_updated_at` (de `updated_at`).
- `commits`:
  - `external_id` = `<id do projeto>:<sha>`, porque o mesmo sha pode existir em projetos diferentes (forks); `repository_id` (FK obrigatória) e `sha`, únicos por `(repository_id, sha)`;
  - `short_sha`, `title`, `author_name`, `author_email`, `authored_at`, `committed_at` e `web_url`;
  - o autor do commit é a identidade do git (nome e e-mail), sem FK para `people`.
- **Pessoas:** os autores dos MRs entram em `people` com `source = 'gitlab'` e `external_id` = id do usuário no GitLab (`username`; `email` só se vier `public_email`). Não se fundem com as pessoas do ClickUp por enquanto.
- **Fora do recorte (decisão do Carlos, 2026-10-15):** assignees e reviewers dos MRs ficam só no `raw`. Ganham tabelas próprias quando for preciso filtrar por eles.
- **Índices:** `merge_requests (repository_id)`, `merge_requests (source_updated_at)`, `merge_requests (author_id)` e `commits (repository_id, authored_at)`.
- **Watermarks:** em `sync_state`, com `resource` = `gitlab:merge_requests:<id do projeto>` e `gitlab:commits:<id do projeto>`.

### Sync

O `SyncService` (FM-06) roda no mesmo run, sob o mesmo advisory lock, os passos do ClickUp e depois os do GitLab. O worker não mudou, e o `POST /sync` cobre as duas fontes.

**Fontes e desfecho do run:**
- uma fonte **não configurada é pulada**: o ClickUp sem token ou team, e o GitLab com `gitlab_enabled` falso. A fonte pulada fica fora do desfecho e aparece em `stats` como `{source, skipped: true, reason: "não configurado"}`. Decisão do Carlos (2026-10-15) para o ClickUp;
- uma falha numa fonte (inclusive 401) deixa o run `partial` e não desfaz o que a outra gravou. O run termina `failed` só se todas as fontes que rodaram falharem, ou se nenhuma estiver configurada (`error` = "nenhuma fonte configurada");
- com o GitLab ativo, o `error` de um run `partial` ou `failed` leva o prefixo da fonte (`clickup: ...`, `gitlab: ...`). Com só o ClickUp, o `error` e o `stats` saem como antes.

**`stats`:** os campos do ClickUp continuam no nível de cima. A chave `stats.gitlab` tem:
- os contadores `repositories`, `merge_requests`, `commits` e `people`;
- `repository_listing`, mais `merge_request_listings` e `commit_listings` por id do repositório (`to_stats()` com `reconciled`, `watermark_advanced` e, nos commits, `since` e `initial_window`);
- `skipped_repositories`, `unavailable`, `errors`, `status` e `error`.

Com o ClickUp pulado, `source`, `skipped` e `reason` ficam no nível de cima. O `SyncButton` ainda não mostra os contadores do GitLab.

**Passos do GitLab:**
1. **Repositórios:** sempre completos; upsert por `(source, external_id)`; `deleted_at` só com `report.allows_deletions`. Os arquivados vêm com `archived=true` e nunca ganham `deleted_at`.
2. **Merge requests, por repositório não arquivado:**
   - watermark `gitlab:merge_requests:<id do projeto>` = maior `source_updated_at`, com margem de 5 min;
   - na primeira vez e a cada `SYNC_FULL_RECONCILE_HOURS`, uma listagem `full` do repositório que marca `deleted_at` nos MRs que não voltaram, só com `allows_deletions` daquela listagem, sem a condição da estrutura que vale para as tarefas. Num repositório sem nenhum MR, o incremental usa `last_full_sync_at − 5 min` como base;
   - autores em `people` (`source='gitlab'`, upsert com `DO UPDATE`) e `author_id` pelo `external_author_id`.
3. **Commits, por repositório não arquivado e com `default_branch`:**
   - todos os branches (`all=true`);
   - watermark `gitlab:commits:<id do projeto>` = maior `committed_at` (o `since` do GitLab filtra pela data do committer), com margem de 5 min;
   - na primeira vez, uma janela de 365 dias (a constante `INITIAL_COMMITS_WINDOW`);
   - commits nunca ganham `deleted_at`, e um sha repetido só atualiza.

**Regras comuns aos passos:**
- os watermarks só avançam com `report.complete` e **nunca passam do instante em que a listagem começou**: uma data no futuro (relógio errado do committer) não congela o repositório. Esse caso é sinalizado com `future_dated_commits` ou `future_dated_merge_requests` e um `warning`;
- **"recurso indisponível":** um 403/404 na listagem de MRs, de commits ou de tags de um repositório, sem nada recebido, conta em `stats.gitlab.unavailable` e é logado em `warning`. Ele não deixa o run `partial` e não avança o watermark. É o caso de MRs desativados ou de repositório vazio. Qualquer outro erro deixa o run `partial`.

**Limitações conhecidas:**
- **Commits empurrados tarde se perdem** (decisão do Carlos, 2026-10-15: aceito por ora). O watermark é o maior `committed_at` entre todos os branches. Um commit feito localmente antes do watermark e enviado depois nunca entra; basta outra pessoa ter feito push no meio. Correções possíveis: rebuscar uma janela de alguns dias a cada run ou periodicamente, ou usar os eventos de push (exige spike).
- Como nas tarefas, cada listagem por repositório roda numa transação aberta durante o HTTP.
- `stats.gitlab` cresce cerca de 1 KB por repositório e é regravado a cada repositório. Antes da FM-11 (self-hosted com muitos repositórios), guardar o detalhe só dos repositórios com problema.

### API

| Método e rota | Filtros (query) | Retorno |
|---|---|---|
| `GET /sources` | — | Os 2 apps, sempre nesta ordem: `clickup` e `gitlab`, sem paginação. Alimenta a barra lateral |
| `GET /repositories` | `q` (em `name` ou `path_with_namespace`), `archived` (padrão `false`: só os ativos; `true`: só os arquivados) | Lista paginada, ordenada por `path_with_namespace` sem diferenciar maiúsculas |
| `GET /merge-requests` | `repository_id`, `state` (repetível), `author_id`, `q` (no título), `updated_from` | Lista paginada, por `source_updated_at` decrescente |
| `GET /commits` | `repository_id`, `from`, `to` (sobre `authored_at`), `q` (no título) | Lista paginada, por `authored_at` decrescente |
| `GET /issues` (FM-16) | `repository_id`, `state` (repetível), `author_id`, `q` (no título) | Lista paginada, por `source_updated_at` decrescente; nunca traz as confidenciais. Ver "Issues (FM-12 a FM-17)" |

Seguem as convenções de "API HTTP": prefixo `/api/v1`, `{ items, total }`, `limit`/`offset`, `deleted_at` filtrado, `raw` nunca sai e operationId = nome da função (`list_sources`, `list_repositories`, `list_merge_requests`, `list_commits`, `list_issues`). Detalhes do contrato (decididos na FM-07):
- **`/sources`:** cada item tem `id`, `name` ("ClickUp" ou "GitLab"), `enabled` e `last_synced_at`.
  - `enabled` vale, no ClickUp, quando token e team estão configurados; no GitLab, quando `gitlab_enabled` é verdadeiro.
  - `last_synced_at` é o maior `synced_at` das linhas da fonte (ClickUp: `tasks`; GitLab: `repositories`), contando também as removidas, ou `null`. É "quando os dados daquela fonte foram vistos pela última vez", não o horário do último run: se o passo da fonte falhar, o valor fica parado.
- **`/merge-requests`:**
  - `state` aceita `opened`, `closed`, `merged` e `locked`; um valor vazio ou inválido dá 422 (diferente de `status` em `/tasks`, que ignora vazios);
  - `author_id` só considera pessoas não removidas; `updated_from` segue a regra de datas de `due_from`;
  - o item traz `id`, `iid`, `title`, `state`, `draft`, `source_branch`, `target_branch`, `web_url`, `created_at_source`, `merged_at`, `closed_at`, `source_updated_at`, `repository: { id, name, path_with_namespace }` e `author: { id, username } | null` (`null` também quando a pessoa foi removida);
  - nulos de `source_updated_at` vão para o fim, e o `id` desempata.
- **`/commits`:**
  - `from` e `to` são inclusivos, com a mesma regra de `due_from`/`due_to` (uma data pura em `to` inclui o dia inteiro);
  - o item traz `id`, `sha`, `short_sha`, `title`, `author_name`, `authored_at`, `committed_at`, `web_url` e `repository: { id, name, path_with_namespace }`;
  - **`author_email` não sai na API** (dado pessoal fora do recorte da tela);
  - nulos de `authored_at` vão para o fim, e o `id` desempata.
- MRs e commits de um repositório removido não aparecem.
- **`/people` ganha `source`** (padrão `clickup`), para que os autores do GitLab não apareçam nas telas do ClickUp. `?source=gitlab` lista só os do GitLab.

### Tags e ícones dos repositórios (Melhorias, rodada 1)

Spike ML-01 (2026-10-15, `backend/scripts/gitlab_spike.py --tags-avatar`, gitlab.com, 3 projetos privados):
- **Tags:** `GET /projects/:id/repository/tags` responde 200 com `read_api` e pagina como as outras listagens (`X-Next-Page` vazio na última página). Cada tag traz `name`, `message`, `target`, `protected`, `created_at` (UTC), `release` e `commit` (objeto completo do commit). Nas tags anotadas, `target` é o sha do **objeto tag**, diferente de `commit.id`: a ligação com o commit usa sempre `commit.id`. Tags leves não foram vistas **(a confirmar)**.
- **Ícone:** `avatar_url` vem nos dois endpoints de projeto, `null` sem ícone, ou uma URL absoluta `{GITLAB_URL}/uploads/-/system/project/avatar/<id>/<arquivo>`. **Em projeto privado, o GET sem token dá 401**: um `<img>` direto no navegador não funciona.

Decisões do Carlos (2026-10-15):
- **Ícones baixados no sync.** O worker baixa a imagem com o token do bot e grava os bytes no banco; a API serve do banco, sem chamar o GitLab.
  - **Download (ML-05):** o GET direto no `avatar_url` (`/uploads/...`) dá 401 mesmo com o token, então o conector baixa por `GET /projects/:id/avatar`, que responde `application/octet-stream`; o tipo gravado vem da assinatura dos bytes. O `avatar_url` só é aceito no mesmo esquema, host e porta de `GITLAB_URL`, sem credenciais, e nada é pedido fora disso; redirects não são seguidos.
  - O conector aceita só `image/png`, `image/jpeg`, `image/gif`, `image/webp`, `image/bmp`, `image/x-icon` e `image/vnd.microsoft.icon` (SVG fica de fora) e até 512 KB. Fora disso, o ícone é ignorado com `warning`.
  - O sync só baixa de novo quando o `avatar_url` muda; com `avatar_url` nulo, apaga o ícone guardado. Uma falha ao baixar não deixa o run `partial`: conta em `stats.gitlab.avatar_errors` e o repositório fica sem ícone.
  - Banco: `repositories.avatar_url` (texto, nulo) e a tabela `repository_avatars` (`repository_id` PK e FK com `ON DELETE CASCADE`, `source_url`, `content_type`, `data` bytea, `fetched_at`).
  - API: o item de `GET /repositories` ganha `avatar_updated_at` (o `fetched_at`, ou `null` sem ícone; o `avatar_url` do GitLab não sai). `GET /repositories/{id}/avatar` devolve os bytes com o `content_type` guardado, `X-Content-Type-Options: nosniff` e `Cache-Control: private, max-age=86400`, ou 404. O front usa `/api/v1/repositories/{id}/avatar?v=<avatar_updated_at>` e, sem ícone ou se a imagem falhar, mostra um quadrado com a inicial.
- **Tags dos commits.** Tabela `repository_tags` com as convenções das sincronizadas: `external_id` = `<id do projeto>:<nome>`, `repository_id` (FK), `name` e `commit_sha`, `UNIQUE (repository_id, name)` e índice em `(repository_id, commit_sha)`, sem FK para `commits` (o commit pode estar fora da janela de 365 dias).
  - Sync (passo G5, depois dos commits): em cada repositório não arquivado e com `default_branch`, uma listagem completa a cada run (sem watermark); upsert por `(source, external_id)` (a tag que volta perde o `deleted_at`) e `deleted_at` nas que não voltaram, só com `allows_deletions`. Um 403/404 sem nada recebido é "recurso indisponível" (`stats.gitlab.unavailable.tags`). `stats.gitlab` ganha `tags` (`created`, `updated`, `deleted`) e `tag_listings` por repositório.
- **Passo de ícones no sync (G4, ML-06):** roda logo depois dos repositórios, em todos os que vieram na listagem, inclusive os arquivados. Baixa (fora de transação, gravando numa transação curta) só quando o `avatar_url` difere do `source_url` guardado ou não há ícone guardado, então um ícone recusado é tentado de novo a cada run. Se o `avatar_url` mudou e o download falhou, o ícone antigo é apagado. `AvatarUnavailable` conta em `stats.gitlab.avatar_errors` (`{count, details: [{repository, reason}]}`) sem deixar o run `partial`; 401 encerra a fonte, como nos outros passos. `stats.gitlab.avatars` = `{downloaded, removed, unchanged}`. Sync real conferido em 2026-10-20: 7 tags e 1 ícone no primeiro run, e o segundo sem duplicar nem baixar de novo.
  - API: o item de `GET /commits` ganha `tags: string[]` (tags não removidas do mesmo `(repository_id, sha)`, por nome), numa subconsulta agregada, sem N+1.

### Issues (FM-12 a FM-17)

Extensão da Fase M, somente leitura, com o token `read_api` do bot. Pré-requisito da Fase I (`PLANO_DE_EXECUCAO.md` › "Issues do GitLab").

**Spike FM-12 (2026-10-21, `backend/scripts/gitlab_spike.py --issues`, gitlab.com).** O grupo de teste não tinha nenhuma issue, então os formatos vieram de um projeto público do gitlab.com (lido só com GET e o mesmo token). Os itens marcados **(a confirmar)** serão refeitos no grupo de teste, depois que o Carlos criar os casos à mão.
- **`GET /projects/:id/issues?scope=all&state=all`:**
  - `id` é global e `iid` é por projeto; `project_id` bate com o projeto;
  - `state` vale `opened` ou `closed`; vêm `issue_type` (`issue`) e `type` (`ISSUE`, em maiúsculas);
  - `labels` é uma lista de strings (nomes);
  - `author`, `assignees[]` e o `assignee` singular trazem `id`, `username`, `name`, `state`, `public_email` e outros, **sem `email`**;
  - **o `closed_by` da issue é um usuário, não um MR.** Os MRs vêm de `/issues/:iid/closed_by`;
  - também vêm `confidential` (booleano), `merge_requests_count`, `references` (`short`, `relative`, `full`), `web_url`, `milestone`, `due_date` e `description`. O formato do caminho de `web_url` varia entre projetos: não depender dele;
  - datas em ISO 8601 UTC com milissegundos e `Z`;
  - paginação por offset com `X-Next-Page`, vazio na última página. **`X-Total` vem**, mas o cliente não depende dele, como nas outras listagens;
  - `order_by=updated_at&sort=asc` é aceito, mas **não é usado**: com paginação por offset, uma issue atualizada durante a listagem vai para o fim e desloca as seguintes, e uma delas seria pulada sem erro (achado do Revisor na FM-14). A listagem usa a ordem padrão (`created_at` decrescente), em que uma atualização não move o item, como nos MRs.
- **`updated_after` filtra de fato** e é inclusivo (`>=`). Somado ao `updated_before`, dá o total. É o filtro do incremental, como nos MRs.
- **Confidenciais (a confirmar):** nenhuma observada. `?confidential=true` responde 200. O que o bot enxerga deve depender do papel dele no projeto.
- **`GET /projects/:id/issues/:iid/closed_by`:** 200 com uma lista de MRs completos (os mesmos campos de `/merge_requests`). Issue aberta ou fechada à mão: lista vazia. Issue fechada com MR: o MR aparece, mas pode estar `closed` sem `merged_at`. **A presença na lista não prova o fechamento por MR.** O caso de um MR ainda aberto com `Closes #N` não foi observado **(a confirmar)**. `iid` inexistente: 404.
- **Issues desativadas (a confirmar):** não observado. Os projetos trazem `issues_enabled` e `issues_access_level`, mas o `Repository` canônico não guarda esses campos: por ora, uma listagem de issues com 403/404 é tratada como "recurso indisponível", como nos MRs. Usar `issues_enabled` para pular a chamada fica como melhoria futura. Projeto inexistente: 404.
- **Rate limit:** os mesmos headers dos MRs, com o burst de 100 (ver "Rate limit" acima). O `closed_by` custa uma chamada por issue, então só é consultado quando necessário (FI-06).

**Critério de "fechada por MR" (decisão do Carlos, 2026-10-21, para a FI-06):** a issue tem `state == closed` **e** o `closed_by` dela traz pelo menos um MR com `state == merged`. Qualquer outro caso (lista vazia, só MRs fechados sem mesclar ou abertos) não gera comentário no ClickUp.

**Tabela `issues` (FM-13), esboço:** mesmas convenções das sincronizadas (`id` UUID, `source = 'gitlab'`, `external_id` = `id` global da issue, `raw`, `synced_at`, `deleted_at`, `UNIQUE (source, external_id)`).
- `repository_id` (FK obrigatória) e `iid` (inteiro), únicos por `(repository_id, iid)`;
- `title`, `state` (texto com `CHECK`: `opened` e `closed`), `confidential` (booleano, padrão `false`), `issue_type` (texto, aceita nulo) e `web_url`;
- `author_id` (FK para `people`, aceita nulo) e `external_author_id`, no padrão dos MRs; o autor entra em `people` com `source = 'gitlab'`;
- `created_at_source`, `closed_at` e `source_updated_at` (de `updated_at`);
- labels, assignees e o `closed_by` (usuário) ficam só no `raw`, que o mapper reduz aos campos usados; a `description` não entra no `raw`;
- índices: `issues (source_updated_at)` e `issues (author_id)`; o `(repository_id, iid)` único já cobre `repository_id`;
- watermark em `sync_state` com `resource` = `gitlab:issues:<id do projeto>`.
- Os MRs que fecharam a issue não ganham tabela na FM-13: a FI-06 consulta o `closed_by` quando precisar.
- Ao contrário de `merge_requests`, não há índice só em `repository_id`: o `UNIQUE (repository_id, iid)` cobre.

**Issues confidenciais (decisão do Carlos, 2026-10-21):** são sincronizadas e gravadas com `confidential = true`, mas **ficam fora da API** (nem o título, nem um indicador) até a Fase 2, porque na Fase 1 a API não tem login. A Fase 2 decide quem pode vê-las.

**Conector (FM-14):** `CodeConnector.iter_issues(repository_id, *, updated_since=None) -> BatchListing[Issue]`, com as mesmas regras de `iter_merge_requests` (`full` e completa sem data, incremental com data; erros por recurso em `report.errors`; só 401 e erro de configuração saem como exceção), e uma consulta dos MRs que fecharam uma issue (`/issues/:iid/closed_by`), que devolve `MergeRequest` canônicos (`fetch_issue_closed_by(repository_id, iid)`, sem filtrar por estado; um MR fora do formato levanta erro em vez de ser descartado, para não esconder um `merged`). Um 403/404 nessa consulta levanta `ConnectorResourceError` (em `connectors/base.py`, subclasse de `ConnectorError`), para que a FI-06 o distinga de outros erros sem importar tipos do GitLab. O `raw` da issue fica reduzido aos campos usados, sem `description`. A listagem usa a ordem padrão do GitLab (ver o spike acima).

**Sync (FM-15):** passo de issues por repositório não arquivado, depois dos MRs, no mesmo modelo dos MRs: watermark `gitlab:issues:<id do projeto>` = maior `source_updated_at` com margem de 5 min, listagem `full` na primeira vez e a cada `SYNC_FULL_RECONCILE_HOURS` (exclusões só com `allows_deletions`), autores em `people` com `source = 'gitlab'`, e 403/404 sem nada recebido como "recurso indisponível". `stats.gitlab` ganha `issues` (contadores) e `issue_listings` por repositório. O sync **não** consulta o `closed_by` (isso é da FI-06).

**API (FM-16):** `GET /issues`, com os filtros `repository_id`, `state` (repetível, `opened` ou `closed`, 422 para vazio ou inválido, como nos MRs), `author_id` e `q` (no título). Lista paginada por `source_updated_at` decrescente, com nulos no fim e o `id` desempatando. Nunca traz `confidential = true` nem issues de repositório removido. O item traz `id`, `iid`, `title`, `state`, `issue_type`, `web_url`, `created_at_source`, `closed_at`, `source_updated_at`, `repository: { id, name, path_with_namespace }` e `author: { id, username } | null`. operationId `list_issues`.

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
2. **Spike (F1-04), feito em 2026-10-14 com o token do `.env`:**
   - **Resolvido:** os headers `X-RateLimit-*` vêm nas respostas 200 e o `Reset` é em segundos; o plano sai de `GET /v2/team/{team_id}/plan`; `archived=true` traz só as arquivadas; nenhuma colisão de ids entre níveis na amostra (o prefixo de nível continua); `members[].user.role` existe.
   - **Pendente:** se a busca padrão traz os marcos e se a busca `archived=true` sem `custom_items[]` traz marcos arquivados; se arquivar ou desarquivar altera o `date_updated`. O workspace testado não tem tarefa arquivada nem marco.
   - **Ambiente de teste (decisão do Carlos, 2026-10-14):** o workspace usado no desenvolvimento é só de teste (Free Forever, um único membro, token de um usuário **Owner**). Isso é aceito durante o desenvolvimento. **Pré-requisito antes de qualquer uso real:** um usuário bot com papel Member ou Guest no workspace da empresa, sem acesso a horas de outras pessoas, e a confirmação do plano (rate limit) desse workspace.
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
- **Fase M:** barra lateral de apps (junto com a F1-11), depois o GitLab: spike, banco, conector, sync, API e telas.
- **Fase 2 (à parte):** LDAP, OAuth, horas e as telas correspondentes. Começa só depois que a Fase 1 estiver validada e que os itens 5 a 7 dos riscos estiverem resolvidos.
