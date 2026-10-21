import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client.ts'
import { isActive, useLatestSyncRun, useRequestSync } from '../api/sync.ts'
import { formatDateTime } from '../lib/dates.ts'

const LABELS: Record<string, string> = {
  tasks: 'tarefas',
  containers: 'projetos',
  people: 'pessoas',
  workspaces: 'workspaces',
}

/** Resume `stats` ({ tasks: { created, updated, deleted } }) em texto. */
function summarize(stats: Record<string, unknown>): string {
  const parts: string[] = []
  for (const [key, value] of Object.entries(stats)) {
    if (typeof value === 'object' && value !== null) {
      const v = value as Record<string, unknown>
      const counts = [
        ['criadas', v.created],
        ['atualizadas', v.updated],
        ['removidas', v.deleted],
      ].filter(([, n]) => typeof n === 'number' && n > 0)
      if (counts.length) {
        parts.push(`${LABELS[key] ?? key}: ${counts.map(([l, n]) => `${n} ${l}`).join(', ')}`)
      }
    } else if (typeof value === 'number') {
      parts.push(`${LABELS[key] ?? key}: ${value}`)
    }
  }
  return parts.join(' · ')
}

function useNow(enabled: boolean) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!enabled) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [enabled])
  return [now, () => setNow(Date.now())] as const
}

export function SyncButton() {
  const client = useQueryClient()
  const latest = useLatestSyncRun()
  const request = useRequestSync()
  const [cooldownUntil, setCooldownUntil] = useState<number | null>(null)

  const run = latest.data
  const active = isActive(run)
  const [now, refreshNow] = useNow(active || cooldownUntil !== null)
  const remaining = cooldownUntil === null ? 0 : Math.max(0, Math.ceil((cooldownUntil - now) / 1000))

  // Ao terminar com sucesso, recarrega os dados que a tela mostra.
  const prevActive = useRef(active)
  useEffect(() => {
    if (prevActive.current && !active && (run?.status === 'succeeded' || run?.status === 'partial')) {
      for (const key of ['tasks', 'task', 'milestones', 'projects', 'people', 'sources', 'repositories', 'merge-requests', 'issues', 'commits']) {
        void client.invalidateQueries({ queryKey: [key] })
      }
    }
    prevActive.current = active
  }, [active, run?.status, client])

  // Encerra o cooldown quando a contagem chega a zero.
  useEffect(() => {
    if (cooldownUntil === null) return
    const id = setTimeout(() => setCooldownUntil(null), Math.max(0, cooldownUntil - Date.now()))
    return () => clearTimeout(id)
  }, [cooldownUntil])

  const click = () => {
    request.mutate(undefined, {
      onSuccess: () => {
        refreshNow()
        setCooldownUntil(null)
      },
      onError: (error) => {
        if (error instanceof ApiError && error.status === 429) {
          refreshNow()
          setCooldownUntil(Date.now() + (error.retryAfter ?? 60) * 1000)
        }
      },
    })
  }

  let label = 'Sincronizar agora'
  if (request.isPending) label = 'Enviando…'
  else if (active) label = run?.status === 'pending' ? 'Na fila…' : 'Sincronizando…'
  else if (remaining > 0) label = `Aguarde ${remaining}s`

  const disabled = request.isPending || active || remaining > 0

  const rateErr = request.error instanceof ApiError && request.error.status === 429
  const otherErr = request.error && !rateErr ? request.error.message : null

  let info: string | null = null
  let tone: 'ok' | 'error' | 'busy' | null = null
  if (active && run) {
    const since = run.started_at ? Math.max(0, Math.floor((now - Date.parse(run.started_at)) / 1000)) : null
    info =
      run.status === 'pending'
        ? 'Aguardando o worker'
        : `Em andamento${since !== null ? ` há ${since}s` : ''}`
    const s = summarize(run.stats)
    if (s) info += ` — ${s}`
    tone = 'busy'
  } else if (otherErr) {
    info = `Não foi possível pedir o sync: ${otherErr}`
    tone = 'error'
  } else if (remaining > 0) {
    info = 'Sync manual em intervalo mínimo; tente de novo em instantes'
  } else if (run?.status === 'failed') {
    info = `Último sync falhou${run.error ? `: ${run.error}` : ''}`
    tone = 'error'
  } else if (run?.status === 'succeeded' || run?.status === 'partial') {
    info = `Último sync${run.status === 'partial' ? ' (parcial)' : ''}: ${formatDateTime(run.finished_at)}`
    if (run.status === 'partial' && run.error) info += ` — ${run.error}`
    const s = summarize(run.stats)
    if (s) info += ` — ${s}`
    tone = run.status === 'partial' ? 'error' : 'ok'
  } else if (latest.isError) {
    info = 'Status do sync indisponível'
    tone = 'error'
  }

  return (
    <div className="sync">
      <button type="button" onClick={click} disabled={disabled} aria-busy={active}>
        {label}
      </button>
      {active && (
        <div className="sync-bar" role="progressbar" aria-label="Sync em andamento">
          <div className="sync-bar-fill" />
        </div>
      )}
      {info && (
        <span className={`sync-info${tone ? ` sync-info--${tone}` : ''}`} role="status">
          {info}
        </span>
      )}
    </div>
  )
}
