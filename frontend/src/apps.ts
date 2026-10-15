import { ClickUpIcon, GitLabIcon, type IconComponent } from './assets/icons/AppIcons.tsx'

export interface AppNavItem {
  /** Caminho relativo ao basePath do app. */
  path: string
  label: string
}

export interface AppDef {
  id: string
  label: string
  icon: IconComponent
  basePath: string
  nav: AppNavItem[]
  enabled: boolean
  /** Dica exibida quando o app está desabilitado. */
  hint?: string
}

export const CLICKUP_ROUTES = {
  tasks: 'tarefas',
  archived: 'arquivadas',
  milestones: 'marcos',
  projects: 'projetos',
} as const

export const APPS: AppDef[] = [
  {
    id: 'clickup',
    label: 'ClickUp',
    icon: ClickUpIcon,
    basePath: '/clickup',
    enabled: true,
    nav: [
      { path: CLICKUP_ROUTES.tasks, label: 'Tarefas' },
      { path: CLICKUP_ROUTES.archived, label: 'Arquivadas' },
      { path: CLICKUP_ROUTES.milestones, label: 'Marcos' },
      { path: CLICKUP_ROUTES.projects, label: 'Projetos' },
    ],
  },
  {
    id: 'gitlab',
    label: 'GitLab',
    icon: GitLabIcon,
    basePath: '/gitlab',
    enabled: false,
    hint: 'em breve',
    nav: [],
  },
]

export const CLICKUP = APPS[0]!

/** Caminhos do ClickUp derivados do basePath, para os links internos. */
export const clickupPaths = {
  tasks: `${CLICKUP.basePath}/${CLICKUP_ROUTES.tasks}`,
  task: (id: string) => `${CLICKUP.basePath}/${CLICKUP_ROUTES.tasks}/${id}`,
  archived: `${CLICKUP.basePath}/${CLICKUP_ROUTES.archived}`,
  milestones: `${CLICKUP.basePath}/${CLICKUP_ROUTES.milestones}`,
  projects: `${CLICKUP.basePath}/${CLICKUP_ROUTES.projects}`,
  tasksOfProject: (projectId: string) => `${CLICKUP.basePath}/${CLICKUP_ROUTES.tasks}?projeto=${projectId}`,
}

export function appForPath(pathname: string): AppDef | undefined {
  return APPS.find((a) => pathname === a.basePath || pathname.startsWith(`${a.basePath}/`))
}
