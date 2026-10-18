import { useRef, type CSSProperties, type PointerEvent, type ReactNode } from 'react'
import './BorderGlow.css'

/*
 * Wraps a card and lights up the part of its border nearest the pointer, with a
 * soft glow outside it, only while hovering. Prop names follow the React Bits
 * "Border Glow" component. Pointer tracking writes CSS variables directly, so
 * moving the mouse does not re-render React.
 */

type BorderGlowProps = {
  children: ReactNode
  className?: string
  /** 0..100: how far from the edge (as % of half the card) the glow starts to show. */
  edgeSensitivity?: number
  /** Glow colour as space-separated HSL, e.g. "134 70 60". */
  glowColor?: string
  /** Kept for API parity; the wrapped card paints its own background. */
  backgroundColor?: string
  borderRadius?: number
  /** Blur radius (px) of the outer glow. */
  glowRadius?: number
  glowIntensity?: number
  /** Half-width (deg) of the lit arc of the border. */
  coneSpread?: number
  /** Light sweeps round the border by itself while hovered. */
  animated?: boolean
  /** Border-light colours, from the arc's edge to its centre and back. */
  colors?: string[]
  /** Width (px) of the lit border; match the card's own border. */
  borderWidth?: number
}

export default function BorderGlow({
  children,
  className,
  edgeSensitivity = 30,
  glowColor = '40 80 80',
  borderRadius = 28,
  glowRadius = 40,
  glowIntensity = 1,
  coneSpread = 25,
  animated = false,
  colors = ['#c084fc', '#f472b6', '#38bdf8'],
  borderWidth = 1,
}: BorderGlowProps) {
  const ref = useRef<HTMLDivElement>(null)

  const track = (e: PointerEvent<HTMLDivElement>) => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const dx = e.clientX - (r.left + r.width / 2)
    const dy = e.clientY - (r.top + r.height / 2)
    // 0 at the centre, 1 on the edge (whichever edge is closer, relatively).
    const reach = Math.max(Math.abs(dx) / (r.width / 2), Math.abs(dy) / (r.height / 2))
    const band = Math.min(Math.max(edgeSensitivity, 1), 100) / 100
    const edge = Math.min(Math.max((reach - (1 - band)) / band, 0), 1)
    const angle = (Math.atan2(dx, -dy) * 180) / Math.PI // 0deg = up, clockwise, like conic-gradient
    el.style.setProperty('--bg-angle', `${angle}deg`)
    el.style.setProperty('--bg-edge', animated ? '1' : edge.toFixed(3))
  }
  const leave = () => ref.current?.style.setProperty('--bg-edge', '0')

  const stops = colors.length > 0 ? colors : ['#ffffff']
  // Arc: transparent -> colours -> transparent over 2 * coneSpread degrees.
  const arc = [
    'transparent 0deg',
    ...stops.map((c, i) => `${c} ${((i + 1) / (stops.length + 1)) * 2 * coneSpread}deg`),
    `transparent ${2 * coneSpread}deg`,
  ].join(', ')

  const style = {
    '--bg-radius': `${borderRadius}px`,
    '--bg-spread': `${coneSpread}deg`,
    '--bg-arc': arc,
    '--bg-glow': glowColor,
    '--bg-blur': `${glowRadius / 2}px`,
    '--bg-intensity': glowIntensity,
    '--bg-width': `${borderWidth}px`,
  } as CSSProperties

  return (
    <div
      ref={ref}
      className={`border-glow${animated ? ' border-glow--animated' : ''}${className ? ` ${className}` : ''}`}
      style={style}
      onPointerMove={track}
      onPointerEnter={track}
      onPointerLeave={leave}
    >
      <span className="border-glow__glow" aria-hidden="true" />
      {children}
      <span className="border-glow__edge" aria-hidden="true" />
    </div>
  )
}
