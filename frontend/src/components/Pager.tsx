export function Pager({ page, pages, onPage }: { page: number; pages: number; onPage: (page: number) => void }) {
  if (pages <= 1) return null
  return (
    <nav className="pager" aria-label="Paginação">
      <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Anterior
      </button>
      <span>
        Página {page} de {pages}
      </span>
      <button type="button" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Próxima
      </button>
    </nav>
  )
}
