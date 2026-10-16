import { useCallback } from 'react'
import { useLocation, useMatch } from 'react-router'
import { CLICKUP, CLICKUP_ROUTES, clickupPaths } from '../apps.ts'

export interface BackgroundLocation {
  pathname: string
  search: string
  hash: string
}

/** Estado de navegação da tarefa aberta em modal. */
export interface TaskModalState {
  /** Lista que fica atrás do modal; ausente em acesso direto. */
  background?: BackgroundLocation
  /** Quantas entradas de histórico o modal empilhou (1 = a primeira tarefa). */
  depth: number
}

export const TASK_ROUTE = `${CLICKUP.basePath}/${CLICKUP_ROUTES.tasks}/:id`

export function readModalState(state: unknown): TaskModalState {
  const s = state as Partial<TaskModalState> | null
  return { background: s?.background, depth: s?.depth ?? 1 }
}

/**
 * Props de <Link> para abrir uma tarefa. Numa lista, passa a lista como fundo;
 * dentro do modal, mantém o mesmo fundo e soma um nível. Sem clique simples
 * (Ctrl/botão do meio) o navegador abre a URL em outra aba.
 */
export function useTaskLink() {
  const location = useLocation()
  const inModal = useMatch(TASK_ROUTE) !== null
  return useCallback(
    (id: string) => {
      const state: TaskModalState = inModal
        ? (() => {
            const cur = readModalState(location.state)
            return { background: cur.background, depth: cur.depth + 1 }
          })()
        : {
            background: { pathname: location.pathname, search: location.search, hash: location.hash },
            depth: 1,
          }
      return { to: clickupPaths.task(id), state }
    },
    [inModal, location],
  )
}
