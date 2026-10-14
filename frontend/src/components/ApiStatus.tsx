import { useQuery } from '@tanstack/react-query'
import { fetchHealth } from '../api/health.ts'

export function ApiStatus() {
  const { isPending, isError, isFetching, refetch } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    retry: false,
    refetchInterval: 30_000,
  })

  if (isPending) {
    return (
      <span className="api-status api-status--checking" role="status">
        Verificando a API…
      </span>
    )
  }

  if (isError) {
    return (
      <span className="api-status api-status--down" role="status">
        API indisponível
        <button
          type="button"
          className="link-button"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          {isFetching ? 'tentando…' : 'tentar de novo'}
        </button>
      </span>
    )
  }

  return (
    <span className="api-status api-status--up" role="status">
      API disponível
    </span>
  )
}
