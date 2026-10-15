// Os filtros de data são dias do calendário LOCAL (AAAA-MM-DD na URL).
// Para a API, o dia vira o intervalo de instantes [00:00:00.000, 23:59:59.999]
// no fuso do navegador, em UTC. Mandar a data pura faria a API usar o dia UTC,
// e quem está em UTC-3 receberia o dia errado.

const DAY = /^(\d{4})-(\d{2})-(\d{2})$/

function parts(day: string): [number, number, number] | null {
  const m = DAY.exec(day)
  if (!m) return null
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])]
  // Rejeita datas inexistentes como 2026-02-31.
  const check = new Date(y, mo - 1, d)
  if (check.getFullYear() !== y || check.getMonth() !== mo - 1 || check.getDate() !== d) return null
  return [y, mo, d]
}

export function isValidDay(day: string): boolean {
  return parts(day) !== null
}

/** Início do dia local, como instante ISO UTC. */
export function startOfLocalDay(day: string): string | undefined {
  const p = parts(day)
  return p ? new Date(p[0], p[1] - 1, p[2], 0, 0, 0, 0).toISOString() : undefined
}

/** Último instante do dia local, como instante ISO UTC. */
export function endOfLocalDay(day: string): string | undefined {
  const p = parts(day)
  return p ? new Date(p[0], p[1] - 1, p[2], 23, 59, 59, 999).toISOString() : undefined
}

/** Dia local (AAAA-MM-DD) de um instante ISO. */
export function localDay(iso: string): string {
  const d = new Date(iso)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

const dateFmt = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short' })
const longFmt = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'full' })
const dateTimeFmt = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' })

export const formatDate = (iso: string | null) => (iso ? dateFmt.format(new Date(iso)) : '—')
export const formatDateTime = (iso: string | null) => (iso ? dateTimeFmt.format(new Date(iso)) : '—')
export const formatLongDay = (day: string) => {
  const p = parts(day)
  return p ? longFmt.format(new Date(p[0], p[1] - 1, p[2])) : day
}
