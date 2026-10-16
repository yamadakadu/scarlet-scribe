import { ExternalLink } from '../components/ExternalLink.tsx'
import type { MergeRequestState } from '../api/client.ts'
import { useMergeRequests, useRepositories } from '../api/queries.ts'
import { Pager } from '../components/Pager.tsx'
import { formatDateTime } from '../lib/dates.ts'
import { useUrlFilters } from '../lib/params.ts'

const PAGE_SIZE = 50
const STATES: { value: MergeRequestState; label: string }[] = [
  { value: 'opened', label: 'Abertos' },
  { value: 'merged', label: 'Mesclados' },
  { value: 'closed', label: 'Fechados' },
  { value: 'locked', label: 'Bloqueados' },
]

/** Merge requests do GitLab. Filtros na URL: repositorio, estado, q, pagina. */
export function MergeRequestsPage() {
  const { params, set, clear } = useUrlFilters()
  const repositorio = params.get('repositorio') ?? ''
  const q = params.get('q') ?? ''
  const estadoParam = params.get('estado')
  const estado: MergeRequestState | 'todos' =
    estadoParam === 'todos' ? 'todos' : (STATES.find((s) => s.value === estadoParam)?.value ?? 'opened')
  const pagina = Math.max(1, Number(params.get('pagina')) || 1)

  const repos = useRepositories(false)
  const reposArchived = useRepositories(true)
  const mrs = useMergeRequests({
    repositoryId: repositorio || undefined,
    state: estado === 'todos' ? undefined : estado,
    q,
    limit: PAGE_SIZE,
    offset: (pagina - 1) * PAGE_SIZE,
  })

  const repoOptions = [...(repos.data?.items ?? []), ...(reposArchived.data?.items ?? [])]
  const total = mrs.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <section>
      <h1>Merge Requests</h1>

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
          Estado
          <select value={estado} onChange={(e) => set('estado', e.target.value === 'opened' ? '' : e.target.value)}>
            {STATES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
            <option value="todos">Todos</option>
          </select>
        </label>
        {params.size > 0 && (
          <button type="button" onClick={clear}>
            Limpar filtros
          </button>
        )}
      </form>

      {mrs.isError && <p className="error" role="alert">Não foi possível carregar os merge requests: {mrs.error.message}</p>}
      {mrs.isPending && <p className="placeholder">Carregando…</p>}
      {mrs.data && (
        <>
          <p className="count" aria-live="polite">
            {total} {total === 1 ? 'merge request' : 'merge requests'}
          </p>
          {mrs.data.items.length === 0 ? (
            <p className="placeholder">Nenhum merge request encontrado.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Merge request</th>
                    <th>Repositório</th>
                    <th>Estado</th>
                    <th>Autor</th>
                    <th>Branches</th>
                    <th>Atualizado em</th>
                  </tr>
                </thead>
                <tbody>
                  {mrs.data.items.map((m) => (
                    <tr key={m.id}>
                      <td>
                        {m.web_url ? (
                          <ExternalLink href={m.web_url}>{m.title}</ExternalLink>
                        ) : (
                          m.title
                        )}{' '}
                        <span className="muted">!{m.iid}</span>
                        {m.draft && <span className="tag">rascunho</span>}
                      </td>
                      <td>{m.repository.name}</td>
                      <td>
                        <span className={`badge badge-${m.state}`}>
                          {STATES.find((s) => s.value === m.state)?.label.replace(/s$/, '') ?? m.state}
                        </span>
                      </td>
                      <td>{m.author?.username ?? '—'}</td>
                      <td>
                        <code>{m.source_branch}</code> → <code>{m.target_branch}</code>
                      </td>
                      <td>{formatDateTime(m.source_updated_at)}</td>
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
