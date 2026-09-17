import { ArrowLeft, RotateCcw, Search, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Pagination } from '../components/Pagination'
import { PriorityBadge, StatusBadge } from '../components/Status'
import { useAuth } from '../context/AuthContext'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { loanStatusLabels, repairStatusLabels } from '../lib/labels'
import type { Device, LoanOrder, RepairOrder, Ticket } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'

interface PagedTickets { items: Ticket[]; total: number; page: number; pageSize: number }

const TABS = [['tickets', '工单'], ['devices', '设备'], ['loans', '借测'], ['repairs', '维修']] as const
type TabKey = (typeof TABS)[number][0]

export function RecycleBinPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const tab = (TABS.some(([key]) => key === params.get('tab')) ? params.get('tab') : 'tickets') as TabKey
  const setTab = (key: TabKey) => setParams((previous) => { const next = new URLSearchParams(previous); next.set('tab', key); return next }, { replace: true })
  return <div className="page-stack">
    <header className="detail-header"><button className="icon-button" onClick={() => navigate(-1)} title="返回"><ArrowLeft size={20} /></button><div><span className="mono eyebrow">RECYCLE BIN</span><h1>回收站</h1><div className="inline-meta"><span>已删除记录可恢复或彻底清理</span></div></div></header>
    <div className="toolbar" role="tablist">
      {TABS.map(([key, label]) => <button key={key} role="tab" aria-selected={tab === key} className={`button small ${tab === key ? 'primary' : ''}`} onClick={() => setTab(key)}>{label}</button>)}
    </div>
    {tab === 'tickets' && <TicketsBin key="tickets" />}
    {tab === 'devices' && <DevicesBin key="devices" />}
    {tab === 'loans' && <LoansBin key="loans" />}
    {tab === 'repairs' && <RepairsBin key="repairs" />}
  </div>
}

/** 行内操作：恢复 + 彻底删除（仅管理员） */
function RowActions({ id, busy, onRestore, onPurge, isAdmin }: { id: string; busy: string; onRestore: () => void; onPurge: () => void; isAdmin: boolean }) {
  return <div className="row-actions">
    <button className="button small" disabled={busy === `restore:${id}`} onClick={() => void onRestore()}><RotateCcw size={14} />恢复</button>
    {isAdmin && <button className="button small danger" disabled={busy === `purge:${id}`} onClick={() => void onPurge()}><Trash2 size={14} />彻底删除</button>}
  </div>
}

const useBusy = () => {
  const [busy, setBusy] = useState('')
  const run = async (key: string, action: () => Promise<void>) => { setBusy(key); try { await action() } catch (reason) { window.alert(reason instanceof Error ? reason.message : '操作失败') } finally { setBusy('') } }
  return { busy, run }
}

function TicketsBin() {
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const search = params.get('q') ?? ''
  const page = Math.max(1, Number.parseInt(params.get('p') ?? '1', 10) || 1)
  const [debouncedSearch, setDebouncedSearch] = useState(search)
  useEffect(() => { const timer = setTimeout(() => setDebouncedSearch(search), 300); return () => clearTimeout(timer) }, [search])
  const setFilter = (key: string, value: string) => { setParams(previous => { const next = new URLSearchParams(previous); value ? next.set(key, value) : next.delete(key); if (key !== 'p') next.delete('p'); return next }, { replace: true }) }
  const query = new URLSearchParams()
  if (debouncedSearch.trim()) query.set('search', debouncedSearch.trim())
  query.set('page', String(page))
  const remote = useRemote(() => api<PagedTickets>(`/tickets/recycle-bin?${query.toString()}`), [debouncedSearch.trim(), page], true)
  const tickets = remote.data?.items ?? []
  const total = remote.data?.total ?? 0
  const pageSize = remote.data?.pageSize ?? 20
  const { busy, run } = useBusy()
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  return <>
    <section className="toolbar"><div className="searchbox"><Search size={16} /><input placeholder="搜索编号、问题或客户" value={search} onChange={(event) => setFilter('q', event.target.value)} /></div><span className="result-count">{total} 条已删除</span></section>
    <section className="panel no-padding"><div className="table-wrap"><table><thead><tr><th>编号</th><th>问题</th><th>客户</th><th>状态</th><th>优先级</th><th>删除人</th><th>删除时间</th><th>原因</th><th>操作</th></tr></thead><tbody>{tickets.map((ticket) => <tr key={ticket.id}><td className="mono">{ticket.number}</td><td><strong>{ticket.title}</strong></td><td>{ticket.organization.name}</td><td><StatusBadge status={ticket.status} /></td><td><PriorityBadge priority={ticket.priority} /></td><td>{ticket.deletedBy?.name ?? '-'}</td><td>{formatDate(ticket.deletedAt ?? '')}</td><td>{ticket.deletedReason || '-'}</td><td><RowActions id={ticket.id} busy={busy} isAdmin={user?.role === 'admin'}
      onRestore={() => run(`restore:${ticket.id}`, async () => { await api(`/tickets/${ticket.id}/restore`, { method: 'POST' }); await remote.refresh() })}
      onPurge={() => { if (window.confirm(`确认彻底删除工单 ${ticket.number}「${ticket.title}」？此操作不可恢复。`)) return run(`purge:${ticket.id}`, async () => { await api(`/tickets/${ticket.id}/purge`, { method: 'DELETE' }); await remote.refresh() }) }} /></td></tr>)}</tbody></table>{!tickets.length && <Empty text="回收站为空" />}</div></section>
    <Pagination page={page} pageSize={pageSize} total={total} onPage={(next) => setFilter('p', String(next))} />
  </>
}

