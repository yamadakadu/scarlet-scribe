import type { ProjectNode } from '../api/client.ts'

export interface FlatProject {
  id: string
  name: string
  kind: string
  depth: number
}

export function flattenProjects(nodes: ProjectNode[], depth = 0): FlatProject[] {
  return nodes.flatMap((n) => [
    { id: n.id, name: n.name, kind: n.kind, depth },
    ...flattenProjects(n.children, depth + 1),
  ])
}
