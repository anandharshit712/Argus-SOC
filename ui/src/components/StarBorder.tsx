import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ElementType,
  type HTMLAttributes,
  type PointerEvent,
  type ReactNode,
} from 'react'
import './StarBorder.css'

/*
 * A glowing "star" with a fading trail that travels around the element's
 * border. Prop names follow the React Bits "Star Border" component. The comet
 * is an SVG overlay drawn over the element's own CSS border, so the element
 * keeps its layout and styling. Positions are driven by requestAnimationFrame
 * from the measured perimeter, so the comet stays in one piece when the
 * element resizes.
 */

type StarBorderProps = {
  as?: ElementType
  className?: string
  children?: ReactNode
  color?: string
  trailColor?: string
  duration?: number
  direction?: 'clockwise' | 'counterclockwise'
  stars?: number
  trailLength?: number
  thickness?: number
  /** Width of the element's own CSS border, so the comet sits centred on it. Defaults to `thickness`. */
  borderWidth?: number
  radius?: number
  glow?: number
  /** 'lap': on hover the star speeds up for one lap. */
  hover?: 'lap' | 'none'
  sparkle?: boolean
  clickPulse?: boolean
  theme?: 'dark' | 'light'
} & Omit<HTMLAttributes<HTMLElement>, 'color'>

type Geometry = { d: string; perimeter: number }

const TRAIL_SEGMENTS = 18
const HEAD_FRACTION = 0.008 // head length as a share of the perimeter
const LAP_SPEEDUP = 3

/** Rounded-rect path (clockwise from the top-left corner) and its exact length in px. */
function roundedRect(w: number, h: number, inset: number, r: number): Geometry {
  const x0 = inset
  const y0 = inset
  const x1 = w - inset
  const y1 = h - inset
  const rr = Math.max(0, Math.min(r, (x1 - x0) / 2, (y1 - y0) / 2))
  const d = [
    `M${x0 + rr},${y0}`,
    `H${x1 - rr}`,
    `A${rr},${rr} 0 0 1 ${x1},${y0 + rr}`,
    `V${y1 - rr}`,
    `A${rr},${rr} 0 0 1 ${x1 - rr},${y1}`,
    `H${x0 + rr}`,
    `A${rr},${rr} 0 0 1 ${x0},${y1 - rr}`,
    `V${y0 + rr}`,
    `A${rr},${rr} 0 0 1 ${x0 + rr},${y0}`,
    'Z',
  ].join(' ')
  const perimeter = 2 * (x1 - x0 + (y1 - y0)) - 8 * rr + 2 * Math.PI * rr
  return { d, perimeter }
}

