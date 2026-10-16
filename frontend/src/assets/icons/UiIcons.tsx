// Ícones de interface (traço simples). viewBox 24x24, cor herdada de currentColor.
import type { SVGProps } from 'react'
import type { IconComponent } from './AppIcons.tsx'

const stroke = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
  focusable: false,
} as const satisfies SVGProps<SVGSVGElement>

export const ArrowUpRightIcon: IconComponent = (props) => (
  <svg {...stroke} {...props}>
    <path d="M7 17 17 7M8 7h9v9" />
  </svg>
)

export const ArrowLeftIcon: IconComponent = (props) => (
  <svg {...stroke} {...props}>
    <path d="M19 12H5M11 6l-6 6 6 6" />
  </svg>
)

export const ChevronRightIcon: IconComponent = (props) => (
  <svg {...stroke} {...props}>
    <path d="m9 6 6 6-6 6" />
  </svg>
)

export const CopyIcon: IconComponent = (props) => (
  <svg {...stroke} {...props}>
    <rect x="9" y="9" width="11" height="11" rx="2" />
    <path d="M5 15V6a2 2 0 0 1 2-2h9" />
  </svg>
)

export const CheckIcon: IconComponent = (props) => (
  <svg {...stroke} {...props}>
    <path d="m5 12 5 5 9-10" />
  </svg>
)

export const TagIcon: IconComponent = (props) => (
  <svg {...stroke} {...props}>
    <path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z" />
    <circle cx="8" cy="8" r="1.5" />
  </svg>
)

export const CloseIcon: IconComponent = (props) => (
  <svg {...stroke} {...props}>
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
)
