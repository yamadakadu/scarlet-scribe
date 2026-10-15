import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap, type SyncRun } from './client.ts'

export const isActive = (run: SyncRun | null | undefined) =>
  run?.status === 'pending' || run?.status === 'running'

const LATEST_KEY = ['sync', 'latest']

/** Run mais recente. Consulta a cada 2 s enquanto ele está pending/running. */
export function useLatestSyncRun() {
  return useQuery({
    queryKey: LATEST_KEY,
    queryFn: async () => unwrap(await api.GET('/api/v1/sync/runs/latest')),
    refetchInterval: (query) => (isActive(query.state.data) ? 2_000 : 30_000),
  })
}

/** POST /sync: 202 (criou) e 200 (já havia um run) devolvem o run; 429 vira ApiError com retryAfter. */
export function useRequestSync() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async () => unwrap(await api.POST('/api/v1/sync')),
    onSuccess: (run) => client.setQueryData(LATEST_KEY, run),
  })
}
