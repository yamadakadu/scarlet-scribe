import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

const DEFAULT_API_PROXY_TARGET = 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // O loadEnv lê os arquivos .env* de frontend/ e também o process.env, que
  // tem prioridade. Assim, VITE_API_PROXY_TARGET pode vir do ambiente do
  // container (F1-12: http://api:8000) ou da linha de comando.
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || DEFAULT_API_PROXY_TARGET

  return {
    plugins: [react()],
    server: {
      // Aceita conexões de fora do container (escuta em 0.0.0.0).
      host: true,
      port: 5173,
      strictPort: true,
      // Front e API na mesma origem: sem CORS. Na Fase 2, o cookie de sessão
      // e o callback do OAuth também passam por aqui.
      proxy: {
        '/api': { target: apiProxyTarget },
      },
    },
    // O `vite preview` herda host e proxy de `server`.
  }
})
