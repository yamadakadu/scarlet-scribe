import { NavLink, Outlet } from 'react-router'
import { ApiStatus } from './ApiStatus.tsx'
import { SyncButton } from './SyncButton.tsx'

const NAV_ITEMS = [
  { to: '/tarefas', label: 'Tarefas' },
  { to: '/arquivadas', label: 'Arquivadas' },
  { to: '/marcos', label: 'Marcos' },
  { to: '/projetos', label: 'Projetos' },
]

export function Layout() {
  return (
    <div className="app">
      <header className="app-header">
        <span className="app-title">Scarlet Scribe</span>
        <nav className="app-nav" aria-label="Principal">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="app-header-actions">
          <ApiStatus />
          <SyncButton />
        </div>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
