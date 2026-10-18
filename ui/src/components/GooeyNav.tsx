import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent,
  type ReactNode,
} from 'react'
import './GooeyNav.css'

/*
 * Navigation with a "gooey" active pill: when the selection changes, the pill
 * slides to the new item with a little overshoot while a shrinking ghost stays
 * behind and droplets burst off it, all merged by an SVG goo filter. Prop names
 * follow the React Bits "Gooey Nav" component; this version also runs
 * vertically and can be controlled (activeIndex) so a router can drive it.
 */

export type GooeyNavItem = {
  label: string
  href: string
  icon?: ReactNode
  /** Extra content after the label (e.g. a count badge). */
  badge?: ReactNode
}

type GooeyNavProps = {
  items: GooeyNavItem[]
  /** Controlled selection; -1 hides the pill. Overrides initialActiveIndex. */
  activeIndex?: number
  initialActiveIndex?: number
  orientation?: 'horizontal' | 'vertical'
  theme?: 'dark' | 'light'
  size?: 'sm' | 'md' | 'lg'
  frame?: boolean
  particleCount?: number
  /** How far (px) droplets fly from the pill. */
  spread?: number
  animationTime?: number
  timeVariance?: number
  /** 0..1: how much the shapes melt together. */
  gooeyness?: number
  /** 0..1: overshoot of the pill when it arrives. */
  wobble?: number
  hoverEffect?: boolean
  /** Pill colour (drawn translucent). */
  color?: string
  /** Droplet colours. */
  particleColors?: string[]
  className?: string
  ariaLabel?: string
  onChange?: (index: number, item: GooeyNavItem) => void
}

type Box = { x: number; y: number; w: number; h: number }
type Particle = { id: number; x: number; y: number; dx: number; dy: number; r: number; color: string; ms: number; delay: number }
type Ghost = { id: number; box: Box; ms: number }

let nextId = 0

