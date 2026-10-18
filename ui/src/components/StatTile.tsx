import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import Icon from './Icon.tsx'
import './StatTile.css'

type StatTileProps = {
  label: string
  value: string
  /** Extra text after the value, e.g. "(38%)". */
  suffix?: string
  /** Change vs the previous window. Null hides the line. */
  delta: number | null
  /** Unit after the delta number, e.g. " s". */
  deltaUnit?: string
  /** Where a click goes. Omit for a tile that is not a link. */
  to?: string
  /** Amber accent, used when something needs a human. */
  warn?: boolean
  /** Recent readings, oldest first, drawn as a small line. Needs two or more. */
  trend?: number[]
}

const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

function DeltaLine({ delta, unit = '' }: { delta: number; unit?: string }) {
  const icon = delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat'
  const text = delta === 0 ? 'no change' : `${Math.abs(delta)}${unit} vs previous window`
  return (
    <span className="tile-delta">
      <Icon name={icon} size={14} />
      <span className="visually-hidden">{delta > 0 ? 'up ' : delta < 0 ? 'down ' : ''}</span>
      {text}
    </span>
  )
}

/** Whole numbers count up (or down) to their new value; anything else is shown as is. */
function CountingValue({ value }: { value: string }) {
  const target = /^\d+$/.test(value) ? Number(value) : null
  const [shown, setShown] = useState(0)
  const from = useRef(0)

  useEffect(() => {
    if (target === null) return
    const start = from.current
    if (start === target || reducedMotion()) {
      from.current = target
      setShown(target)
      return
    }
    const began = performance.now()
    const duration = 700
    let raf = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - began) / duration)
      const eased = 1 - (1 - t) ** 3
      setShown(Math.round(start + (target - start) * eased))
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(raf)
      from.current = target
    }
  }, [target])

  return <>{target === null ? value : shown}</>
}

/** Small line of recent readings; a flat line when nothing changed. */
function Sparkline({ points }: { points: number[] }) {
  const W = 100
  const H = 24
  const min = Math.min(...points)
  const max = Math.max(...points)
  const span = max - min
  const xy = points.map((v, i) => {
    const x = (i / (points.length - 1)) * W
    const y = span === 0 ? H / 2 : H - 2 - ((v - min) / span) * (H - 4)
    return [x, y] as const
  })
  const line = xy.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  return (
    <svg className="tile-spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
      <path d={`${line} L${W},${H} L0,${H} Z`} className="tile-spark-area" />
      <path d={line} className="tile-spark-line" />
    </svg>
  )
}

export default function StatTile({ label, value, suffix, delta, deltaUnit, to, warn, trend }: StatTileProps) {
  // Flash the tile when its value changes after the first load.
  const previous = useRef(value)
  const [flash, setFlash] = useState(0)
  useEffect(() => {
    if (previous.current !== value) {
      previous.current = value
      if (!reducedMotion()) setFlash((n) => n + 1)
    }
  }, [value])

  const body = (
    <>
      {flash > 0 && <span key={flash} className="tile-flash" aria-hidden="true" />}
      <span className="tile-label">{label}</span>
      <span className="tile-value">
        <CountingValue value={value} />
        {suffix && <small>{suffix}</small>}
      </span>
      {delta !== null ? <DeltaLine delta={delta} unit={deltaUnit} /> : <span className="tile-delta">&nbsp;</span>}
      {trend && trend.length > 1 && <Sparkline points={trend} />}
    </>
  )
  const className = `stat-tile${warn ? ' is-warn' : ''}`
  return to ? (
    <Link to={to} className={className} aria-label={`${label}: ${value}${suffix ? ` ${suffix}` : ''}`}>
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  )
}
