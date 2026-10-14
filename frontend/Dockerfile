# Imagem de desenvolvimento do frontend, usada pelo serviço frontend do
# docker-compose.yml: servidor do Vite com HMR, código montado por bind mount.
# Contexto de build: raiz do repositório (ver .dockerignore na raiz).
#
# Node 24 (LTS). Os pacotes do lockfile exigem Node ^20.19 || >=22.12 (Vite 8,
# Rolldown, plugin-react) e >=22.22 (react-router 8).
FROM node:24-slim

# Roda como o usuário node (uid 1000), e não como root, para que o que o
# container escrever no bind mount não fique com dono root no host.
WORKDIR /app
RUN chown node:node /app
USER node

# Dependências primeiro, para aproveitar o cache das camadas. O node_modules
# fica na imagem e é copiado para o volume anônimo /app/node_modules no
# primeiro start (ver docker-compose.yml).
COPY --chown=node:node frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/home/node/.npm,uid=1000,gid=1000 \
    npm ci

COPY --chown=node:node frontend/ ./

EXPOSE 5173

CMD ["npm", "run", "dev"]
