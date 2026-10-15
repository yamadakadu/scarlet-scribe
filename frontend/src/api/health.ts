import { api, unwrap } from './client.ts'

export async function fetchHealth() {
  return unwrap(await api.GET('/api/v1/health'))
}
