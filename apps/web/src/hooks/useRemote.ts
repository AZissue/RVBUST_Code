import { useCallback, useEffect, useState } from 'react'

export function useRemote<T>(loader: () => Promise<T>, dependencies: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const refresh = useCallback(async () => {
    setLoading(true); setError('')
    try { setData(await loader()) } catch (reason) { setError(reason instanceof Error ? reason.message : '加载失败') } finally { setLoading(false) }
  }, dependencies)
  useEffect(() => { void refresh() }, [refresh])
  return { data, loading, error, refresh, setData }
}

