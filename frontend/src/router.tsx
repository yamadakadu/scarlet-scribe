import { createBrowserRouter, Navigate } from 'react-router'
import { Layout } from './components/Layout.tsx'
import { MilestonesPage } from './pages/MilestonesPage.tsx'
import { NotFoundPage } from './pages/NotFoundPage.tsx'
import { ProjectsPage } from './pages/ProjectsPage.tsx'
import { TasksPage } from './pages/TasksPage.tsx'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/tarefas" replace /> },
      { path: 'tarefas', element: <TasksPage /> },
      { path: 'marcos', element: <MilestonesPage /> },
      { path: 'projetos', element: <ProjectsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
