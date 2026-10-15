import { Link } from 'react-router'
import type { Task } from '../api/client.ts'
import { formatDate } from '../lib/dates.ts'

export function TaskTable({ tasks, showArchived }: { tasks: Task[]; showArchived?: boolean }) {
  if (tasks.length === 0) return <p className="placeholder">Nenhuma tarefa encontrada.</p>
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Tarefa</th>
            <th>Status</th>
            <th>Projeto</th>
            <th>Responsáveis</th>
            <th>Prazo</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((t) => (
            <tr key={t.id}>
              <td>
                <Link to={`/tarefas/${t.id}`}>{t.name}</Link>
                {t.is_milestone && <span className="tag">marco</span>}
                {showArchived && t.archived && <span className="tag">arquivada</span>}
                {t.parent_id && <span className="tag">subtarefa</span>}
              </td>
              <td>{t.status ?? '—'}</td>
              <td>{t.container?.name ?? 'sem projeto'}</td>
              <td>{t.assignees.map((a) => a.username ?? a.email ?? '?').join(', ') || '—'}</td>
              <td>{formatDate(t.due_date)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
