import { createBrowserRouter, Navigate } from 'react-router'
import { CLICKUP, CLICKUP_ROUTES, clickupPaths } from './apps.ts'
import { LegacyRedirect } from './components/LegacyRedirect.tsx'
import { Layout } from './components/Layout.tsx'
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
      { index: true, element: <Navigate to={clickupPaths.tasks} replace /> },
      {
        path: CLICKUP.basePath.slice(1),
        children: [
          { index: true, element: <Navigate to={clickupPaths.tasks} replace /> },
          { path: CLICKUP_ROUTES.tasks, element: <TasksPage /> },
          { path: `${CLICKUP_ROUTES.tasks}/:id`, element: <TaskDetailPage /> },
          { path: CLICKUP_ROUTES.archived, element: <TasksPage archived /> },
          { path: CLICKUP_ROUTES.milestones, element: <MilestonesPage /> },
          { path: CLICKUP_ROUTES.projects, element: <ProjectsPage /> },
        ],
      },
      { path: 'tarefas', element: <LegacyRedirect to={() => clickupPaths.tasks} /> },
      { path: 'tarefas/:id', element: <LegacyRedirect to={clickupPaths.task} /> },
      { path: CLICKUP_ROUTES.archived, element: <LegacyRedirect to={() => clickupPaths.archived} /> },
      { path: 'marcos', element: <LegacyRedirect to={() => clickupPaths.milestones} /> },
      { path: 'projetos', element: <LegacyRedirect to={() => clickupPaths.projects} /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