export default function StarBorder({
  as: Tag = 'div',
  className,
  children,
  color = '#ffffff',
  trailColor = '#ffffff',
  duration = 4,
  direction = 'clockwise',
  stars = 1,
  trailLength = 0.3,
  thickness = 1,
  borderWidth,
  radius = 12,
  glow = 0.6,
  hover = 'lap',
  sparkle = false,
  clickPulse = true,
  onPointerEnter,
  onPointerDown,
  style,
  ...rest
}: StarBorderProps) {
  const hostRef = useRef<HTMLElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const lapRef = useRef(0) // remaining boosted distance, in laps
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [pulse, setPulse] = useState(0)

  useLayoutEffect(() => {
    const el = hostRef.current
    if (el) setSize({ w: el.offsetWidth, h: el.offsetHeight })
  }, [])

  useEffect(() => {
    const el = hostRef.current
    if (!el) return
    const observer = new ResizeObserver(() => setSize({ w: el.offsetWidth, h: el.offsetHeight }))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const { w, h } = size
  const inset = (borderWidth ?? thickness) / 2
  const geo = w > 0 && h > 0 ? roundedRect(w, h, inset, radius - inset) : null
  const P = geo?.perimeter ?? 0
  const trailPx = Math.min(Math.max(trailLength, 0.02), 0.9) * P
  const headPx = Math.max(HEAD_FRACTION * P, thickness * 4)
  const seg = trailPx / TRAIL_SEGMENTS
  const starCount = Math.max(1, Math.round(stars))

  // Drive every dash from one clock: dash offset = -(position along the loop).
  useEffect(() => {
    const svg = svgRef.current
    if (!svg || P <= 0) return
    const dashes = [...svg.querySelectorAll<SVGPathElement>('[data-sb-pos]')].map((el) => ({
      el,
      pos: Number(el.dataset.sbPos),
    }))
    const place = (progress: number) => {
      for (const { el, pos } of dashes) {
        const at = (((progress + pos / P) % 1) + 1) % 1
        el.style.strokeDashoffset = String(-at * P)
      }
    }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      place(0)
      return
    }
    let progress = 0
    let last = performance.now()
    let raf = 0
    const tick = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.1)
      last = now
      let step = dt / Math.max(duration, 0.1)
      if (lapRef.current > 0) {
        step *= LAP_SPEEDUP
        lapRef.current = Math.max(0, lapRef.current - step)
      }
      progress = (progress + step) % 1
      place(progress)
      raf = requestAnimationFrame(tick)
    }
    place(0)
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [P, duration, starCount, trailPx, headPx])

  const handleEnter = (e: PointerEvent<HTMLElement>) => {
    onPointerEnter?.(e)
    if (hover === 'lap' && lapRef.current === 0) lapRef.current = 1
  }
  const handleDown = (e: PointerEvent<HTMLElement>) => {
    onPointerDown?.(e)
    // A click inside a nested StarBorder pulses only the innermost one.
    if (clickPulse && (e.target as Element).closest('.star-border') === e.currentTarget) {
      setPulse((n) => n + 1)
    }
  }

  const dash = (len: number) => `${len} ${Math.max(P - len, 0)}`
  const flip = direction === 'counterclockwise' ? `translate(${w} 0) scale(-1 1)` : undefined

  return (
    <Tag
      ref={hostRef}
      className={`star-border${className ? ` ${className}` : ''}`}
      style={{ ...style, '--sb-glow': `${Math.max(0, glow) * 6}px`, '--sb-color': color } as CSSProperties}
      onPointerEnter={handleEnter}
      onPointerDown={handleDown}
      {...rest}
    >
      {children}
      {geo && (
        <svg ref={svgRef} className="star-border__svg" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
          <g transform={flip}>
            {pulse > 0 && (
              <path
                key={`pulse-${pulse}`}
                d={geo.d}
                className="star-border__pulse"
                stroke={color}
                strokeWidth={thickness}
                onAnimationEnd={() => setPulse(0)}
              />
            )}
            <g className="star-border__glow">
              {Array.from({ length: starCount }, (_, k) => {
                const base = (k * P) / starCount
                return (
                  <g key={k}>
                    {Array.from({ length: TRAIL_SEGMENTS }, (_, i) => {
                      const t = (i + 1) / TRAIL_SEGMENTS
                      return (
                        <path
                          key={i}
                          d={geo.d}
                          data-sb-pos={base + P - headPx - trailPx + i * seg}
                          className="star-border__dash"
                          stroke={trailColor}
                          strokeWidth={thickness}
                          strokeOpacity={t * t * 0.85}
                          strokeDasharray={dash(seg + 0.5)}
                        />
                      )
                    })}
                    <path
                      d={geo.d}
                      data-sb-pos={base + P - headPx}
                      className={`star-border__dash star-border__head${sparkle ? ' star-border__head--sparkle' : ''}`}
                      stroke={color}
                      strokeWidth={thickness + 0.5}
                      strokeDasharray={dash(headPx)}
                    />
                  </g>
                )
              })}
            </g>
          </g>
        </svg>
      )}
    </Tag>
  )
}
