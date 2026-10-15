import { Link, useSearchParams } from 'react-router'
import { useMilestones, useProjects } from '../api/queries.ts'
import { endOfLocalDay, formatLongDay, isValidDay, localDay, startOfLocalDay } from '../lib/dates.ts'
import { flattenProjects } from '../lib/projects.ts'
import type { Task } from '../api/client.ts'

/** Marcos agrupados pelo dia local do prazo. Filtros na URL: projeto, de, ate. */
export function MilestonesPage() {
  const [params, setParams] = useSearchParams()
  const projeto = params.get('projeto') ?? ''
  const de = params.get('de') ?? ''
  const ate = params.get('ate') ?? ''

  const projects = useProjects()
  const milestones = useMilestones(
    projeto || undefined,
    isValidDay(de) ? startOfLocalDay(de) : undefined,
    isValidDay(ate) ? endOfLocalDay(ate) : undefined,
  )

  const set = (key: string, value: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value) next.set(key, value)
        else next.delete(key)
        return next
      },
      { replace: true },
    )

  const groups = new Map<string, Task[]>()
  for (const m of milestones.data?.items ?? []) {
    const key = m.due_date ? localDay(m.due_date) : 'sem-prazo'
    groups.set(key, [...(groups.get(key) ?? []), m])
  }
  const flat = projects.data ? flattenProjects(projects.data.items) : []
  const total = milestones.data?.total ?? 0
  const shown = milestones.data?.items.length ?? 0

  return (
    <section>
      <h1>Marcos</h1>
      <form className="filters" onSubmit={(e) => e.preventDefault()}>
        <label>
          Projeto
          <select value={projeto} onChange={(e) => set('projeto', e.target.value)}>
            <option value="">Todos</option>
            {flat.map((p) => (
              <option key={p.id} value={p.id}>
                {'  '.repeat(p.depth)}
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Prazo de
          <input type="date" value={de} onChange={(e) => set('de', e.target.value)} />
        </label>
        <label>
          Prazo até
          <input type="date" value={ate} onChange={(e) => set('ate', e.target.value)} />
        </label>
        {params.size > 0 && (
          <button type="button" onClick={() => setParams({}, { replace: true })}>
            Limpar filtros
          </button>
        )}
      </form>

      {milestones.isError && <p className="error" role="alert">Não foi possível carregar os marcos: {milestones.error.message}</p>}
      {milestones.isPending && <p className="placeholder">Carregando…</p>}
      {milestones.data && shown === 0 && <p className="placeholder">Nenhum marco encontrado.</p>}
      {[...groups].map(([day, items]) => (
        <div key={day} className="day-group">
          <h2>{day === 'sem-prazo' ? 'Sem prazo' : formatLongDay(day)}</h2>
          <ul className="plain-list">
            {items.map((m) => (
              <li key={m.id}>
                <Link to={`/tarefas/${m.id}`}>{m.name}</Link>
                <span className="muted"> · {m.container?.name ?? 'sem projeto'}</span>
                {m.status && <span className="tag">{m.status}</span>}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {total > shown && <p className="muted">Mostrando os primeiros {shown} de {total} marcos; use o filtro de datas.</p>}
    </section>
  )
}
