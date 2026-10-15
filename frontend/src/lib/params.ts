import { useSearchParams } from 'react-router'

/** Parâmetros da URL com um setter que volta à primeira página ao mudar um filtro. */
export function useUrlFilters() {
  const [params, setParams] = useSearchParams()
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
