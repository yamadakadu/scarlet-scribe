import { useCallback, useEffect, useRef } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router'
import { clickupPaths } from '../apps.ts'
import { ArrowLeftIcon, CloseIcon } from '../assets/icons/UiIcons.tsx'
import { preferences } from '../lib/preferences.ts'
import { readModalState } from '../lib/taskLink.ts'
import { TASK_TITLE_ID, TaskDetail } from './TaskDetail.tsx'

/**
 * Tarefa em <dialog> nativo (modal ou painel lateral, conforme a preferência).
 * showModal() prende o foco, trata o Esc e deixa o fundo inerte.
 */
export function TaskModal() {
  const { id = '' } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const ref = useRef<HTMLDialogElement>(null)
  const { background, depth } = readModalState(location.state)

  useEffect(() => {
    const dialog = ref.current
    if (dialog && !dialog.open) dialog.showModal()
    return () => dialog?.close()
  }, [])

  // Com fundo: desfaz as entradas empilhadas pelo modal. Sem fundo (acesso direto): vai às tarefas.
  const close = useCallback(() => {
    if (background) navigate(-depth)
    else navigate(clickupPaths.tasks, { replace: true })
  }, [background, depth, navigate])

  return (
    <dialog
      ref={ref}
      className={`task-dialog task-dialog--${preferences.taskOpenMode}`}
      aria-labelledby={TASK_TITLE_ID}
      onCancel={(e) => {
        e.preventDefault()
        close()
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) close()
      }}
    >
      <div className="task-dialog-inner">
        <div className="task-dialog-bar">
          {depth > 1 ? (
            <button type="button" className="link-button back-button" onClick={() => navigate(-1)}>
              <ArrowLeftIcon />
              Voltar
            </button>
          ) : (
            <span />
          )}
          <button type="button" className="icon-button" onClick={close} aria-label="Fechar">
            <CloseIcon />
          </button>
        </div>
        <TaskDetail id={id} onClose={close} />
      </div>
    </dialog>
  )
}
