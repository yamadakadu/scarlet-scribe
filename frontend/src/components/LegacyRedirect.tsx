import { Navigate, useLocation, useParams } from 'react-router'

// Rotas antigas (sem prefixo): preservam o :id e a query string.
export function LegacyRedirect({ to }: { to: (id: string) => string }) {
  const { id = '' } = useParams()
  const { search } = useLocation()
  return <Navigate to={`${to(id)}${search}`} replace />
}
