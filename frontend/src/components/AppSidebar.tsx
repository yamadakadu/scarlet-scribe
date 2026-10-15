import { NavLink } from 'react-router'
import { APPS } from '../apps.ts'

export function AppSidebar() {
  return (
    <nav className="app-sidebar" aria-label="Aplicativos">
      {APPS.map((app) => {
        const Icon = app.icon
        if (!app.enabled) {
          const title = `${app.label} (${app.hint ?? 'em breve'})`
          return (
            <span key={app.id} className="app-sidebar-item is-disabled" role="link" tabIndex={0} aria-disabled="true" aria-label={title} title={title}>
              <Icon />
            </span>
          )
        }
        return (
          <NavLink key={app.id} to={app.basePath} className="app-sidebar-item" aria-label={app.label} title={app.label}>
            <Icon />
          </NavLink>
        )
      })}
    </nav>
  )
}
