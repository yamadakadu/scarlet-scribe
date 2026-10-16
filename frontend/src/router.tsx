import { createBrowserRouter, Navigate } from 'react-router'
import { CLICKUP, CLICKUP_ROUTES, clickupPaths, GITLAB, GITLAB_ROUTES, gitlabPaths } from './apps.ts'
import { LegacyRedirect } from './components/LegacyRedirect.tsx'
import { Layout } from './components/Layout.tsx'
import { CommitsPage } from './pages/CommitsPage.tsx'
import { MergeRequestsPage } from './pages/MergeRequestsPage.tsx'
import { RepositoriesPage } from './pages/RepositoriesPage.tsx'
import { MilestonesPage } from './pages/MilestonesPage.tsx'
import { NotFoundPage } from './pages/NotFoundPage.tsx'
import { ProjectsPage } from './pages/ProjectsPage.tsx'
import { TaskDetailPage } from './pages/TaskDetailPage.tsx'
import { TasksPage } from './pages/TasksPage.tsx'

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
          { path: CLICKUP_ROUTES.tasks, element: <TasksPage /> },
          { path: `${CLICKUP_ROUTES.tasks}/:id`, element: <TaskDetailPage /> },
          { path: CLICKUP_ROUTES.archived, element: <TasksPage archived /> },
          { path: CLICKUP_ROUTES.milestones, element: <MilestonesPage /> },
          { path: CLICKUP_ROUTES.projects, element: <ProjectsPage /> },
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
