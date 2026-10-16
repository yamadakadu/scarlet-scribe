import { Link } from 'react-router'
import { ApiError } from '../api/client.ts'
import { useTask } from '../api/queries.ts'
import { clickupPaths } from '../apps.ts'
import { formatDate, formatDateTime } from '../lib/dates.ts'
import { useTaskLink } from '../lib/taskLink.ts'
import { PriorityBadge, StatusBadge } from './Badges.tsx'
import { ExternalLink } from './ExternalLink.tsx'
import { TaskTable } from './TaskTable.tsx'

export const TASK_TITLE_ID = 'task-detail-title'

/** Conteúdo da tarefa (mostrado dentro do modal/painel). */
export function TaskDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const task = useTask(id)
  const taskLink = useTaskLink()

  if (task.isPending) {
    return (
      <div>
        <h2 id={TASK_TITLE_ID} className="task-title">Tarefa</h2>
        <p className="placeholder">Carregando…</p>
      </div>
    )
  }
  if (task.isError) {
    const notFound = task.error instanceof ApiError && task.error.status === 404
    return (
      <div>
        <h2 id={TASK_TITLE_ID} className="task-title">Tarefa</h2>
        <p className="error" role="alert">
          {notFound ? 'Tarefa não encontrada.' : `Não foi possível carregar a tarefa: ${task.error.message}`}
        </p>
        <button type="button" onClick={onClose}>
          Fechar
        </button>
      </div>
    )
  }
  const t = task.data
  const fields: { k: string; v: React.ReactNode }[] = [
    { k: 'Status', v: <StatusBadge status={t.status} type={t.status_type} /> },
    { k: 'Prioridade', v: <PriorityBadge priority={t.priority} /> },
    {
      k: 'Projeto',
      v: t.container ? (
        <Link to={clickupPaths.tasksOfProject(t.container.id)} replace>
          {t.container.name}
        </Link>
      ) : (
        'sem projeto'
      ),
    },
    { k: 'Responsáveis', v: t.assignees.map((a) => a.username ?? a.email ?? '?').join(', ') || '—' },
    { k: 'Início', v: formatDate(t.start_date) },
    { k: 'Prazo', v: formatDate(t.due_date) },
    { k: 'Concluída em', v: formatDateTime(t.done_at) },
    { k: 'Alterada na origem', v: formatDateTime(t.source_updated_at) },
  ]
  return (
    <div>
      <h2 id={TASK_TITLE_ID} className="task-title">
        {t.name}
        {t.is_milestone && <span className="tag">marco</span>}
        {t.archived && <span className="tag">arquivada</span>}
      </h2>
      {t.url && (
        <p>
          <ExternalLink href={t.url}>Abrir no ClickUp</ExternalLink>
        </p>
      )}
      {t.parent && (
        <p>
          Subtarefa de <Link {...taskLink(t.parent.id)}>{t.parent.name}</Link>
          {t.parent.archived && <span className="tag">arquivada</span>}
        </p>
      )}
      <dl className="fields">
        {fields.map(({ k, v }) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      {t.subtasks.length > 0 && (
        <>
          <h3>Subtarefas</h3>
          <TaskTable tasks={t.subtasks} showArchived />
        </>
      )}
    </div>
  )
}
