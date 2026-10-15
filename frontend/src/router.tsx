import { createBrowserRouter, Navigate } from 'react-router'
import { CLICKUP, clickupPaths } from './apps.ts'
import { LegacyRedirect } from './components/LegacyRedirect.tsx'
import { Layout } from './components/Layout.tsx'
import { MilestonesPage } from './pages/MilestonesPage.tsx'
import { NotFoundPage } from './pages/NotFoundPage.tsx'
import { ProjectsPage } from './pages/ProjectsPage.tsx'
import { TaskDetailPage } from './pages/TaskDetailPage.tsx'
import { TasksPage } from './pages/TasksPage.tsx'

const [tasks, , milestones, projects] = CLICKUP.nav.map((n) => n.path)

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
          { path: tasks, element: <TasksPage /> },
          { path: `${tasks}/:id`, element: <TaskDetailPage /> },
          { path: 'arquivadas', element: <TasksPage archived /> },
          { path: milestones, element: <MilestonesPage /> },
          { path: projects, element: <ProjectsPage /> },
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
