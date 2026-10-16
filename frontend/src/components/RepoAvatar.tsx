import { useState } from 'react'

const COLORS = ['gray', 'blue', 'green', 'red', 'amber'] as const

function colorOf(name: string): (typeof COLORS)[number] {
  let h = 0
  for (const ch of name) h = (h * 31 + ch.codePointAt(0)!) >>> 0
  return COLORS[h % COLORS.length]
}

interface Props {
  id: number | string
  name: string
  avatarUpdatedAt: string | null | undefined
}

/** Ícone de 20 px do repositório; sem ícone (ou se falhar), quadrado com a inicial. */
export function RepoAvatar({ id, name, avatarUpdatedAt }: Props) {
  const [failedFor, setFailedFor] = useState<string | null>(null)
  if (avatarUpdatedAt && failedFor !== avatarUpdatedAt) {
    return (
      <img
        className="repo-avatar"
        src={`/api/v1/repositories/${id}/avatar?v=${encodeURIComponent(avatarUpdatedAt)}`}
        alt=""
        loading="lazy"
        onError={() => setFailedFor(avatarUpdatedAt)}
      />
    )
  }
  const base = name.split('/').pop() || name
  const initial = (base.trim().charAt(0) || '?').toUpperCase()
  return (
    <span className={`repo-avatar repo-avatar--${colorOf(name)}`} aria-hidden="true">
      {initial}
    </span>
  )
}
