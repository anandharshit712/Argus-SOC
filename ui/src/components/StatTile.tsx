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
  /** Where a click goes. Omit for a tile that is not a link. */
  to?: string
  /** Amber accent, used when something needs a human. */
  warn?: boolean
}

function DeltaLine({ delta }: { delta: number }) {
  const icon = delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat'
  const text = delta === 0 ? 'no change' : `${Math.abs(delta)} vs previous`
  return (
    <span className="tile-delta">
      <Icon name={icon} size={14} />
      <span className="visually-hidden">{delta > 0 ? 'up ' : delta < 0 ? 'down ' : ''}</span>
      {text}
    </span>
  )
}

export default function StatTile({ label, value, suffix, delta, to, warn }: StatTileProps) {
  const body = (
    <>
      <span className="tile-label">{label}</span>
      <span className="tile-value">
        {value}
        {suffix && <small>{suffix}</small>}
      </span>
      {delta !== null ? <DeltaLine delta={delta} /> : <span className="tile-delta">&nbsp;</span>}
    </>
  )
  const className = `stat-tile${warn ? ' is-warn' : ''}`
  return to ? (
    <Link to={to} className={className}>{body}</Link>
  ) : (
    <div className={className}>{body}</div>
  )
}
