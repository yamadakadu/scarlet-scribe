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

export const APPS: AppDef[] = [
  {
    id: 'clickup',
    label: 'ClickUp',
    icon: ClickUpIcon,
    basePath: '/clickup',
    enabled: true,
    nav: [
      { path: 'tarefas', label: 'Tarefas' },
      { path: 'arquivadas', label: 'Arquivadas' },
      { path: 'marcos', label: 'Marcos' },
      { path: 'projetos', label: 'Projetos' },
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
  tasks: `${CLICKUP.basePath}/tarefas`,
  task: (id: string) => `${CLICKUP.basePath}/tarefas/${id}`,
  archived: `${CLICKUP.basePath}/arquivadas`,
  milestones: `${CLICKUP.basePath}/marcos`,
  projects: `${CLICKUP.basePath}/projetos`,
  tasksOfProject: (projectId: string) => `${CLICKUP.basePath}/tarefas?projeto=${projectId}`,
}

export function appForPath(pathname: string): AppDef | undefined {
  return APPS.find((a) => pathname === a.basePath || pathname.startsWith(`${a.basePath}/`))
}
