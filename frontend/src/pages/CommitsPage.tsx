import { useCommits, useRepositories } from '../api/queries.ts'
import { Pager } from '../components/Pager.tsx'
import { formatDateTime, isValidDay } from '../lib/dates.ts'
import { useUrlFilters } from '../lib/params.ts'

const PAGE_SIZE = 50

/** Commits do GitLab. Filtros na URL: repositorio, de, ate (dias locais), q, pagina. */
export function CommitsPage() {
  const { params, set, clear } = useUrlFilters()
  const repositorio = params.get('repositorio') ?? ''
  const q = params.get('q') ?? ''
  const de = params.get('de') ?? ''
  const ate = params.get('ate') ?? ''
  const pagina = Math.max(1, Number(params.get('pagina')) || 1)
  const deOk = !de || isValidDay(de)
  const ateOk = !ate || isValidDay(ate)

  const repos = useRepositories(false)
  const reposArchived = useRepositories(true)
  const commits = useCommits({
    repositoryId: repositorio || undefined,
    from: deOk ? de : undefined,
    to: ateOk ? ate : undefined,
    q,
    limit: PAGE_SIZE,
    offset: (pagina - 1) * PAGE_SIZE,
  })

  const repoOptions = [...(repos.data?.items ?? []), ...(reposArchived.data?.items ?? [])]
  const total = commits.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <section>
      <h1>Commits</h1>

      <form className="filters" onSubmit={(e) => e.preventDefault()}>
        <label>
          Busca
          <input type="search" value={q} onChange={(e) => set('q', e.target.value)} placeholder="Título" />
        </label>
        <label>
          Repositório
          <select value={repositorio} onChange={(e) => set('repositorio', e.target.value)}>
            <option value="">Todos</option>
            {repoOptions.map((r) => (
              <option key={r.id} value={r.id}>
                {r.path_with_namespace}
              </option>
            ))}
          </select>
        </label>
        <label>
          De
          <input type="date" value={de} onChange={(e) => set('de', e.target.value)} aria-invalid={!deOk} />
        </label>
        <label>
          Até
          <input type="date" value={ate} onChange={(e) => set('ate', e.target.value)} aria-invalid={!ateOk} />
        </label>
        {params.size > 0 && (
          <button type="button" onClick={clear}>
            Limpar filtros
          </button>
        )}
      </form>

      {commits.isError && <p className="error" role="alert">Não foi possível carregar os commits: {commits.error.message}</p>}
      {commits.isPending && <p className="placeholder">Carregando…</p>}
      {commits.data && (
        <>
          <p className="count" aria-live="polite">
            {total} {total === 1 ? 'commit' : 'commits'}
          </p>
          {commits.data.items.length === 0 ? (
            <p className="placeholder">Nenhum commit encontrado.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Commit</th>
                    <th>Título</th>
                    <th>Repositório</th>
                    <th>Autor</th>
                    <th>Data</th>
                  </tr>
                </thead>
                <tbody>
                  {commits.data.items.map((c) => (
                    <tr key={c.id}>
                      <td>
                        {c.web_url ? (
                          <a href={c.web_url} target="_blank" rel="noopener noreferrer">
                            <code>{c.short_sha}</code>
                          </a>
                        ) : (
                          <code>{c.short_sha}</code>
                        )}
                      </td>
                      <td>{c.title}</td>
                      <td>{c.repository.name}</td>
                      <td>{c.author_name ?? '—'}</td>
                      <td>{formatDateTime(c.authored_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pager page={pagina} pages={pages} onPage={(p) => set('pagina', String(p))} />
        </>
      )}
    </section>
  )
}
