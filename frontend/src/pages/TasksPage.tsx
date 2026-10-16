import type { TaskOrder } from '../api/client.ts'
import { usePeople, useProjects, useTasks } from '../api/queries.ts'
import { TaskTable } from '../components/TaskTable.tsx'
import { isValidDay } from '../lib/dates.ts'
import { useUrlFilters } from '../lib/params.ts'
import { flattenProjects } from '../lib/projects.ts'

const PAGE_SIZE = 50
const ORDERS: { value: TaskOrder; label: string }[] = [
  { value: 'due_date', label: 'Prazo' },
  { value: 'updated_at', label: 'Alterada recentemente' },
  { value: 'name', label: 'Nome' },
]

/**
 * Lista de tarefas. Todos os filtros ficam na URL (link compartilhável):
 * q, status, pessoa, projeto, de, ate (dias locais), encerradas, ordem, pagina.
 * `archived` escolhe entre a lista ativa e a seção de arquivadas.
 */
export function TasksPage({ archived = false }: { archived?: boolean }) {
  const { params, set, clear } = useUrlFilters()
  const q = params.get('q') ?? ''
  const status = params.get('status') ?? ''
  const pessoa = params.get('pessoa') ?? ''
  const projeto = params.get('projeto') ?? ''
  const de = params.get('de') ?? ''
  const ate = params.get('ate') ?? ''
  const encerradas = params.get('encerradas') === '1'
  const ordem = (ORDERS.find((o) => o.value === params.get('ordem'))?.value ?? 'due_date') as TaskOrder
  const pagina = Math.max(1, Number(params.get('pagina')) || 1)

  const deOk = !de || isValidDay(de)
  const ateOk = !ate || isValidDay(ate)

  const projects = useProjects()
  const people = usePeople()
  const tasks = useTasks({
    q,
    status,
    assigneeId: pessoa || undefined,
    containerId: projeto || undefined,
    dueFrom: deOk ? de : undefined,
    dueTo: ateOk ? ate : undefined,
    includeClosed: encerradas,
    archived,
    orderBy: ordem,
    limit: PAGE_SIZE,
    offset: (pagina - 1) * PAGE_SIZE,
  })

  const flat = projects.data ? flattenProjects(projects.data.items) : []
  const hasFilters = [...params.keys()].length > 0
  const total = tasks.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <section>
      <h1>{archived ? 'Tarefas arquivadas' : 'Tarefas'}</h1>

      <form className="filters" onSubmit={(e) => e.preventDefault()}>
        <label>
          Busca
          <input type="search" value={q} onChange={(e) => set('q', e.target.value)} placeholder="Nome da tarefa" />
        </label>
        <label>
          Status
          <input value={status} onChange={(e) => set('status', e.target.value)} placeholder="ex.: in progress" />
        </label>
        <label>
          Responsável
          <select value={pessoa} onChange={(e) => set('pessoa', e.target.value)}>
            <option value="">Todos</option>
            {people.data?.items.map((p) => (
              <option key={p.id} value={p.id}>
                {p.username ?? p.email}
              </option>
            ))}
          </select>
        </label>
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
          <input type="date" value={de} onChange={(e) => set('de', e.target.value)} aria-invalid={!deOk} />
        </label>
        <label>
          Prazo até
          <input type="date" value={ate} onChange={(e) => set('ate', e.target.value)} aria-invalid={!ateOk} />
        </label>
        <label>
          Ordenar por
          <select value={ordem} onChange={(e) => set('ordem', e.target.value === 'due_date' ? '' : e.target.value)}>
            {ORDERS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={encerradas} onChange={(e) => set('encerradas', e.target.checked ? '1' : '')} />
          Incluir encerradas
        </label>
        {hasFilters && (
          <button type="button" onClick={clear}>
            Limpar filtros
          </button>
        )}
      </form>

      {tasks.isError && <p className="error" role="alert">Não foi possível carregar as tarefas: {tasks.error.message}</p>}
      {tasks.isPending && <p className="placeholder">Carregando…</p>}
      {tasks.data && (
        <>
          <p className="count" aria-live="polite">
            {total} {total === 1 ? 'tarefa' : 'tarefas'}
          </p>
          <TaskTable tasks={tasks.data.items} />
          {pages > 1 && (
            <nav className="pager" aria-label="Paginação">
              <button type="button" disabled={pagina <= 1} onClick={() => set('pagina', String(pagina - 1))}>
                Anterior
              </button>
              <span>
                Página {pagina} de {pages}
              </span>
              <button type="button" disabled={pagina >= pages} onClick={() => set('pagina', String(pagina + 1))}>
                Próxima
              </button>
            </nav>
          )}
        </>
      )}
    </section>
  )
}
