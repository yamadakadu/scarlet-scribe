import { NavLink, Outlet } from 'react-router'
import { ApiStatus } from './ApiStatus.tsx'

const NAV_ITEMS = [
  { to: '/tarefas', label: 'Tarefas' },
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
          {/* O botão ganha a lógica (POST /sync e acompanhamento do run) na F1-09b. */}
          <button type="button" disabled title="Disponível em breve">
            Sincronizar agora
          </button>
        </div>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
