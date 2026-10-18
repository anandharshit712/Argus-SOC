import type { ReactNode } from 'react'
import BorderGlow from './BorderGlow.tsx'

const GREEN = ['#22c55e', '#4ade6a', '#bbf7d0']
const AMBER = ['#d99a1a', '#f0c040', '#fde68a']

/**
 * The app's standard card glow: the border lights up near the pointer, on hover only.
 * `className` lands on the wrapper (e.g. a grid area); the card inside fills it.
 */
export default function GlowFrame({
  children,
  className,
  warn = false,
  radius = 10,
}: {
  children: ReactNode
  className?: string
  warn?: boolean
  radius?: number
}) {
  return (
    <BorderGlow
      className={className}
      edgeSensitivity={45}
      glowColor={warn ? '45 86 55' : '134 68 58'}
      borderRadius={radius}
      glowRadius={28}
      glowIntensity={1}
      coneSpread={30}
      animated={false}
      colors={warn ? AMBER : GREEN}
      borderWidth={1.5}
    >
      {children}
    </BorderGlow>
  )
}
