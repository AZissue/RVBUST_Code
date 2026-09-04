import { useCallback, useEffect, useRef, useState } from 'react'

export function useRemote<T>(loader: () => Promise<T>, dependencies: unknown[] = [], live = false) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const sequence = useRef(0)
  const refresh = useCallback(async () => {
    const request = ++sequence.current
    try { const result = await loader(); if (request === sequence.current) { setData(result); setError('') } }
    catch (reason) { if (request === sequence.current) setError(reason instanceof Error ? reason.message : '加载失败') }
    finally { if (request === sequence.current) setLoading(false) }
  }, dependencies)
  useEffect(() => {
    setLoading(true); void refresh()
    if (!live) return () => { ++sequence.current }
    let timer: ReturnType<typeof setTimeout>
    const changed = () => { clearTimeout(timer); timer = setTimeout(() => void refresh(), 100) }
    const channel = 'BroadcastChannel' in window ? new BroadcastChannel('crm-data') : null
    if (channel) channel.onmessage = changed
    window.addEventListener('crm-data-changed', changed)
    window.addEventListener('focus', changed)
    const poll = setInterval(() => { if (!document.hidden) void refresh() }, 15000)
    return () => { ++sequence.current; clearTimeout(timer); clearInterval(poll); channel?.close(); window.removeEventListener('crm-data-changed', changed); window.removeEventListener('focus', changed) }
  }, [refresh, live])
  return { data, loading, error, refresh, setData }
}
