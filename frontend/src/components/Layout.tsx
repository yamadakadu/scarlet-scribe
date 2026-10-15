import { NavLink, Outlet, useLocation } from 'react-router'
import { appForPath, CLICKUP, GITHUB_REPO_URL } from '../apps.ts'
import { GitHubIcon } from '../assets/icons/AppIcons.tsx'
import { ApiStatus } from './ApiStatus.tsx'
import { AppSidebar } from './AppSidebar.tsx'
import { SyncButton } from './SyncButton.tsx'

export function Layout() {
  const { pathname } = useLocation()
  const app = appForPath(pathname) ?? CLICKUP

  return (
    <div className="app">
      <AppSidebar />
      <div className="app-body">
        <header className="app-header">
          <span className="app-title">{app.label}</span>
          <nav className="app-nav" aria-label={`Telas do ${app.label}`}>
            {app.nav.map((item) => (
              <NavLink key={item.path} to={`${app.basePath}/${item.path}`}>
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="app-header-actions">
            <ApiStatus />
            <SyncButton />
            <a
              className="github-link"
              href={GITHUB_REPO_URL}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Repositório no GitHub"
              title="Repositório no GitHub"
            >
              <GitHubIcon />
            </a>
          </div>
        </header>
        <main className="app-main">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
