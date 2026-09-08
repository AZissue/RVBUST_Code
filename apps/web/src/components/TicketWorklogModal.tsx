import { useRef, useState, type FormEvent } from 'react'
import { Save } from 'lucide-react'
import { Modal } from './Modal'
import { useRemote } from '../hooks/useRemote'
import { api } from '../lib/api'
import type { Ticket, WorkType } from '../types'

export function TicketWorklogModal({ ticket, onClose, onSaved }: { ticket: Ticket; onClose: () => void; onSaved: () => void }) {
  const types = useRemote(() => api<WorkType[]>('/work-types'), [])
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const [error, setError] = useState('')
  const [occurredAt] = useState(() => {
    const now = new Date()
    return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
  })
  const activeTypes = types.data?.filter(type => type.isActive) ?? []
  const preferred = activeTypes.find(type => type.label === '客户支持')?.id ?? activeTypes[0]?.id
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (lock.current) return
    lock.current = true; setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    const value = (key: string) => String(form.get(key) ?? '').trim()
    try {
      await api('/worklogs', { method: 'POST', body: JSON.stringify({
        ticketId: ticket.id, organizationId: ticket.organization.id, projectId: ticket.project?.id,
        workTypeId: value('workTypeId'), occurredAt: new Date(value('occurredAt')).toISOString(),
        summary: value('summary'), actions: value('actions') || undefined,
        result: value('result') || undefined, nextStep: value('nextStep') || undefined,
        durationMinutes: value('durationMinutes') ? Number(value('durationMinutes')) : undefined,
        source: 'WEB', status: 'CONFIRMED',
      }) })
      onSaved()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败') }
    finally { lock.current = false; setBusy(false) }
  }
  return <Modal title="登记工作记录" onClose={() => { if (!lock.current) onClose() }} wide>
    <p className="muted">{ticket.number} · {ticket.organization.name}</p>
    <form className="form-grid" onSubmit={submit}>
      <label className="span-2">做了什么<input name="summary" required minLength={2} maxLength={240} autoFocus /></label>
      <label>工作分类{types.loading ? <span>加载中…</span> : <select name="workTypeId" required defaultValue={preferred}>{activeTypes.map(type => <option key={type.id} value={type.id}>{type.label}</option>)}</select>}</label>
      <label>发生时间<input name="occurredAt" type="datetime-local" required defaultValue={occurredAt} /></label>
      <label className="span-2">处理结果<textarea name="result" rows={3} maxLength={10000} /></label>
      <label className="span-2">下一步<textarea name="nextStep" rows={2} maxLength={10000} /></label>
      <details className="span-2"><summary>补充信息</summary><div className="form-grid">
        <label className="span-2">具体操作<textarea name="actions" rows={3} maxLength={10000} /></label>
        <label>耗时（分钟）<input name="durationMinutes" type="number" min={0} max={1440} step={1} /></label>
      </div></details>
      {(error || types.error) && <div role="alert" className="form-error span-2">{error || types.error}{types.error && <button type="button" onClick={() => void types.refresh()}>重试</button>}</div>}
      <div className="form-actions span-2"><button type="button" className="button" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={busy || types.loading || !activeTypes.length}><Save size={16} />{busy ? '保存中' : '保存记录'}</button></div>
    </form>
  </Modal>
}
