const STATUS_TONES: Record<string, string> = {
  open: 'gray',
  custom: 'blue',
  done: 'green',
  closed: 'dgreen',
}

const PRIORITY_TONES: Record<string, string> = {
  urgent: 'red',
  high: 'amber',
  normal: 'blue',
  low: 'gray',
}

function Pill({ tone, children }: { tone: string; children: string }) {
  return <span className={`pill pill--${tone}`}>{children}</span>
}

export function StatusBadge({ status, type }: { status: string | null; type: string | null }) {
  if (!status) return <>—</>
  return <Pill tone={(type && STATUS_TONES[type.toLowerCase()]) || 'neutral'}>{status}</Pill>
}

export function PriorityBadge({ priority }: { priority: string | null }) {
  if (!priority) return <>—</>
  return <Pill tone={PRIORITY_TONES[priority.toLowerCase()] ?? 'neutral'}>{priority}</Pill>
}
