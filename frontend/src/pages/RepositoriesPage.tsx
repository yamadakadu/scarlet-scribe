import { Link } from 'react-router'
import { useRepositories } from '../api/queries.ts'
import { gitlabPaths } from '../apps.ts'
import { ChevronRightIcon } from '../assets/icons/UiIcons.tsx'
import { ExternalLink } from '../components/ExternalLink.tsx'
import { Pager } from '../components/Pager.tsx'
import { formatDateTime } from '../lib/dates.ts'
import { useUrlFilters } from '../lib/params.ts'

const PAGE_SIZE = 50

/** Repositórios do GitLab. Filtros na URL: arquivados, pagina. */
export function RepositoriesPage() {
  const { params, set } = useUrlFilters()
  const arquivados = params.get('arquivados') === '1'
  const pagina = Math.max(1, Number(params.get('pagina')) || 1)
  const repos = useRepositories(arquivados, PAGE_SIZE, (pagina - 1) * PAGE_SIZE)

  const total = repos.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <section>
      <h1>{arquivados ? 'Repositórios arquivados' : 'Repositórios'}</h1>

      <form className="filters" onSubmit={(e) => e.preventDefault()}>
        <label className="check">
          <input type="checkbox" checked={arquivados} onChange={(e) => set('arquivados', e.target.checked ? '1' : '')} />
          Mostrar só arquivados
        </label>
      </form>

      {repos.isError && <p className="error" role="alert">Não foi possível carregar os repositórios: {repos.error.message}</p>}
      {repos.isPending && <p className="placeholder">Carregando…</p>}
      {repos.data && (
        <>
          {repos.data.items.length === 0 ? (
            <p className="placeholder">Nenhum repositório encontrado.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Repositório</th>
                    <th>Branch padrão</th>
                    <th>Última atividade</th>
                    <th>Merge requests</th>
                  </tr>
                </thead>
                <tbody>
                  {repos.data.items.map((r) => (
                    <tr key={r.id}>
                      <td>
                        {r.web_url ? (
                          <ExternalLink href={r.web_url}>{r.path_with_namespace}</ExternalLink>
                        ) : (
                          r.path_with_namespace
                        )}
                        {r.archived && <span className="tag">arquivado</span>}
                      </td>
                      <td>{r.default_branch ? <code>{r.default_branch}</code> : '—'}</td>
                      <td>{formatDateTime(r.last_activity_at)}</td>
                      <td>
                        <Link className="go-link" to={gitlabPaths.mergeRequestsOfRepository(r.id)}>
                          Ver
                          <ChevronRightIcon />
                        </Link>
                      </td>
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
