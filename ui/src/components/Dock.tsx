import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import './Dock.css'

/*
 * macOS-style dock: tiles grow as the pointer nears them. Prop names follow the
 * React Bits "Dock" component. Rendered inline (it sits where you put it), with
 * `position` deciding which way tiles grow and where labels pop up. Context
 * menus from the original are not implemented.
 */

export type DockItem =
  | { separator: true }
  | {
      separator?: false
      icon: ReactNode
      label: string
      /** Tooltip text; defaults to `label`. */
      title?: string
      active?: boolean
      badge?: number | string
      onClick?: () => void
    }

type DockProps = {
  items: DockItem[]
  baseItemSize?: number
  magnification?: number
  panelHeight?: number
  accentColor?: string
  badgeColor?: string
  position?: 'bottom' | 'top'
  /** Pointer distance (px) over which tiles grow. */
  distance?: number
  gap?: number
  /** 0 = square corners, 1 = fully round tiles. */
  roundness?: number
  bounce?: boolean
  tiles?: boolean
  showLabels?: boolean
  showIndicators?: boolean
  showBadges?: boolean
  className?: string
  ariaLabel?: string
}

type Entry = Extract<DockItem, { icon: ReactNode }>

function DockTile({
  item,
  pointerX,
  base,
  max,
  distance,
  bounce,
  showLabels,
  showIndicators,
  showBadges,
}: {
  item: Entry
  pointerX: number | null
  base: number
  max: number
  distance: number
  bounce: boolean
  showLabels: boolean
  showIndicators: boolean
  showBadges: boolean
}) {
  const ref = useRef<HTMLButtonElement>(null)
  const [bouncing, setBouncing] = useState(false)

  let size = base
  if (pointerX !== null && ref.current) {
    const rect = ref.current.getBoundingClientRect()
    const d = Math.abs(pointerX - (rect.left + rect.width / 2))
    if (d < distance) size = base + (max - base) * Math.cos((d / distance) * (Math.PI / 2))
  }

  return (
    <button
      ref={ref}
      type="button"
      className={`dock__item${item.active ? ' is-active' : ''}${bouncing ? ' is-bouncing' : ''}`}
      style={{ '--dock-size': `${size}px` } as CSSProperties}
      aria-pressed={item.active ?? false}
      aria-label={item.title ?? item.label}
      onClick={() => {
        if (bounce) setBouncing(true)
        item.onClick?.()
      }}
      onAnimationEnd={() => setBouncing(false)}
    >
      <span className="dock__icon">{item.icon}</span>
      {showLabels && (
        <span className="dock__label" role="tooltip">
          {item.title ?? item.label}
        </span>
      )}
      {showIndicators && item.active && <span className="dock__indicator" aria-hidden="true" />}
      {showBadges && item.badge !== undefined && <span className="dock__badge">{item.badge}</span>}
    </button>
  )
}

export default function Dock({
  items,
  baseItemSize = 50,
  magnification = 70,
  panelHeight = 68,
  accentColor = '#0a84ff',
  badgeColor = '#ff453a',
  position = 'bottom',
  distance = 200,
  gap = 10,
  roundness = 0.5,
  bounce = true,
  tiles = true,
  showLabels = true,
  showIndicators = true,
  showBadges = true,
  className,
  ariaLabel = 'Dock',
}: DockProps) {
  const [pointerX, setPointerX] = useState<number | null>(null)
  const [reducedMotion, setReducedMotion] = useState(false)

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const sync = () => setReducedMotion(mq.matches)
    sync()
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])

  const max = reducedMotion ? baseItemSize : magnification
  const style = {
    '--dock-panel-h': `${panelHeight}px`,
    '--dock-gap': `${gap}px`,
    '--dock-accent': accentColor,
    '--dock-badge': badgeColor,
    '--dock-radius': `${Math.min(Math.max(roundness, 0), 1) * 50}%`,
  } as CSSProperties

  return (
    <div
      className={`dock dock--${position}${tiles ? ' dock--tiles' : ''}${className ? ` ${className}` : ''}`}
      style={style}
      role="group"
      aria-label={ariaLabel}
      onPointerMove={(e) => e.pointerType === 'mouse' && setPointerX(e.clientX)}
      onPointerLeave={() => setPointerX(null)}
    >
      {items.map((item, i) =>
        item.separator ? (
          <span key={`sep-${i}`} className="dock__separator" aria-hidden="true" />
        ) : (
          <DockTile
            key={item.label}
            item={item}
            pointerX={pointerX}
            base={baseItemSize}
            max={max}
            distance={distance}
            bounce={bounce && !reducedMotion}
            showLabels={showLabels}
            showIndicators={showIndicators}
            showBadges={showBadges}
          />
        ),
      )}
    </div>
  )
}