export default function GooeyNav({
  items,
  activeIndex,
  initialActiveIndex = 0,
  orientation = 'horizontal',
  theme = 'dark',
  size = 'md',
  frame = false,
  particleCount = 15,
  spread = 56,
  animationTime = 600,
  timeVariance = 300,
  gooeyness = 0.5,
  wobble = 0.5,
  hoverEffect = true,
  color = '#4ade6a',
  particleColors = ['#4ade6a', '#22c55e', '#86efac'],
  className,
  ariaLabel = 'Navigation',
  onChange,
}: GooeyNavProps) {
  const filterId = `goo-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const rootRef = useRef<HTMLElement>(null)
  const itemRefs = useRef<(HTMLAnchorElement | null)[]>([])
  const [ownIndex, setOwnIndex] = useState(initialActiveIndex)
  const current = activeIndex ?? ownIndex
  const [box, setBox] = useState<Box | null>(null)
  const [animate, setAnimate] = useState(false)
  const [particles, setParticles] = useState<Particle[]>([])
  const [ghosts, setGhosts] = useState<Ghost[]>([])
  const prev = useRef<{ index: number; box: Box | null }>({ index: current, box: null })
  // Burst settings, read when the selection changes (kept out of effect deps on purpose).
  const burstRef = useRef({ animationTime, particleCount, spread, timeVariance, orientation, particleColors })
  burstRef.current = { animationTime, particleCount, spread, timeVariance, orientation, particleColors }

  const measure = useCallback((index: number): Box | null => {
    const root = rootRef.current
    const el = itemRefs.current[index]
    if (!root || !el) return null
    return { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight }
  }, [])

  // Place the pill; animate only when the selection changes after the first paint.
  useLayoutEffect(() => {
    const { animationTime, particleCount, spread, timeVariance, orientation, particleColors } = burstRef.current
    const next = current >= 0 ? measure(current) : null
    const before = prev.current
    const changed = before.index !== current && before.box !== null && next !== null
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    setAnimate(changed && !reduced)
    setBox(next)
    if (changed && !reduced && next && before.box) {
      const ms = animationTime
      setGhosts((g) => [...g, { id: nextId++, box: before.box as Box, ms }])
      const cx = next.x + next.w / 2
      const cy = next.y + next.h / 2
      const burst: Particle[] = Array.from({ length: Math.max(0, Math.round(particleCount)) }, (_, i) => {
        const angle = (i / particleCount) * Math.PI * 2 + Math.random() * 0.6
        const dist = spread * (0.45 + Math.random() * 0.55)
        // Start spread along the pill's long side so droplets leave from its whole edge.
        const along = (Math.random() - 0.5) * (orientation === 'vertical' ? next.w * 0.7 : next.w * 0.6)
        return {
          id: nextId++,
          x: cx + along,
          y: cy,
          // Vertical lists have little room sideways, so droplets fly mostly up and down.
          dx: Math.cos(angle) * dist * (orientation === 'vertical' ? 0.45 : 1),
          dy: Math.sin(angle) * dist * (orientation === 'vertical' ? 0.8 : 0.55),
          r: 3 + Math.random() * 5,
          color: particleColors[i % particleColors.length],
          ms: ms + Math.random() * timeVariance,
          delay: Math.random() * 80,
        }
      })
      setParticles((p) => [...p, ...burst])
    }
    prev.current = { index: current, box: next }
  }, [current, measure])

  // Keep the pill on its item when the layout changes (resize, fonts, badges).
  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    const observer = new ResizeObserver(() => {
      const next = current >= 0 ? measure(current) : null
      setAnimate(false)
      setBox(next)
      prev.current = { index: current, box: next }
    })
    observer.observe(root)
    return () => observer.disconnect()
  }, [current, measure])

  const select = (event: MouseEvent<HTMLAnchorElement>, index: number) => {
    // Let the browser handle new-tab / new-window clicks.
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return
    event.preventDefault()
    if (activeIndex === undefined) setOwnIndex(index)
    onChange?.(index, items[index])
  }

  const blur = 3 + Math.min(Math.max(gooeyness, 0), 1) * 9
  const overshoot = 1 + Math.min(Math.max(wobble, 0), 1) * 0.9
  const style = {
    '--goo-color': color,
    '--goo-ms': `${animationTime}ms`,
    '--goo-ease': `cubic-bezier(0.34, ${overshoot}, 0.64, 1)`,
  } as CSSProperties

  return (
    <nav
      ref={rootRef}
      aria-label={ariaLabel}
      className={[
        'gooey-nav',
        `gooey-nav--${orientation}`,
        `gooey-nav--${size}`,
        `gooey-nav--${theme}`,
        frame ? 'gooey-nav--frame' : '',
        hoverEffect ? 'gooey-nav--hover' : '',
        className ?? '',
      ]
        .filter(Boolean)
        .join(' ')}
      style={style}
    >
      <svg className="gooey-nav__defs" aria-hidden="true" focusable="false">
        <filter id={filterId} x="-50%" y="-50%" width="200%" height="200%" colorInterpolationFilters="sRGB">
          <feGaussianBlur in="SourceGraphic" stdDeviation={blur} result="blur" />
          <feColorMatrix in="blur" mode="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 22 -9" result="goo" />
          <feComposite in="SourceGraphic" in2="goo" operator="atop" />
        </filter>
      </svg>

      {/* Gooey layer: pill, ghost and droplets melt together under the filter. */}
      <div className="gooey-nav__goo" style={{ filter: `url(#${filterId})` }} aria-hidden="true">
        {box && (
          <span
            className={`gooey-nav__pill${animate ? ' is-moving' : ''}`}
            style={{ transform: `translate(${box.x}px, ${box.y}px)`, width: box.w, height: box.h }}
          />
        )}
        {ghosts.map((g) => (
          <span
            key={g.id}
            className="gooey-nav__ghost"
            style={{
              transform: `translate(${g.box.x}px, ${g.box.y}px)`,
              width: g.box.w,
              height: g.box.h,
              animationDuration: `${g.ms}ms`,
            }}
            onAnimationEnd={() => setGhosts((all) => all.filter((x) => x.id !== g.id))}
          />
        ))}
        {particles.map((p) => (
          <span
            key={p.id}
            className="gooey-nav__particle"
            style={
              {
                left: p.x - p.r,
                top: p.y - p.r,
                width: p.r * 2,
                height: p.r * 2,
                background: p.color,
                animationDuration: `${p.ms}ms`,
                animationDelay: `${p.delay}ms`,
                '--dx': `${p.dx}px`,
                '--dy': `${p.dy}px`,
              } as CSSProperties
            }
            onAnimationEnd={() => setParticles((all) => all.filter((x) => x.id !== p.id))}
          />
        ))}
      </div>

      {/* Crisp outline that follows the pill. */}
      {box && (
        <span
          className={`gooey-nav__outline${animate ? ' is-moving' : ''}`}
          style={{ transform: `translate(${box.x}px, ${box.y}px)`, width: box.w, height: box.h }}
          aria-hidden="true"
        />
      )}

      {items.map((item, i) => (
        <a
          key={item.href}
          ref={(el) => {
            itemRefs.current[i] = el
          }}
          href={item.href}
          className={`gooey-nav__item${i === current ? ' is-active' : ''}`}
          aria-current={i === current ? 'page' : undefined}
          onClick={(e) => select(e, i)}
        >
          {item.icon}
          <span className="gooey-nav__label">{item.label}</span>
          {item.badge}
        </a>
      ))}
    </nav>
  )
}
