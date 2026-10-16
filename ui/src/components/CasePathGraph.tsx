import type { PathNode } from '../api/apiTypes.ts'

type CasePathGraphProps = { path: PathNode[] }

const WIDTH = 640
const HEIGHT = 240
const MARGIN = 70

// The path from the entry point to the crown jewel, drawn as a zig-zag so long names do not collide.
export default function CasePathGraph({ path }: CasePathGraphProps) {
  if (path.length === 0) return <p className="muted">No path found for this case.</p>

  const step = path.length > 1 ? (WIDTH - MARGIN * 2) / (path.length - 1) : 0
  const points = path.map((node, i) => ({
    node,
    x: path.length > 1 ? MARGIN + i * step : WIDTH / 2,
    y: HEIGHT / 2 + (i % 2 === 0 ? -30 : 30),
  }))
  const last = points.length - 1

  return (
    <svg
      className="path-graph"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label={`Path: ${path.map((n) => n.name).join(' to ')}`}
    >
      <defs>
        <marker id="path-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0 0L10 5L0 10z" fill="#4ade6a" />
        </marker>
      </defs>

      {points.slice(1).map((p, i) => (
        <line
          key={p.node.name}
          x1={points[i].x}
          y1={points[i].y}
          x2={p.x}
          y2={p.y}
          className="path-edge"
          markerEnd="url(#path-arrow)"
        />
      ))}

      {points.map((p, i) => {
        const kind = i === 0 && last > 0 ? 'entry' : i === last && last > 0 ? 'target' : 'hop'
        const above = p.y < HEIGHT / 2
        return (
          <g key={p.node.name} className={`path-node path-node-${kind}`}>
            <circle cx={p.x} cy={p.y} r="15" />
            <text x={p.x} y={above ? p.y - 28 : p.y + 36} textAnchor="middle" className="path-name">
              {p.node.name}
            </text>
            <text x={p.x} y={above ? p.y - 44 : p.y + 52} textAnchor="middle" className="path-label">
              {kind === 'entry' ? `${p.node.label} · entry` : kind === 'target' ? `${p.node.label} · crown jewel` : p.node.label}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
