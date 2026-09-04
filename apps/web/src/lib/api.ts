export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) { super(message); this.status = status }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    credentials: 'include',
    headers: options.body instanceof FormData ? options.headers : { 'Content-Type': 'application/json', ...options.headers },
  })
  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const message = Array.isArray(body.message) ? body.message.join('；') : body.message
    throw new ApiError(message || '请求失败', response.status)
  }
  if (options.method && !['GET', 'HEAD'].includes(options.method.toUpperCase()) && !path.endsWith('/parse') && !path.endsWith('/similar')) {
    window.dispatchEvent(new Event('crm-data-changed'))
    if ('BroadcastChannel' in window) { const channel = new BroadcastChannel('crm-data'); channel.postMessage('changed'); channel.close() }
  }
  return body as T
}

export function formatDate(value?: string) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}
