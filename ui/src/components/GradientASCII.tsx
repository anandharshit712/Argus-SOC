import { useEffect, useRef } from 'react'
import './GradientASCII.css'

/*
 * Animated gradient + ASCII-glyph background drawn on a single <canvas>.
 * Prop names follow the React Bits "Gradient ASCII" background so it can be
 * tuned with the same knobs. No dependencies; ~30 fps; pauses when the tab is
 * hidden; renders one still frame when the user prefers reduced motion.
 */

type GradientASCIIProps = {
  colors?: string[]
  shape?: 'horizon' | 'radial' | 'linear'
  characters?: string
  cellSize?: number
  density?: number
  glyphOpacity?: number
  glow?: number
  depthOfField?: number
  flicker?: number
  softness?: number
  scale?: number
  flow?: number
  speed?: number
  gradientOpacity?: number
  grain?: number
  variation?: number
  mouseInteraction?: boolean
  scrambleRadius?: number
  clickEffect?: 'wave' | 'none'
  intro?: boolean
  lightMode?: boolean
  className?: string
}

type Rgb = [number, number, number]
type Wave = { x: number; y: number; start: number }

const FRAME_MS = 1000 / 30
const WAVE_LIFE = 1.8
const INTRO_SECONDS = 1.6
const PALETTE_STEPS = 48

function hexToRgb(hex: string): Rgb {
  const clean = hex.replace('#', '')
  const full = clean.length === 3 ? clean.split('').map((c) => c + c).join('') : clean
  const n = parseInt(full, 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function samplePalette(stops: Rgb[], t: number): Rgb {
  if (stops.length === 1) return stops[0]
  const pos = Math.min(Math.max(t, 0), 1) * (stops.length - 1)
  const i = Math.min(Math.floor(pos), stops.length - 2)
  const f = pos - i
  const a = stops[i]
  const b = stops[i + 1]
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]
}

/** Cheap deterministic per-cell hash in [0, 1). */
function hash(x: number, y: number, seed = 0): number {
  const s = Math.sin(x * 127.1 + y * 311.7 + seed * 74.7) * 43758.5453
  return s - Math.floor(s)
}

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v
}

