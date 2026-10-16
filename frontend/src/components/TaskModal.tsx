import { useCallback, useLayoutEffect, useRef } from 'react'
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
  const downOnBackdrop = useRef(false)
  const { background, depth } = readModalState(location.state)

  // Layout effect: o cleanup roda antes de o <dialog> sair do DOM, então o foco volta ao link de origem.
  useLayoutEffect(() => {
    const dialog = ref.current
    const prev = document.activeElement
    if (dialog && !dialog.open) dialog.showModal()
    return () => {
      dialog?.close()
      if (prev instanceof HTMLElement && prev.isConnected) prev.focus()
    }
  }, [])

  // Desfaz as entradas de histórico empilhadas pelo modal e, se houver destino, o
  // substitui na entrada restante (assim o Voltar seguinte não reabre uma tarefa).
  const leave = useCallback(
    (to?: string) => {
      // Com fundo, a entrada anterior à primeira tarefa é a lista; sem fundo, a primeira tarefa é a entrada inicial.
      const steps = background ? depth : depth - 1
      const target = background ? to : (to ?? clickupPaths.tasks)
      if (steps === 0) {
        if (target) navigate(target, { replace: true })
        return
      }
      if (target) {
        window.addEventListener('popstate', () => navigate(target, { replace: true }), { once: true })
      }
      navigate(-steps)
    },
    [background, depth, navigate],
  )
  const close = useCallback(() => leave(), [leave])

  return (
    <dialog
      ref={ref}
      className={`task-dialog task-dialog--${preferences.taskOpenMode}`}
      aria-labelledby={TASK_TITLE_ID}
      onCancel={(e) => {
        e.preventDefault()
        close()
      }}
      onMouseDown={(e) => {
        downOnBackdrop.current = e.target === e.currentTarget
      }}
      onClick={(e) => {
        if (downOnBackdrop.current && e.target === e.currentTarget) close()
        downOnBackdrop.current = false
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
        <TaskDetail id={id} onClose={close} onLeaveTo={leave} />
      </div>
    </dialog>
  )
}
