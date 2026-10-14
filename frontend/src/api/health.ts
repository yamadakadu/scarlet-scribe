// Chamada provisória a GET /api/v1/health. Na F1-09b, as chamadas passam a
// usar o cliente TypeScript gerado do OpenAPI do backend.

export const HEALTH_URL = '/api/v1/health'

export async function fetchHealth(): Promise<unknown> {
  const response = await fetch(HEALTH_URL, {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    throw new Error(`GET ${HEALTH_URL} respondeu ${response.status}`)
  }
  return response.json()
}