export default function GradientASCII({
  colors = ['#052e16', '#14532d', '#22c55e', '#4ade6a'],
  shape = 'horizon',
  characters = ' =+xX0S8#@',
  cellSize = 18,
  density = 0.8,
  glyphOpacity = 0.85,
  glow = 0.2,
  depthOfField = 0,
  flicker = 0.2,
  softness = 0.5,
  scale = 1,
  flow = 0.5,
  speed = 1,
  gradientOpacity = 0.9,
  grain = 0.08,
  variation = 0,
  mouseInteraction = true,
  scrambleRadius = 0.1,
  clickEffect = 'wave',
  intro = true,
  className,
}: GradientASCIIProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const colorKey = colors.join(',')

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return

    const stops = colorKey.split(',').map(hexToRgb)
    const palette = Array.from({ length: PALETTE_STEPS }, (_, i) => {
      const [r, g, b] = samplePalette(stops, i / (PALETTE_STEPS - 1))
      return `rgb(${r | 0},${g | 0},${b | 0})`
    })
    const glyphs = characters.length > 0 ? characters : ' .:+#'
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const supportsFilter = 'filter' in ctx

    // Grain tile, generated once and stamped at a random offset each frame.
    const grainTile = document.createElement('canvas')
    grainTile.width = grainTile.height = 128
    const grainCtx = grainTile.getContext('2d')
    if (grainCtx) {
      const img = grainCtx.createImageData(128, 128)
      for (let i = 0; i < img.data.length; i += 4) {
        const v = Math.random() * 255
        img.data[i] = img.data[i + 1] = img.data[i + 2] = v
        img.data[i + 3] = 255
      }
      grainCtx.putImageData(img, 0, 0)
    }
    const grainPattern = ctx.createPattern(grainTile, 'repeat')

    // Offscreen layer for the glyphs so glow can be a single blurred pass.
    const glyphLayer = document.createElement('canvas')
    const glyphCtx = glyphLayer.getContext('2d')
    if (!glyphCtx) return

    let width = 0
    let height = 0
    let dpr = 1
    let cols = 0
    let rows = 0
    const pointer = { x: -9999, y: -9999, active: false }
    const waves: Wave[] = []
    const startedAt = performance.now()
    let raf = 0
    let lastFrame = 0

    const resize = () => {
      const rect = canvas.getBoundingClientRect()
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      width = Math.max(1, rect.width)
      height = Math.max(1, rect.height)
      for (const c of [canvas, glyphLayer]) {
        c.width = Math.round(width * dpr)
        c.height = Math.round(height * dpr)
      }
      cols = Math.ceil(width / cellSize) + 1
      rows = Math.ceil(height / cellSize) + 1
      if (reducedMotion) draw(performance.now())
    }

    /** Base intensity field in [0, 1] for a cell centre (normalised coords). */
    const field = (nx: number, ny: number, t: number): number => {
      const f = flow * t
      const s = scale
      const swirl =
        0.5 +
        0.25 * Math.sin(nx * 6.2 * s + f * 0.9 + Math.sin(ny * 3.1 * s - f * 0.6)) +
        0.25 * Math.cos(ny * 5.3 * s - f * 0.7 + nx * 2.2 * s)
      const spread = 0.1 + softness * 0.3

      if (shape === 'radial') {
        const d = Math.hypot(nx - 0.5, (ny - 0.5) * (height / width))
        return clamp01(Math.exp(-d / (spread * 1.4)) * (0.55 + 0.45 * swirl))
      }
      if (shape === 'linear') {
        const band = Math.exp(-Math.abs(nx - 0.5 - 0.15 * Math.sin(f * 0.4 + ny * 3)) / spread)
        return clamp01(band * (0.55 + 0.45 * swirl))
      }

      // Horizon: bright band across the lower third, perspective rows below it.
      const horizon = 0.64 + 0.02 * Math.sin(f * 0.35 + nx * 3)
      const dy = ny - horizon
      const band = Math.exp(-Math.abs(dy) / (dy < 0 ? spread * 1.6 : spread))
      let v = band * (0.55 + 0.45 * swirl)
      if (dy > 0) {
        const depth = 1 / (dy + 0.03)
        const stripe = 0.5 + 0.5 * Math.sin(depth * 1.4 * s - f * 2.2)
        v = Math.max(v, (0.25 + 0.45 * stripe) * clamp01(dy * 3.2))
      }
      return clamp01(v)
    }

    const draw = (now: number) => {
      const t = ((now - startedAt) / 1000) * speed
      const elapsed = (now - startedAt) / 1000
      const introP = intro && !reducedMotion ? clamp01(elapsed / INTRO_SECONDS) : 1

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.globalCompositeOperation = 'source-over'
      ctx.globalAlpha = 1
      ctx.clearRect(0, 0, width, height)

      // 1. Soft gradient wash underneath the glyphs.
      if (gradientOpacity > 0) {
        const [r0, g0, b0] = stops[0]
        const [r1, g1, b1] = samplePalette(stops, 0.45)
        const gy = height * (shape === 'horizon' ? 0.64 : 0.5)
        const wash = ctx.createRadialGradient(width / 2, gy, 0, width / 2, gy, Math.max(width, height) * (0.45 + softness * 0.35))
        wash.addColorStop(0, `rgba(${r1 | 0},${g1 | 0},${b1 | 0},${0.55 * gradientOpacity * introP})`)
        wash.addColorStop(0.55, `rgba(${r0},${g0},${b0},${0.35 * gradientOpacity * introP})`)
        wash.addColorStop(1, 'rgba(0,0,0,0)')
        ctx.fillStyle = wash
        ctx.fillRect(0, 0, width, height)
      }

      // 2. Glyphs.
      glyphCtx.setTransform(dpr, 0, 0, dpr, 0, 0)
      glyphCtx.clearRect(0, 0, width, height)
      glyphCtx.font = `${Math.round(cellSize * 0.82)}px 'Share Tech Mono', ui-monospace, monospace`
      glyphCtx.textAlign = 'center'
      glyphCtx.textBaseline = 'middle'

      const scrambleR = scrambleRadius * Math.min(width, height)
      const flickerTick = Math.floor(t * 7)
      const waveSpeed = Math.max(width, height) * 0.55
      const liveWaves = waves.filter((w) => (now - w.start) / 1000 < WAVE_LIFE)
      waves.length = 0
      waves.push(...liveWaves)

      for (let row = 0; row < rows; row++) {
        const cy = row * cellSize + cellSize / 2
        const ny = cy / height
        for (let col = 0; col < cols; col++) {
          const cx = col * cellSize + cellSize / 2
          const nx = cx / width
          const cellRand = hash(col, row)
          let v = field(nx, ny, t)

          if (variation > 0) v = clamp01(v + (cellRand - 0.5) * variation)
          if (flicker > 0) v *= 1 - flicker * 0.6 * hash(col, row, flickerTick)

          let boost = 0
          let scramble = false
          if (mouseInteraction && pointer.active && scrambleR > 0) {
            const d = Math.hypot(cx - pointer.x, cy - pointer.y)
            if (d < scrambleR) {
              const k = 1 - d / scrambleR
              boost += k * 0.55
              scramble = hash(col, row, flickerTick * 3) < k
            }
          }
          for (const w of waves) {
            const age = (now - w.start) / 1000
            const radius = age * waveSpeed
            const d = Math.hypot(cx - w.x, cy - w.y)
            const ring = Math.exp(-(((d - radius) / (cellSize * 2.2)) ** 2))
            if (ring > 0.05) {
              boost += ring * (1 - age / WAVE_LIFE) * 0.8
              if (ring > 0.5) scramble = true
            }
          }

          // Intro: reveal outward from the horizon / centre with scrambled glyphs.
          let reveal = 1
          if (introP < 1) {
            const origin = shape === 'horizon' ? 0.64 : 0.5
            const dist = Math.abs(ny - origin) + cellRand * 0.15
            reveal = clamp01((introP * 1.25 - dist) * 6)
            if (reveal > 0 && reveal < 1) scramble = true
          }

          if (depthOfField > 0) {
            const origin = shape === 'horizon' ? 0.64 : 0.5
            v *= 1 - depthOfField * clamp01(Math.abs(ny - origin) * 1.6)
          }

          const level = clamp01(v + boost)
          if (reveal <= 0 || (cellRand > density && boost < 0.15)) continue
          const alpha = glyphOpacity * reveal * (0.3 + 0.7 * level)
          if (level < 0.06 || alpha < 0.02) continue

          const idx = scramble
            ? 1 + Math.floor(hash(col, row, now * 0.01) * (glyphs.length - 1))
            : Math.min(glyphs.length - 1, Math.floor(level * glyphs.length))
          const ch = glyphs[idx] ?? glyphs[glyphs.length - 1]
          if (ch === ' ') continue

          glyphCtx.globalAlpha = Math.min(alpha, 1)
          glyphCtx.fillStyle = palette[Math.min(PALETTE_STEPS - 1, Math.floor(level * PALETTE_STEPS))]
          glyphCtx.fillText(ch, cx, cy)
        }
      }

      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.drawImage(glyphLayer, 0, 0)
      if (glow > 0 && supportsFilter) {
        ctx.globalCompositeOperation = 'lighter'
        ctx.globalAlpha = Math.min(glow * 1.5, 1)
        ctx.filter = `blur(${Math.round(cellSize * 0.45 * dpr)}px)`
        ctx.drawImage(glyphLayer, 0, 0)
        ctx.filter = 'none'
      }

      // 3. Film grain.
      if (grain > 0 && grainPattern) {
        ctx.globalCompositeOperation = 'overlay'
        ctx.globalAlpha = grain
        const ox = Math.random() * 128
        const oy = Math.random() * 128
        ctx.translate(-ox, -oy)
        ctx.fillStyle = grainPattern
        ctx.fillRect(0, 0, canvas.width + 128, canvas.height + 128)
        ctx.setTransform(1, 0, 0, 1, 0, 0)
      }
      ctx.globalCompositeOperation = 'source-over'
      ctx.globalAlpha = 1
    }

    const loop = (now: number) => {
      raf = requestAnimationFrame(loop)
      if (document.hidden || now - lastFrame < FRAME_MS) return
      lastFrame = now
      draw(now)
    }

    const toLocal = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect()
      return { x: e.clientX - rect.left, y: e.clientY - rect.top }
    }
    const onMove = (e: PointerEvent) => {
      const p = toLocal(e)
      pointer.x = p.x
      pointer.y = p.y
      pointer.active = true
    }
    const onLeave = () => {
      pointer.active = false
    }
    const onDown = (e: PointerEvent) => {
      const target = e.target as Element | null
      if (target?.closest('input, button, a, select, textarea, label')) return
      const p = toLocal(e)
      waves.push({ x: p.x, y: p.y, start: performance.now() })
    }

    const observer = new ResizeObserver(resize)
    observer.observe(canvas)
    resize()

    if (!reducedMotion) {
      if (mouseInteraction) {
        window.addEventListener('pointermove', onMove)
        document.documentElement.addEventListener('pointerleave', onLeave)
      }
      if (clickEffect === 'wave') window.addEventListener('pointerdown', onDown)
      raf = requestAnimationFrame(loop)
    }
    // Redraw once web fonts are in so glyph metrics match the theme font.
    document.fonts?.ready.then(() => draw(performance.now()))

    return () => {
      cancelAnimationFrame(raf)
      observer.disconnect()
      window.removeEventListener('pointermove', onMove)
      document.documentElement.removeEventListener('pointerleave', onLeave)
      window.removeEventListener('pointerdown', onDown)
    }
  }, [
    colorKey, shape, characters, cellSize, density, glyphOpacity, glow, depthOfField,
    flicker, softness, scale, flow, speed, gradientOpacity, grain, variation,
    mouseInteraction, scrambleRadius, clickEffect, intro,
  ])

  return <canvas ref={canvasRef} className={`gradient-ascii${className ? ` ${className}` : ''}`} aria-hidden="true" />
}
