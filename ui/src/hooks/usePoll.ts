import { useCallback, useEffect, useRef, useState } from 'react'

type PollState<T> = { data: T | null; error: string | null; loading: boolean }

/**
 * Calls `load` now and then every `intervalMs` while `enabled`. Re-runs from scratch when `deps`
 * change. Keeps the last data on screen while a refresh is in flight or has failed.
 * `refresh()` fetches again straight away, for example after a write.
 */
export function usePoll<T>(
  load: () => Promise<T>,
  intervalMs: number,
  enabled: boolean,
  deps: unknown[],
): PollState<T> & { refresh: () => void } {
  const [state, setState] = useState<PollState<T>>({ data: null, error: null, loading: true })
  const [refreshCount, setRefreshCount] = useState(0)
  const loadRef = useRef(load)
  loadRef.current = load

  const refresh = useCallback(() => setRefreshCount((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false

    async function run() {
      try {
        const data = await loadRef.current()
        if (!cancelled) setState({ data, error: null, loading: false })
      } catch (err) {
        const error = err instanceof Error ? err.message : 'Request failed.'
        if (!cancelled) setState((prev) => ({ ...prev, error, loading: false }))
      }
    }

    setState((prev) => ({ ...prev, loading: true }))
    void run()
    if (!enabled) {
      return () => {
        cancelled = true
      }
    }

    const timer = setInterval(run, intervalMs)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, enabled, refreshCount, ...deps])

  return { ...state, refresh }
}