function DevicesBin() {
  const { user } = useAuth()
  const remote = useRemote(() => api<Device[]>('/devices/recycle-bin'), [], true)
  const { busy, run } = useBusy()
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  const devices = remote.data ?? []
  return <section className="panel no-padding"><div className="table-wrap"><table><thead><tr><th>名称</th><th>型号</th><th>SN</th><th>归属</th><th>删除人</th><th>删除时间</th><th>操作</th></tr></thead><tbody>{devices.map((device) => <tr key={device.id}>
    <td><strong>{device.name}</strong></td><td>{device.cameraModel || device.product || '-'}</td><td className="mono">{device.serialNumber || '-'}</td>
    <td>{device.ownerType === 'COMPANY' ? '公司样机' : device.organization?.name ?? '客户资产'}</td>
    <td>{device.deletedBy?.name ?? '-'}</td><td>{formatDate(device.deletedAt ?? '')}</td>
    <td><RowActions id={device.id} busy={busy} isAdmin={user?.role === 'admin'}
      onRestore={() => run(`restore:${device.id}`, async () => { await api(`/devices/${device.id}/restore`, { method: 'POST' }); await remote.refresh() })}
      onPurge={() => { if (window.confirm(`确认彻底删除设备「${device.name}」？存在工单/借测/返修引用的设备无法彻底删除，此操作不可恢复。`)) return run(`purge:${device.id}`, async () => { await api(`/devices/${device.id}/purge`, { method: 'DELETE' }); await remote.refresh() }) }} /></td>
  </tr>)}</tbody></table>{!devices.length && <Empty text="回收站为空" />}</div></section>
}

function LoansBin() {
  const { user } = useAuth()
  const remote = useRemote(() => api<LoanOrder[]>('/loans/recycle-bin'), [], true)
  const { busy, run } = useBusy()
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  const loans = remote.data ?? []
  return <section className="panel no-padding"><div className="table-wrap"><table><thead><tr><th>单号</th><th>客户</th><th>状态</th><th>删除人</th><th>删除时间</th><th>操作</th></tr></thead><tbody>{loans.map((loan) => <tr key={loan.id}>
    <td className="mono">{loan.loanNo}</td><td>{loan.organization.name}</td><td>{loanStatusLabels[loan.status]}</td>
    <td>{loan.deletedBy?.name ?? '-'}</td><td>{formatDate(loan.deletedAt ?? '')}</td>
    <td><RowActions id={loan.id} busy={busy} isAdmin={user?.role === 'admin'}
      onRestore={() => run(`restore:${loan.id}`, async () => { await api(`/loans/${loan.id}/restore`, { method: 'POST' }); await remote.refresh() })}
      onPurge={() => { if (window.confirm(`确认彻底删除借测单 ${loan.loanNo}？借测明细与跟进记录将一并清除，此操作不可恢复。`)) return run(`purge:${loan.id}`, async () => { await api(`/loans/${loan.id}/purge`, { method: 'DELETE' }); await remote.refresh() }) }} /></td>
  </tr>)}</tbody></table>{!loans.length && <Empty text="回收站为空" />}</div></section>
}

function RepairsBin() {
  const { user } = useAuth()
  const remote = useRemote(() => api<RepairOrder[]>('/repairs/recycle-bin'), [], true)
  const { busy, run } = useBusy()
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  const repairs = remote.data ?? []
  return <section className="panel no-padding"><div className="table-wrap"><table><thead><tr><th>单号</th><th>客户</th><th>SN</th><th>状态</th><th>删除人</th><th>删除时间</th><th>操作</th></tr></thead><tbody>{repairs.map((repair) => <tr key={repair.id}>
    <td className="mono">{repair.repairNo}</td><td>{repair.organization.name}</td><td className="mono">{repair.serialNumber || repair.device?.serialNumber || '-'}</td><td>{repairStatusLabels[repair.status]}</td>
    <td>{repair.deletedBy?.name ?? '-'}</td><td>{formatDate(repair.deletedAt ?? '')}</td>
    <td><RowActions id={repair.id} busy={busy} isAdmin={user?.role === 'admin'}
      onRestore={() => run(`restore:${repair.id}`, async () => { await api(`/repairs/${repair.id}/restore`, { method: 'POST' }); await remote.refresh() })}
      onPurge={() => { if (window.confirm(`确认彻底删除返修单 ${repair.repairNo}？状态时间线与跟进记录将一并清除，此操作不可恢复。`)) return run(`purge:${repair.id}`, async () => { await api(`/repairs/${repair.id}/purge`, { method: 'DELETE' }); await remote.refresh() }) }} /></td>
  </tr>)}</tbody></table>{!repairs.length && <Empty text="回收站为空" />}</div></section>
}
