import { Link } from 'react-router'

export function NotFoundPage() {
  return (
    <section>
      <h1>Página não encontrada</h1>
      <p>
        <Link to="/tarefas">Voltar para as tarefas</Link>
      </p>
    </section>
  )
}
