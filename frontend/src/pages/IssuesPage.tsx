import type { IssueState } from '../api/client.ts'
import { useIssues, useRepositories } from '../api/queries.ts'
import { ExternalLink } from '../components/ExternalLink.tsx'
import { Pager } from '../components/Pager.tsx'
import { formatDateTime } from '../lib/dates.ts'
import { useUrlFilters } from '../lib/params.ts'

const PAGE_SIZE = 50
const STATES: { value: IssueState; label: string; single: string }[] = [
  { value: 'opened', label: 'Abertas', single: 'Aberta' },
  { value: 'closed', label: 'Fechadas', single: 'Fechada' },
]

/** Issues do GitLab. Filtros na URL: repositorio, estado, q, pagina. */
export function IssuesPage() {
  const { params, set, clear } = useUrlFilters()
  const repositorio = params.get('repositorio') ?? ''
  const q = params.get('q') ?? ''
  const estadoParam = params.get('estado')
  const estado: IssueState | 'todas' =
    estadoParam === 'todas' ? 'todas' : (STATES.find((s) => s.value === estadoParam)?.value ?? 'opened')
  const pagina = Math.max(1, Number(params.get('pagina')) || 1)

  const repos = useRepositories(false)
  const reposArchived = useRepositories(true)
  const issues = useIssues({
    repositoryId: repositorio || undefined,
    state: estado === 'todas' ? undefined : estado,
    q,
    limit: PAGE_SIZE,
    offset: (pagina - 1) * PAGE_SIZE,
  })

  const repoOptions = [...(repos.data?.items ?? []), ...(reposArchived.data?.items ?? [])]
  const total = issues.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <section>
      <h1>Issues</h1>

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
            <option value="todas">Todas</option>
          </select>
        </label>
        {params.size > 0 && (
          <button type="button" onClick={clear}>
            Limpar filtros
          </button>
        )}
      </form>

      {issues.isError && <p className="error" role="alert">Não foi possível carregar as issues: {issues.error.message}</p>}
      {issues.isPending && <p className="placeholder">Carregando…</p>}
      {issues.data && (
        <>
          <p className="count" aria-live="polite">
            {total} {total === 1 ? 'issue' : 'issues'}
          </p>
          {issues.data.items.length === 0 ? (
            <p className="placeholder">
              {params.size > 0
                ? 'Nenhuma issue encontrada com esses filtros.'
                : 'Nenhuma issue por aqui ainda. Elas aparecem depois da próxima sincronização.'}
            </p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Título</th>
                    <th>Estado</th>
                    <th>Tipo</th>
                    <th>Repositório</th>
                    <th>Autor</th>
                    <th>Atualizada em</th>
                    <th>Fechada em</th>
                  </tr>
                </thead>
                <tbody>
                  {issues.data.items.map((i) => (
                    <tr key={i.id}>
                      <td className="muted">#{i.iid}</td>
                      <td>
                        {i.web_url ? <ExternalLink href={i.web_url}>{i.title}</ExternalLink> : i.title}
                      </td>
                      <td>
                        <span className={`badge badge-${i.state}`}>
                          {STATES.find((s) => s.value === i.state)?.single ?? i.state}
                        </span>
                      </td>
                      <td>{i.issue_type ?? '—'}</td>
                      <td>{i.repository.name}</td>
                      <td>{i.author?.username ?? '—'}</td>
                      <td>{formatDateTime(i.source_updated_at)}</td>
                      <td>{formatDateTime(i.closed_at)}</td>
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
