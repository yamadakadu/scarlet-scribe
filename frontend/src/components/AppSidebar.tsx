import { NavLink } from 'react-router'
import { useSources } from '../api/queries.ts'
import { APPS } from '../apps.ts'
import { formatDateTime } from '../lib/dates.ts'

export function AppSidebar() {
  const sources = useSources()
  return (
    <nav className="app-sidebar" aria-label="Aplicativos">
      {APPS.map((app) => {
        const Icon = app.icon
        // Com /sources carregado, o enabled vem da API; senão vale o estático.
        const source = sources.data?.items.find((s) => s.id === app.id)
        const enabled = source ? source.enabled : app.enabled
        if (!enabled) {
          const title = `${app.label} (${source ? 'não configurado' : (app.hint ?? 'em breve')})`
          return (
            <span key={app.id} className="app-sidebar-item is-disabled" role="link" tabIndex={0} aria-disabled="true" aria-label={title} title={title}>
              <Icon />
            </span>
          )
        }
        const title = source
          ? `${app.label} · ${source.last_synced_at ? `último sync ${formatDateTime(source.last_synced_at)}` : 'nunca sincronizado'}`
          : app.label
        return (
          <NavLink key={app.id} to={app.basePath} className="app-sidebar-item" aria-label={title} title={title}>
            <Icon />
          </NavLink>
        )
      })}
    </nav>
  )
}
