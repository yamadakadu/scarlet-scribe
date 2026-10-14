# Frontend do scarlet-scribe

Vite + React + TypeScript, com TanStack Query e React Router.

## Comandos (dentro de `frontend/`)

```bash
npm install          # instala as dependências (package-lock.json versionado)
npm run dev          # servidor de desenvolvimento em http://localhost:5173
npm run build        # checagem de tipos (tsc -b) e build de produção em dist/
npm run preview      # serve o build de dist/
npm run typecheck    # tsc --noEmit
npm run lint         # oxlint
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
