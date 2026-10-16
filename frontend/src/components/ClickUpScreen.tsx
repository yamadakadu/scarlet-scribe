import type { ComponentType } from 'react'
import { useLocation, useParams } from 'react-router'
import { clickupPaths } from '../apps.ts'
import { MilestonesPage } from '../pages/MilestonesPage.tsx'
import { ProjectsPage } from '../pages/ProjectsPage.tsx'
import { TasksPage } from '../pages/TasksPage.tsx'
import { BackgroundSearchContext } from '../lib/params.ts'
import { readModalState } from '../lib/taskLink.ts'
import { TaskModal } from './TaskModal.tsx'

const ArchivedPage = () => <TasksPage archived />

const PAGES: Record<string, ComponentType> = {
  [clickupPaths.tasks]: TasksPage,
  [clickupPaths.archived]: ArchivedPage,
  [clickupPaths.milestones]: MilestonesPage,
  [clickupPaths.projects]: ProjectsPage,
}

/**
 * Elemento único das telas do ClickUp. Em `/clickup/tarefas/:id` desenha a tela de
 * fundo (a lista de origem, ou Tarefas em acesso direto) e a tarefa em modal por cima.
 * Como todas as rotas usam este mesmo elemento, a lista não é remontada ao abrir/fechar.
 */
export function ClickUpScreen() {
  const { id } = useParams()
  const location = useLocation()
  const { background } = readModalState(location.state)

  const bgPath = id ? (background?.pathname ?? clickupPaths.tasks) : location.pathname
  const bgSearch = id ? (background?.search ?? '') : location.search
  const Page = PAGES[bgPath.replace(/\/+$/, '')] ?? TasksPage

  return (
    <>
      <BackgroundSearchContext.Provider value={id ? bgSearch : null}>
        <Page />
      </BackgroundSearchContext.Provider>
      {id && <TaskModal key="task-modal" />}
    </>
  )
}
