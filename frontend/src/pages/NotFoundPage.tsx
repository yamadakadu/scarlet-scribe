import { Link } from 'react-router'
import { clickupPaths } from '../apps.ts'

export function NotFoundPage() {
  return (
    <section>
      <h1>Página não encontrada</h1>
      <p>
        <Link to={clickupPaths.tasks}>Voltar para as tarefas</Link>
      </p>
    </section>
  )
}
