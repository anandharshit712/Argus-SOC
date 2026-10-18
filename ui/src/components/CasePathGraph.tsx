import { useState, type CSSProperties } from 'react'
import type { PathNode } from '../api/apiTypes.ts'

type CasePathGraphProps = {
  path: PathNode[]
  /** Hosts and accounts the decision acts on (isolate / disable): highlighted. */
  targets?: string[]
  /** The path ends on a crown-jewel host (findings.path_to_crown_jewel). */
  endsOnCrownJewel?: boolean
  /** [host, score 0..1] from the decision, shown in a node's details. */
  ranking?: [string, number][]
}

const WIDTH = 640
const HEIGHT = 260
const MARGIN = 60
const NODE = 22 // half the node size; edges stop at the node's edge
const STEP_S = 0.45 // seconds between hops when the path draws itself

// Left to right, zig-zag so long names do not collide (UI_PAGES §4.4).
// Host = rounded box, User = circle; the crown jewel gets a star; decision targets are ringed.
// The path draws itself hop by hop, a pulse then runs along it, and each node shows its
// details on hover or keyboard focus.
export default function CasePathGraph({ path, targets = [], endsOnCrownJewel = true, ranking = [] }: CasePathGraphProps) {
  const [run, setRun] = useState(0) // bump to replay the drawing
  const [active, setActive] = useState<number | null>(null)
  if (path.length === 0) return <p className="muted">No path to a crown jewel within 6 hops</p>

  const step = path.length > 1 ? (WIDTH - MARGIN * 2) / (path.length - 1) : 0
  const points = path.map((node, i) => ({
    node,
    x: path.length > 1 ? MARGIN + i * step : WIDTH / 2,
    y: HEIGHT / 2 + (path.length > 2 ? (i % 2 === 0 ? -34 : 34) : 0),
  }))
  const last = points.length - 1
  const targetSet = new Set(targets)
  const scores = new Map(ranking)
  const route = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ')
  const drawn = (last + 1) * STEP_S

  const roles = (i: number) => {
    const name = points[i].node.name
    return [
      i === 0 && last > 0 ? 'Entry point' : null,
      i === last && last > 0 && endsOnCrownJewel ? 'Crown jewel' : null,
      targetSet.has(name) ? 'Action target' : null,
    ].filter((r): r is string => r !== null)
  }
  const shown = active !== null ? points[active] : null

  return (
    <div className="path-graph-wrap">
      <div className="path-graph-bar">
        <ul className="path-legend" aria-label="Legend">
          <li><i className="lg-entry" /> Entry</li>
          <li><i className="lg-jewel" /> Crown jewel</li>
          <li><i className="lg-target" /> Action target</li>
          <li><i className="lg-user" /> User</li>
        </ul>
        {last > 0 && (
          <button type="button" className="path-replay" onClick={() => setRun((n) => n + 1)}>
            ▶ Replay path
          </button>
        )}
      </div>

      <div className="path-graph-canvas">
        <svg
          key={run}
          className="path-graph"
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-label={`Attack path: ${path.map((n) => `${n.name} (${n.label})`).join(' to ')}`}
        >
          <defs>
            <marker id="path-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M0 0L10 5L0 10z" fill="#7d9a89" />
            </marker>
            <filter id="path-packet-glow" x="-200%" y="-200%" width="500%" height="500%">
              <feGaussianBlur stdDeviation="3" />
            </filter>
          </defs>

          {points.slice(1).map((p, i) => {
            const from = points[i]
            const dx = p.x - from.x
            const dy = p.y - from.y
            const len = Math.hypot(dx, dy) || 1
            const pad = NODE + 6
            return (
              <line
                key={`${from.node.name}-${p.node.name}`}
                x1={from.x + (dx / len) * pad}
                y1={from.y + (dy / len) * pad}
                x2={p.x - (dx / len) * pad}
                y2={p.y - (dy / len) * pad}
                className="path-edge"
                style={{ '--d': `${(i + 0.6) * STEP_S}s` } as CSSProperties}
                markerEnd="url(#path-arrow)"
              />
            )
          })}

          {/* A pulse that runs along the path once it is drawn, then keeps looping. */}
          {last > 0 && (
            <g className="path-packet" style={{ '--d': `${drawn}s` } as CSSProperties} aria-hidden="true">
              <circle r="9" className="path-packet-halo" filter="url(#path-packet-glow)">
                <animateMotion dur={`${Math.max(2.4, last * 0.9)}s`} begin={`${drawn}s`} repeatCount="indefinite" path={route} />
              </circle>
              <circle r="4.5" className="path-packet-core">
                <animateMotion dur={`${Math.max(2.4, last * 0.9)}s`} begin={`${drawn}s`} repeatCount="indefinite" path={route} />
              </circle>
            </g>
          )}

          {points.map((p, i) => {
            const isUser = p.node.label === 'User'
            const jewel = i === last && last > 0 && endsOnCrownJewel
            const target = targetSet.has(p.node.name)
            const above = p.y <= HEIGHT / 2
            const classes = [
              'path-node',
              isUser ? 'is-user' : 'is-host',
              jewel && 'is-jewel',
              i === 0 && last > 0 && 'is-entry',
              target && 'is-target',
              active === i && 'is-active',
            ]
            const nameY = above ? p.y - NODE - 14 : p.y + NODE + 28
            const labelY = above ? p.y - NODE - 38 : p.y + NODE + 50
            // The end nodes' labels grow inwards so they never leave the drawing.
            const anchor = last === 0 ? 'middle' : i === 0 ? 'start' : i === last ? 'end' : 'middle'
            const textX = anchor === 'start' ? p.x - NODE : anchor === 'end' ? p.x + NODE : p.x
            return (
              <g
                key={p.node.name}
                className={classes.filter(Boolean).join(' ')}
                style={{ '--d': `${i * STEP_S}s`, transformOrigin: `${p.x}px ${p.y}px` } as CSSProperties}
                tabIndex={0}
                aria-label={`Hop ${i + 1} of ${last + 1}: ${p.node.name}, ${p.node.label}${roles(i).length ? `, ${roles(i).join(', ')}` : ''}`}
                onMouseEnter={() => setActive(i)}
                onMouseLeave={() => setActive(null)}
                onFocus={() => setActive(i)}
                onBlur={() => setActive(null)}
              >
                {target &&
                  (isUser ? (
                    <circle cx={p.x} cy={p.y} r={NODE + 6} className="target-ring" />
                  ) : (
                    <rect x={p.x - NODE - 6} y={p.y - NODE - 6} width={(NODE + 6) * 2} height={(NODE + 6) * 2} rx="12" className="target-ring" />
                  ))}
                {isUser ? (
                  <circle cx={p.x} cy={p.y} r={NODE} className="path-shape" />
                ) : (
                  <rect x={p.x - NODE} y={p.y - NODE} width={NODE * 2} height={NODE * 2} rx="8" className="path-shape" />
                )}
                {jewel && (
                  <text x={p.x} y={p.y + 7} textAnchor="middle" className="path-star" aria-hidden="true">
                    ★
                  </text>
                )}
                <text x={textX} y={nameY} textAnchor={anchor} className="path-name">
                  {p.node.name}
                </text>
                <text x={textX} y={labelY} textAnchor={anchor} className="path-label">
                  {[p.node.label, i === 0 && last > 0 ? 'entry' : null, jewel ? 'crown jewel' : null, target ? 'action target' : null]
                    .filter(Boolean)
                    .join(' · ')}
                </text>
              </g>
            )
          })}
        </svg>

        {shown && active !== null && (
          <div
            className={`path-tip${shown.y <= HEIGHT / 2 ? ' is-below' : ''}`}
            style={{ left: `${(shown.x / WIDTH) * 100}%`, top: `${(shown.y / HEIGHT) * 100}%` }}
            role="tooltip"
          >
            <strong>{shown.node.name}</strong>
            <span>
              {shown.node.label} · hop {active + 1} of {last + 1}
            </span>
            {roles(active).length > 0 && <span className="path-tip-roles">{roles(active).join(' · ')}</span>}
            {scores.has(shown.node.name) && <span>Risk score {(scores.get(shown.node.name) as number).toFixed(2)}</span>}
          </div>
        )}
      </div>
    </div>
  )
}
