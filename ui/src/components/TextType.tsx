import { useEffect, useMemo, useState, type CSSProperties, type ElementType } from 'react'
import './TextType.css'

/*
 * Typewriter text that types, pauses, deletes and cycles through `text`.
 * Prop names follow the React Bits "Text Type" component. Screen readers get
 * the full sentences once; the animated copy is hidden from them.
 */

type TextTypeProps = {
  text: string | string[]
  as?: ElementType
  className?: string
  typingSpeed?: number
  pauseDuration?: number
  deletingSpeed?: number
  deleteMode?: 'backspace' | 'instant'
  typeEffect?: 'none' | 'fade'
  mistakes?: number
  cursorStyle?: 'underscore' | 'bar' | 'block'
  cursorGlide?: boolean
  showCursor?: boolean
  cursorColor?: string
  prefixColor?: string
  cursorBlinkDuration?: number
  cursorCharacter?: string
  prefix?: string
  loop?: boolean
  initialDelay?: number
}

type Step = { value: string; delay: number; pause?: boolean }

const DEFAULT_CURSOR = { underscore: '_', bar: '|', block: '▌' } as const
const TYPO_KEYS = 'qwertyuiopasdfghjklzxcvbnm'

/** Every intermediate string for one sentence: type (with typos), pause, delete. */
function buildSteps(
  sentence: string,
  opts: { typingSpeed: number; deletingSpeed: number; pauseDuration: number; deleteMode: string; mistakes: number },
): Step[] {
  const steps: Step[] = []
  const typoAt = new Set<number>()
  const letters = [...sentence].map((c, i) => (/[a-z]/i.test(c) ? i : -1)).filter((i) => i > 0)
  while (typoAt.size < Math.min(opts.mistakes, letters.length)) {
    typoAt.add(letters[Math.floor(Math.random() * letters.length)])
  }

  let typed = ''
  for (let i = 0; i < sentence.length; i++) {
    if (typoAt.has(i)) {
      const wrong = TYPO_KEYS[Math.floor(Math.random() * TYPO_KEYS.length)]
      const typo = sentence[i] === sentence[i].toUpperCase() ? wrong.toUpperCase() : wrong
      steps.push({ value: typed + typo, delay: opts.typingSpeed })
      steps.push({ value: typed, delay: opts.typingSpeed * 3 })
    }
    typed += sentence[i]
    steps.push({ value: typed, delay: opts.typingSpeed })
  }
  steps.push({ value: typed, delay: opts.pauseDuration, pause: true })
  if (opts.deleteMode === 'instant') {
    steps.push({ value: '', delay: opts.typingSpeed * 4 })
  } else {
    for (let n = typed.length - 1; n >= 0; n--) {
      steps.push({ value: typed.slice(0, n), delay: opts.deletingSpeed })
    }
    steps.push({ value: '', delay: opts.typingSpeed * 4 })
  }
  return steps
}

export default function TextType({
  text,
  as: Tag = 'span',
  className,
  typingSpeed = 75,
  pauseDuration = 1500,
  deletingSpeed = 50,
  deleteMode = 'backspace',
  typeEffect = 'none',
  mistakes = 0,
  cursorStyle = 'underscore',
  cursorGlide = true,
  showCursor = true,
  cursorColor = 'currentColor',
  prefixColor = 'currentColor',
  cursorBlinkDuration = 0.5,
  cursorCharacter,
  prefix = '',
  loop = true,
  initialDelay = 0,
}: TextTypeProps) {
  // Keyed by content so a new-but-equal array from the parent doesn't restart typing.
  const sentenceKey = Array.isArray(text) ? text.join('\u0000') : text
  const sentences = useMemo(() => sentenceKey.split('\u0000'), [sentenceKey])
  const [reducedMotion] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )
  const [sentenceIndex, setSentenceIndex] = useState(0)
  const [stepIndex, setStepIndex] = useState(-1)
  const [done, setDone] = useState(false)

  const steps = useMemo(
    () =>
      buildSteps(sentences[sentenceIndex] ?? '', { typingSpeed, deletingSpeed, pauseDuration, deleteMode, mistakes }),
    [sentences, sentenceIndex, typingSpeed, deletingSpeed, pauseDuration, deleteMode, mistakes],
  )

  useEffect(() => {
    if (reducedMotion || done) return
    const isLastSentence = sentenceIndex === sentences.length - 1
    // Without loop, stop once the last sentence is fully typed (before deleting).
    if (!loop && isLastSentence && steps[stepIndex]?.pause) {
      setDone(true)
      return
    }
    const delay = stepIndex < 0 ? initialDelay : steps[stepIndex].delay
    const timer = window.setTimeout(() => {
      if (stepIndex + 1 < steps.length) {
        setStepIndex(stepIndex + 1)
      } else {
        setSentenceIndex((sentenceIndex + 1) % sentences.length)
        setStepIndex(0)
      }
    }, delay)
    return () => window.clearTimeout(timer)
  }, [reducedMotion, done, stepIndex, steps, sentenceIndex, sentences.length, loop, initialDelay])

  const value = reducedMotion ? (sentences[0] ?? '') : stepIndex < 0 ? '' : steps[stepIndex].value
  const moving = stepIndex >= 0 && !steps[stepIndex]?.pause && !done
  const cursor = cursorCharacter ?? DEFAULT_CURSOR[cursorStyle]
  const head = typeEffect === 'fade' && value.length > 0 ? value.slice(0, -1) : value
  const tail = typeEffect === 'fade' && value.length > 0 ? value.slice(-1) : ''

  return (
    <Tag className={`text-type${className ? ` ${className}` : ''}`}>
      <span className="text-type__sr">
        {prefix}
        {sentences.join(' · ')}
      </span>
      <span className="text-type__live" aria-hidden="true">
        {prefix && (
          <span className="text-type__prefix" style={{ color: prefixColor }}>
            {prefix}
          </span>
        )}
        <span className="text-type__text">{head}</span>
        {tail && (
          <span key={value.length} className="text-type__text text-type__text--fade">
            {tail}
          </span>
        )}
        {showCursor && (
          <span
            className={`text-type__cursor text-type__cursor--${cursorStyle}${
              cursorGlide && moving ? ' text-type__cursor--solid' : ''
            }`}
            style={{ color: cursorColor, '--tt-blink': `${cursorBlinkDuration * 2}s` } as CSSProperties}
          >
            {cursor}
          </span>
        )}
      </span>
    </Tag>
  )
}
