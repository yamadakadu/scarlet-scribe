import { createContext, useContext, useMemo } from 'react'
import { useSearchParams } from 'react-router'

/**
 * Quando a tarefa abre em modal, a lista de fundo lê os filtros da location de
 * fundo (e não da URL atual, que é a da tarefa). Esse contexto leva o `search`.
 */
export const BackgroundSearchContext = createContext<string | null>(null)

/** Parâmetros da URL com um setter que volta à primeira página ao mudar um filtro. */
export function useUrlFilters() {
  const [realParams, setParams] = useSearchParams()
  const backgroundSearch = useContext(BackgroundSearchContext)
  const params = useMemo(
    () => (backgroundSearch === null ? realParams : new URLSearchParams(backgroundSearch)),
    [backgroundSearch, realParams],
  )
  const set = (key: string, value: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value) next.set(key, value)
        else next.delete(key)
        if (key !== 'pagina') next.delete('pagina')
        return next
      },
      { replace: true },
    )
  const clear = () => setParams({}, { replace: true })
  return { params, set, clear }
}
