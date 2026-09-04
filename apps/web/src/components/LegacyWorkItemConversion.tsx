import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useRemote } from '../hooks/useRemote'
import { api } from '../lib/api'
import type { Customer, Ticket, WorkItem } from '../types'

export function LegacyWorkItemConversion({ items, onSaved }: { items: WorkItem[]; onSaved: () => Promise<void> }) {
  const customers = useRemote(() => api<Customer[]>('/customers'), [])
  const [itemId, setItemId] = useState('')
  const [customerId, setCustomerId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [ticket, setTicket] = useState<Ticket | null>(null)
  const selected = items.find((i) => i.id === itemId)
  const convert = async () => {
    if (!selected || !customerId || !window.confirm(`确认将“${selected.title}”转换为客户工单？原事项将保留并锁定，关联工作记录将链接到工单。纯内部工作请保留原状。`)) return
    setBusy(true); setError('')
    try { setTicket(await api<Ticket>(`/tickets/from-work-item/${itemId}`, { method: 'POST', body: JSON.stringify({ organizationId: customerId }) })); setItemId(''); await onSaved() }
    catch (e) { setError(e instanceof Error ? e.message : '转换失败') } finally { setBusy(false) }
  }
  return <section className="workspace-section"><h2>历史事项转换</h2><div className="toolbar"><label>待转换事项<select value={itemId} onChange={(e) => { setItemId(e.target.value); setCustomerId(items.find((i) => i.id === e.target.value)?.organization?.id ?? '') }}><option value="">选择历史事项</option>{items.filter((i) => !i.convertedTicketId).map((i) => <option key={i.id} value={i.id}>{i.title}</option>)}</select></label><label>客户<select disabled={Boolean(selected?.organization)} value={customerId} onChange={(e) => setCustomerId(e.target.value)}><option value="">选择真实客户</option>{customers.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label><button className="button" disabled={busy || !selected || !customerId} onClick={() => void convert()}>{busy ? '正在转换' : '确认转换为工单'}</button></div>{error && <div role="alert" className="form-error">{error}</div>}{ticket && <Link to={`/tickets/${ticket.id}`}>查看工单 {ticket.number}</Link>}{items.filter((i) => i.convertedTicketId).map((i) => <p key={i.id}><Link to={`/tickets/${i.convertedTicketId}`}>{i.title} · 查看关联工单</Link></p>)}</section>
}
