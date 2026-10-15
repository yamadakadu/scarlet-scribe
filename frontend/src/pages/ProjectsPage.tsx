import { useState } from 'react'
import { Link } from 'react-router'
import type { ProjectNode } from '../api/client.ts'
import { useProjects } from '../api/queries.ts'
import { clickupPaths } from '../apps.ts'

const KIND: Record<string, string> = { space: 'space', folder: 'pasta', list: 'lista' }

function Node({ node, depth }: { node: ProjectNode; depth: number }) {
  const [open, setOpen] = useState(depth < 1)
  const hasChildren = node.children.length > 0
  return (
    <li>
      <div className="tree-row">
        {hasChildren ? (
          <button
            type="button"
            className="link-button tree-toggle"
            aria-expanded={open}
            aria-label={`${open ? 'Recolher' : 'Expandir'} ${node.name}`}
            onClick={() => setOpen(!open)}
          >
            {open ? '▾' : '▸'}
          </button>
        ) : (
          <span className="tree-toggle" aria-hidden="true" />
        )}
        <Link to={clickupPaths.tasksOfProject(node.id)} title="Ver as tarefas deste projeto">
          {node.name}
        </Link>
        <span className="tag">{KIND[node.kind] ?? node.kind}</span>
      </div>
      {hasChildren && open && (
        <ul className="tree">
          {node.children.map((c) => (
            <Node key={c.id} node={c} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  )
}

export function ProjectsPage() {
  const projects = useProjects()
  return (
    <section>
      <h1>Projetos</h1>
      <p className="muted">Clique em um projeto para ver as tarefas dele (inclui as de dentro).</p>
      {projects.isError && <p className="error" role="alert">Não foi possível carregar os projetos: {projects.error.message}</p>}
      {projects.isPending && <p className="placeholder">Carregando…</p>}
      {projects.data && projects.data.items.length === 0 && <p className="placeholder">Nenhum projeto sincronizado ainda.</p>}
      {projects.data && (
        <ul className="tree tree--root">
          {projects.data.items.map((n) => (
            <Node key={n.id} node={n} depth={0} />
          ))}
        </ul>
      )}
    </section>
  )
}
