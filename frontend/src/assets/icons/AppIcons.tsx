// Paths do Simple Icons (CC0). viewBox 24x24, cor herdada de currentColor.
import type { SVGProps } from 'react'

export type IconComponent = (props: SVGProps<SVGSVGElement>) => React.JSX.Element

export const ClickUpIcon: IconComponent = (props) => (
  <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false" {...props}>
    <path d="m2 18.439 3.69-2.828c1.961 2.56 4.044 3.739 6.363 3.739 2.307 0 4.33-1.166 6.203-3.704L22 18.405C19.298 22.065 15.941 24 12.053 24 8.178 24 4.788 22.078 2 18.439M12.04 6.15l-6.568 5.66-3.036-3.52L12.055 0l9.543 8.296-3.05 3.509z" />
  </svg>
)

export const GitLabIcon: IconComponent = (props) => (
  <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false" {...props}>
    <path d="m23.6 9.593-.033-.086L20.3.98a.85.85 0 0 0-.336-.405.875.875 0 0 0-1 .054.88.88 0 0 0-.29.44L16.47 7.818H7.537L5.333 1.07a.86.86 0 0 0-.29-.441.875.875 0 0 0-1-.054.86.86 0 0 0-.336.405L.433 9.502l-.032.086a6.066 6.066 0 0 0 2.012 7.01l.01.009.03.021 4.977 3.727 2.462 1.863 1.5 1.132a1.01 1.01 0 0 0 1.22 0l1.499-1.132 2.461-1.863 5.006-3.75.013-.01a6.07 6.07 0 0 0 2.01-7.002" />
  </svg>
)
