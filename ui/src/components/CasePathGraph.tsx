import type { PathNode } from '../api/apiTypes.ts'

type CasePathGraphProps = {
  path: PathNode[]
  /** Hosts and accounts the decision acts on (isolate / disable): highlighted. */
  targets?: string[]
  /** The path ends on a crown-jewel host (findings.path_to_crown_jewel). */
  endsOnCrownJewel?: boolean
}

const WIDTH = 640
const HEIGHT = 260
const MARGIN = 60
const NODE = 22 // half the node size; edges stop at the node's edge

// Left to right, zig-zag so long names do not collide (UI_PAGES §4.4).
// Host = rounded box, User = circle; the crown jewel gets a star; decision targets are ringed.
export default function CasePathGraph({ path, targets = [], endsOnCrownJewel = true }: CasePathGraphProps) {
  if (path.length === 0) return <p className="muted">No path to a crown jewel within 6 hops</p>

  const step = path.length > 1 ? (WIDTH - MARGIN * 2) / (path.length - 1) : 0
  const points = path.map((node, i) => ({
    node,
    x: path.length > 1 ? MARGIN + i * step : WIDTH / 2,
    y: HEIGHT / 2 + (path.length > 2 ? (i % 2 === 0 ? -34 : 34) : 0),
  }))
  const last = points.length - 1
  const targetSet = new Set(targets)

  return (
    <svg
      className="path-graph"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label={`Attack path: ${path.map((n) => `${n.name} (${n.label})`).join(' to ')}`}
    >
      <defs>
        <marker id="path-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0 0L10 5L0 10z" fill="#7d9a89" />
        </marker>
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
            markerEnd="url(#path-arrow)"
          />
        )
      })}

      {points.map((p, i) => {
        const isUser = p.node.label === 'User'
        const jewel = i === last && last > 0 && endsOnCrownJewel
        const target = targetSet.has(p.node.name)
        const above = p.y <= HEIGHT / 2
        const classes = ['path-node', isUser ? 'is-user' : 'is-host', jewel && 'is-jewel', i === 0 && last > 0 && 'is-entry', target && 'is-target']
        const nameY = above ? p.y - NODE - 14 : p.y + NODE + 28
        const labelY = above ? p.y - NODE - 38 : p.y + NODE + 50
        // The end nodes' labels grow inwards so they never leave the drawing.
        const anchor = last === 0 ? 'middle' : i === 0 ? 'start' : i === last ? 'end' : 'middle'
        const textX = anchor === 'start' ? p.x - NODE : anchor === 'end' ? p.x + NODE : p.x
        return (
          <g key={p.node.name} className={classes.filter(Boolean).join(' ')}>
            {target && (isUser ? (
              <circle cx={p.x} cy={p.y} r={NODE + 6} className="target-ring" />
            ) : (
              <rect x={p.x - NODE - 6} y={p.y - NODE - 6} width={(NODE + 6) * 2} height={(NODE + 6) * 2} rx="12" className="target-ring" />
            ))}
            {isUser ? (
              <circle cx={p.x} cy={p.y} r={NODE} />
            ) : (
              <rect x={p.x - NODE} y={p.y - NODE} width={NODE * 2} height={NODE * 2} rx="8" />
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
  )
}
