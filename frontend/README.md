# Frontend do scarlet-scribe

Vite + React + TypeScript, com TanStack Query e React Router.

## Comandos (dentro de `frontend/`)

```bash
npm ci               # instala exatamente o que está no package-lock.json
npm install          # instala ou atualiza dependências (atualiza o lockfile)
npm run dev          # servidor de desenvolvimento em http://localhost:5173
npm run build        # checagem de tipos (tsc -b) e build de produção em dist/
npm run preview      # serve o build de dist/
npm run typecheck    # tsc --noEmit -p tsconfig.app.json && tsc --noEmit -p tsconfig.node.json
npm run lint         # oxlint
npm run gen:api      # regenera src/api/schema.gen.ts a partir do OpenAPI da API
```

## Proxy da API

Em desenvolvimento, o Vite encaminha `/api` para o backend, então front e API
ficam na mesma origem e não há CORS. O destino vem de `VITE_API_PROXY_TARGET`
(padrão `http://localhost:8000`):

```bash
VITE_API_PROXY_TARGET=http://localhost:9000 npm run dev
```

Dentro do Docker Compose, o serviço do front usa `http://api:8000`. O servidor
escuta em todas as interfaces (`server.host: true`) para aceitar conexões de
fora do container.

## Cliente da API

`src/api/schema.gen.ts` é gerado do OpenAPI (`/api/v1/openapi.json`) com o
`openapi-typescript` e fica versionado, então o build não precisa do backend.
Os tipos são usados pelo `openapi-fetch` em `src/api/client.ts`. Com a API no ar,
rode `npm run gen:api` depois de qualquer mudança no contrato; para outro
endereço: `OPENAPI_URL=http://localhost:8003/api/v1/openapi.json npm run gen:api`.
O `openapi-typescript` roda via `npx` (versão fixada no script), porque o peer
dependency dele ainda não aceita o TypeScript 6.

## Filtros e datas

Os filtros da lista de tarefas ficam na query string (`/tarefas?status=...&de=2026-10-14`),
então a URL é um link compartilhável. Os filtros de data são dias do calendário
local: o front converte o dia para o intervalo de instantes no fuso do navegador
antes de chamar a API (`src/lib/dates.ts`).
