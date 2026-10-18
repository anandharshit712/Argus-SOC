import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import type { CaseSummary } from '../api/apiTypes.ts'
import { fetchCases } from '../api/argusApi.ts'
import { caseTitle, humanize } from '../lib/caseTitle.ts'
import { tenantLabel } from '../lib/tenantLabel.ts'
import Icon, { type IconName } from './Icon.tsx'
import './CommandPalette.css'

/*
 * Ctrl+K / ⌘K: jump to a page, a case (by number or name) or another tenant
 * from anywhere. Arrow keys move, Enter opens, Esc closes.
 */

type Command = {
  id: string
  group: 'Pages' | 'Cases' | 'Tenants'
  label: string
  meta?: string
  icon: IconName
  keywords: string
  run: () => void
}

type CommandPaletteProps = {
  open: boolean
  onClose: () => void
  tenant: string
  tenants: string[]
  setTenant: (tenant: string) => void
}

const PAGES: { to: string; label: string; icon: IconName; keywords: string }[] = [
  { to: '/dashboard', label: 'Dashboard', icon: 'home', keywords: 'home overview kpi' },
  { to: '/cases', label: 'Cases', icon: 'cases', keywords: 'queue incidents' },
  { to: '/cases?status=awaiting_approval', label: 'Cases awaiting approval', icon: 'cases', keywords: 'approve needs you pending' },
  { to: '/playbooks', label: 'Playbooks', icon: 'playbooks', keywords: 'learned rules' },
  { to: '/activity', label: 'Activity', icon: 'activity', keywords: 'agents feed log' },
]
const MAX_CASES = 8

export const isMac = () => typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)

export default function CommandPalette({ open, onClose, tenant, tenants, setTenant }: CommandPaletteProps) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [index, setIndex] = useState(0)
  const [cases, setCases] = useState<CaseSummary[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)

  // Fresh case list each time it opens.
  useEffect(() => {
    if (!open) return
    setQuery('')
    setIndex(0)
    let cancelled = false
    fetchCases(tenant, 500)
      .then((list) => {
        if (!cancelled) setCases(list)
      })
      .catch(() => {
        if (!cancelled) setCases([])
      })
    requestAnimationFrame(() => inputRef.current?.focus())
    return () => {
      cancelled = true
    }
  }, [open, tenant])

  const commands = useMemo<Command[]>(() => {
    const go = (to: string) => () => {
      navigate(to)
      onClose()
    }
    const pages: Command[] = PAGES.map((p) => ({
      id: `page:${p.to}`,
      group: 'Pages',
      label: p.label,
      icon: p.icon,
      keywords: p.keywords,
      run: go(p.to),
    }))
    const caseCommands: Command[] = cases.map((c) => ({
      id: `case:${c.id}`,
      group: 'Cases',
      label: `#${c.id} ${caseTitle(c.category)}`,
      meta: `${humanize(c.priority)} · ${humanize(c.status)}`,
      icon: 'cases',
      keywords: `${c.id} ${c.category ?? ''} ${c.priority} ${c.status}`,
      run: go(`/cases/${c.id}`),
    }))
    const tenantCommands: Command[] = tenants
      .filter((t) => t !== tenant)
      .map((t) => ({
        id: `tenant:${t}`,
        group: 'Tenants',
        label: `Switch to ${tenantLabel(t)}`,
        icon: 'building',
        keywords: `tenant ${t}`,
        run: () => {
          setTenant(t)
          onClose()
        },
      }))
    return [...pages, ...caseCommands, ...tenantCommands]
  }, [cases, tenants, tenant, navigate, onClose, setTenant])

  const results = useMemo(() => {
    const q = query.trim().toLowerCase().replace(/^#/, '')
    if (!q) {
      // Nothing typed: pages, the newest few cases, tenants.
      return [
        ...commands.filter((c) => c.group === 'Pages'),
        ...commands.filter((c) => c.group === 'Cases').slice(0, 5),
        ...commands.filter((c) => c.group === 'Tenants'),
      ]
    }
    const words = q.split(/\s+/)
    const matches = commands.filter((c) => {
      const text = `${c.label} ${c.keywords}`.toLowerCase()
      return words.every((w) => text.includes(w))
    })
    // A case number typed exactly comes first.
    matches.sort((a, b) => Number(b.id === `case:${q}`) - Number(a.id === `case:${q}`))
    let caseCount = 0
    return matches.filter((c) => c.group !== 'Cases' || caseCount++ < MAX_CASES)
  }, [commands, query])

  useEffect(() => setIndex(0), [query])
  useEffect(() => {
    listRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [index])

  if (!open) return null

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setIndex((i) => (results.length ? (i + 1) % results.length : 0))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setIndex((i) => (results.length ? (i - 1 + results.length) % results.length : 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      results[index]?.run()
    }
  }

  let lastGroup = ''
  return (
    <div className="palette-backdrop" onMouseDown={onClose}>
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Search pages and cases"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <div className="palette-input">
          <Icon name="search" size={18} />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search pages, case numbers, tenants…"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-results"
            aria-activedescendant={results[index] ? `palette-${results[index].id}` : undefined}
          />
          <kbd>Esc</kbd>
        </div>
        <ul id="palette-results" ref={listRef} className="palette-results" role="listbox">
          {results.length === 0 && <li className="palette-empty">No matches for “{query}”.</li>}
          {results.map((c, i) => {
            const heading = c.group !== lastGroup ? c.group : null
            lastGroup = c.group
            return (
              <li key={c.id} role="presentation">
                {heading && <p className="palette-group">{heading}</p>}
                <div
                  id={`palette-${c.id}`}
                  role="option"
                  aria-selected={i === index}
                  className={`palette-item${i === index ? ' is-active' : ''}`}
                  onMouseMove={() => setIndex(i)}
                  onClick={() => c.run()}
                >
                  <Icon name={c.icon} size={18} />
                  <span className="palette-label">{c.label}</span>
                  {c.meta && <span className="palette-meta">{c.meta}</span>}
                  {i === index && <Icon name="arrowRight" size={16} />}
                </div>
              </li>
            )
          })}
        </ul>
        <p className="palette-foot">
          <span><kbd>↑</kbd> <kbd>↓</kbd> move</span>
          <span><kbd>Enter</kbd> open</span>
          <span><kbd>{isMac() ? '⌘' : 'Ctrl'}</kbd> <kbd>K</kbd> toggle</span>
        </p>
      </div>
    </div>
  )
}
