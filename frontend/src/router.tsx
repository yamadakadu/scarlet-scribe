import { createBrowserRouter, Navigate } from 'react-router'
import { CLICKUP, CLICKUP_ROUTES, clickupPaths, GITLAB, GITLAB_ROUTES, gitlabPaths } from './apps.ts'
import { ClickUpScreen } from './components/ClickUpScreen.tsx'
import { LegacyRedirect } from './components/LegacyRedirect.tsx'
import { Layout } from './components/Layout.tsx'
import { CommitsPage } from './pages/CommitsPage.tsx'
import { MergeRequestsPage } from './pages/MergeRequestsPage.tsx'
import { RepositoriesPage } from './pages/RepositoriesPage.tsx'
import { NotFoundPage } from './pages/NotFoundPage.tsx'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to={clickupPaths.projects} replace /> },
      {
        path: CLICKUP.basePath.slice(1),
        children: [
          { index: true, element: <Navigate to={clickupPaths.projects} replace /> },
          // Mesmo elemento em todas as rotas: a tela de fundo não remonta ao abrir a tarefa.
          { path: CLICKUP_ROUTES.tasks, element: <ClickUpScreen /> },
          { path: `${CLICKUP_ROUTES.tasks}/:id`, element: <ClickUpScreen /> },
          { path: CLICKUP_ROUTES.archived, element: <ClickUpScreen /> },
          { path: CLICKUP_ROUTES.milestones, element: <ClickUpScreen /> },
          { path: CLICKUP_ROUTES.projects, element: <ClickUpScreen /> },
        ],
      },
      {
        path: GITLAB.basePath.slice(1),
        children: [
          { index: true, element: <Navigate to={gitlabPaths.repositories} replace /> },
          { path: GITLAB_ROUTES.mergeRequests, element: <MergeRequestsPage /> },
          { path: GITLAB_ROUTES.commits, element: <CommitsPage /> },
          { path: GITLAB_ROUTES.repositories, element: <RepositoriesPage /> },
        ],
      },
      { path: 'tarefas', element: <LegacyRedirect to={() => clickupPaths.tasks} /> },
      { path: 'tarefas/:id', element: <LegacyRedirect to={clickupPaths.task} /> },
      { path: 'arquivadas', element: <LegacyRedirect to={() => clickupPaths.archived} /> },
      { path: 'marcos', element: <LegacyRedirect to={() => clickupPaths.milestones} /> },
      { path: 'projetos', element: <LegacyRedirect to={() => clickupPaths.projects} /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
