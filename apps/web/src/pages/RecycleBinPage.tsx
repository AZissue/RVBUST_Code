import { ArrowLeft, RotateCcw, Search, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Pagination } from '../components/Pagination'
import { PriorityBadge, StatusBadge } from '../components/Status'
import { useAuth } from '../context/AuthContext'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import type { Ticket } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'

interface PagedTickets { items: Ticket[]; total: number; page: number; pageSize: number }

export function RecycleBinPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const search = params.get('q') ?? ''
  const page = Math.max(1, Number.parseInt(params.get('p') ?? '1', 10) || 1)
  const [debouncedSearch, setDebouncedSearch] = useState(search)
  const [busy, setBusy] = useState('')
  useEffect(() => { const timer = setTimeout(() => setDebouncedSearch(search), 300); return () => clearTimeout(timer) }, [search])
  const setFilter = (key: string, value: string) => { setParams(previous => { const next = new URLSearchParams(previous); value ? next.set(key, value) : next.delete(key); if (key !== 'p') next.delete('p'); return next }, { replace: true }) }
  const query = new URLSearchParams()
  if (debouncedSearch.trim()) query.set('search', debouncedSearch.trim())
  query.set('page', String(page))
  const remote = useRemote(() => api<PagedTickets>(`/tickets/recycle-bin?${query.toString()}`), [debouncedSearch.trim(), page], true)
  const tickets = remote.data?.items ?? []
  const total = remote.data?.total ?? 0
  const pageSize = remote.data?.pageSize ?? 20
  const restore = async (ticket: Ticket) => { setBusy(`restore:${ticket.id}`); try { await api(`/tickets/${ticket.id}/restore`, { method: 'POST' }); await remote.refresh() } catch (reason) { window.alert(reason instanceof Error ? reason.message : '恢复失败') } finally { setBusy('') } }
  const purge = async (ticket: Ticket) => { if (!window.confirm(`确认彻底删除工单 ${ticket.number}「${ticket.title}」？此操作不可恢复。`)) return; setBusy(`purge:${ticket.id}`); try { await api(`/tickets/${ticket.id}/purge`, { method: 'DELETE' }); await remote.refresh() } catch (reason) { window.alert(reason instanceof Error ? reason.message : '删除失败') } finally { setBusy('') } }
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  return <div className="page-stack">
    <header className="detail-header"><button className="icon-button" onClick={() => navigate('/tickets')} title="返回"><ArrowLeft size={20} /></button><div><span className="mono eyebrow">RECYCLE BIN</span><h1>工单回收站</h1><div className="inline-meta"><span>已删除工单可恢复或彻底清理</span></div></div></header>
    <section className="toolbar"><div className="searchbox"><Search size={16} /><input placeholder="搜索编号、问题或客户" value={search} onChange={(event) => setFilter('q', event.target.value)} /></div><span className="result-count">{total} 条已删除</span></section>
    <section className="panel no-padding"><div className="table-wrap"><table><thead><tr><th>编号</th><th>问题</th><th>客户</th><th>状态</th><th>优先级</th><th>删除人</th><th>删除时间</th><th>原因</th><th>操作</th></tr></thead><tbody>{tickets.map((ticket) => <tr key={ticket.id}><td className="mono">{ticket.number}</td><td><strong>{ticket.title}</strong></td><td>{ticket.organization.name}</td><td><StatusBadge status={ticket.status} /></td><td><PriorityBadge priority={ticket.priority} /></td><td>{ticket.deletedBy?.name ?? '-'}</td><td>{formatDate(ticket.deletedAt ?? '')}</td><td>{ticket.deletedReason || '-'}</td><td><div className="row-actions"><button className="button small" disabled={busy === `restore:${ticket.id}`} onClick={() => void restore(ticket)}><RotateCcw size={14} />恢复</button>{user?.role === 'admin' && <button className="button small danger" disabled={busy === `purge:${ticket.id}`} onClick={() => void purge(ticket)}><Trash2 size={14} />彻底删除</button>}</div></td></tr>)}</tbody></table>{!tickets.length && <Empty text="回收站为空" />}</div></section>
    <Pagination page={page} pageSize={pageSize} total={total} onPage={(next) => setFilter('p', String(next))} />
  </div>
}
