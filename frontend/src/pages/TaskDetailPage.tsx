import { Link, useNavigate, useParams } from 'react-router'
import { ApiError } from '../api/client.ts'
import { useTask } from '../api/queries.ts'
import { PriorityBadge, StatusBadge } from '../components/Badges.tsx'
import { ExternalLink } from '../components/ExternalLink.tsx'
import { ArrowLeftIcon } from '../assets/icons/UiIcons.tsx'
import { TaskTable } from '../components/TaskTable.tsx'
import { formatDate, formatDateTime } from '../lib/dates.ts'
import { clickupPaths } from '../apps.ts'

export function TaskDetailPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const task = useTask(id)
  // Volta para a lista com os filtros, se a pessoa veio dela.
  const back = () => (window.history.state?.idx > 0 ? navigate(-1) : navigate(clickupPaths.tasks))

  if (task.isPending) return <p className="placeholder">Carregando…</p>
  if (task.isError) {
    const notFound = task.error instanceof ApiError && task.error.status === 404
    return (
      <section>
        <p className="error" role="alert">
          {notFound ? 'Tarefa não encontrada.' : `Não foi possível carregar a tarefa: ${task.error.message}`}
        </p>
        <Link to={clickupPaths.tasks}>Voltar às tarefas</Link>
      </section>
    )
  }
  const t = task.data
  const fields: { k: string; v: React.ReactNode }[] = [
    { k: 'Status', v: <StatusBadge status={t.status} type={t.status_type} /> },
    { k: 'Prioridade', v: <PriorityBadge priority={t.priority} /> },
    { k: 'Projeto', v: t.container ? <Link to={clickupPaths.tasksOfProject(t.container.id)}>{t.container.name}</Link> : 'sem projeto' },
    { k: 'Responsáveis', v: t.assignees.map((a) => a.username ?? a.email ?? '?').join(', ') || '—' },
    { k: 'Início', v: formatDate(t.start_date) },
    { k: 'Prazo', v: formatDate(t.due_date) },
    { k: 'Concluída em', v: formatDateTime(t.done_at) },
    { k: 'Alterada na origem', v: formatDateTime(t.source_updated_at) },
  ]
  return (
    <section>
      <button type="button" className="link-button back-button" onClick={back}>
        <ArrowLeftIcon />
        Voltar
      </button>
      <h1>
        {t.name}
        {t.is_milestone && <span className="tag">marco</span>}
        {t.archived && <span className="tag">arquivada</span>}
      </h1>
      {t.url && (
        <p>
          <ExternalLink href={t.url}>Abrir no ClickUp</ExternalLink>
        </p>
      )}
      {t.parent && (
        <p>
          Subtarefa de <Link to={clickupPaths.task(t.parent.id)}>{t.parent.name}</Link>
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
          <h2>Subtarefas</h2>
          <TaskTable tasks={t.subtasks} showArchived />
        </>
      )}
    </section>
  )
}
