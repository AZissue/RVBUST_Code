import { Bug, CheckCircle2, Paperclip, X } from 'lucide-react'
import { useRef, useState, type FormEvent } from 'react'
import { useAuth } from '../context/AuthContext'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { bugStatusLabel } from '../lib/labels'
import type { Attachment, BugReport, BugStatus } from '../types'

const statusBadgeClass: Record<BugStatus, string> = { OPEN: 'status-pending', IN_PROGRESS: 'status-in_progress', FIXED: 'status-resolved' }
const filters: Array<{ key: '' | BugStatus | 'mine'; label: string }> = [
  { key: '', label: '全部' }, { key: 'OPEN', label: '待处理' }, { key: 'IN_PROGRESS', label: '修复中' }, { key: 'FIXED', label: '已修复' }, { key: 'mine', label: '我提交的' },
]

export function BugsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [filter, setFilter] = useState<'' | BugStatus | 'mine'>('')
  const query = filter === 'mine' ? 'mine=1' : filter ? `status=${filter}` : ''
  const remote = useRemote(() => api<BugReport[]>(`/bugs${query ? `?${query}` : ''}`), [query], true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    const title = String(form.get('title') ?? '').trim()
    const description = String(form.get('description') ?? '').trim()
    try {
      const created = await api<BugReport>('/bugs', { method: 'POST', body: JSON.stringify({ title, description }) })
      if (file) {
        const body = new FormData(); body.append('file', file)
        await api(`/files/bugs/${created.id}`, { method: 'POST', body })
      }
      setFile(null); if (fileInput.current) fileInput.current.value = ''
      event.currentTarget.reset()
      await remote.refresh()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '提交失败') } finally { setBusy(false) }
  }

  const markStatus = async (id: string, status: BugStatus) => {
    setError('')
    try { await api(`/bugs/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status }) }); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '状态更新失败') }
  }

  const bugs = remote.data ?? []
  return <div className="page-stack">
    <header className="page-header"><div><span className="eyebrow">BUG TRACKER</span><h1>BUG 反馈</h1><p>所有用户都可以提交使用中遇到的问题并查看处理进度；截图支持 jpg / png / webp。</p></div></header>
    <section className="panel bug-form-panel"><div className="section-heading"><div><h2><Bug size={18} />提交 BUG</h2><p>描述你遇到的问题，可附一张截图</p></div></div>
      {error && <div className="form-error"><button onClick={() => setError('')}><X size={14} /></button>{error}</div>}
      <form onSubmit={submit} className="stack-form">
        <label>问题标题<input name="title" required minLength={3} maxLength={240} placeholder="一句话概括问题" /></label>
        <label>问题描述<textarea name="description" required minLength={3} rows={4} placeholder="复现步骤、期望行为、实际现象等" /></label>
        <label>截图<input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
        <div className="drawer-actions"><button className="button primary" disabled={busy}>{busy ? '提交中' : '提交 BUG'}</button></div>
      </form>
    </section>
    <section className="panel"><div className="section-heading"><div><h2>已提交的 BUG</h2><p>{bugs.length} 条记录</p></div>
      <div className="filter-row">{filters.map((item) => <button key={item.key} className={`chip ${filter === item.key ? 'active' : ''}`} onClick={() => setFilter(item.key)}>{item.label}</button>)}</div></div>
      <div className="relation-list">{bugs.map((bug) => <article className="relation-row bug-row" key={bug.id}>
        <div className="bug-main">
          <div className="bug-title"><span className={`badge ${statusBadgeClass[bug.status]}`}>{bugStatusLabel(bug.status)}</span><strong>{bug.title}</strong><span className="mono muted">{bug.bugNo}</span></div>
          <p className="bug-desc">{bug.description}</p>
          <div className="inline-meta"><span>{bug.author.name} 提交于 {formatDate(bug.createdAt)}</span>{bug.status === 'FIXED' && bug.resolver && <span>由 {bug.resolver.name} 修复于 {formatDate(bug.resolvedAt ?? undefined)}</span>}</div>
          {!!bug.attachments.length && <div className="thumb-list">{bug.attachments.map((item: Attachment) => <a key={item.id} href={`/api/files/${item.id}`} target="_blank" rel="noreferrer"><Paperclip size={13} />{item.originalName}</a>)}</div>}
        </div>
        {isAdmin && bug.status !== 'FIXED' && <div className="bug-actions">
          {bug.status === 'OPEN' && <button className="button small" onClick={() => void markStatus(bug.id, 'IN_PROGRESS')}>开始修复</button>}
          <button className="button small primary" onClick={() => void markStatus(bug.id, 'FIXED')}><CheckCircle2 size={14} />标记已修复</button>
        </div>}
      </article>)}{!bugs.length && <div className="empty-compact">暂无 BUG 记录</div>}</div>
    </section>
  </div>
}
