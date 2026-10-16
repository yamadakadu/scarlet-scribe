import type { ReactNode } from 'react'
import { ArrowUpRightIcon } from '../assets/icons/UiIcons.tsx'

/** Link para fora do app: abre em outra aba e traz o ícone de seta. */
export function ExternalLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a className="ext-link" href={href} target="_blank" rel="noopener noreferrer">
      {children}
      <ArrowUpRightIcon className="ext-link-icon" />
    </a>
  )
}
