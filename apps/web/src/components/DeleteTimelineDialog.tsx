import { Trash2 } from 'lucide-react'
import { useRef, useState, type FormEvent } from 'react'
import { Modal } from './Modal'
import { api } from '../lib/api'

export function DeleteTimelineDialog({ ticketId, event, onClose, onDeleted }: { ticketId: string; event: { id: string; content: string }; onClose: () => void; onDeleted: () => Promise<void> }) {
  const lock = useRef(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault(); if (lock.current) return
    const reason = String(new FormData(e.currentTarget).get('reason') ?? '').trim()
    if (!reason) { setError('请填写删除原因'); return }
    lock.current = true; setBusy(true); setError('')
    try { await api(`/tickets/${ticketId}/events/${event.id}`, { method: 'DELETE', body: JSON.stringify({ reason }) }); await onDeleted() }
    catch (error) { setError(error instanceof Error ? error.message : '删除失败') }
    finally { lock.current = false; setBusy(false) }
  }
  return <Modal title="删除流程记录" onClose={() => { if (!busy) onClose() }}><form className="form-grid" onSubmit={submit}>
    <p className="span-2" style={{ maxHeight: 160, overflow: 'auto', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>{event.content}</p>
    <p className="span-2">仅删除这条时间线展示；当前工单状态、协助邀请、附件及工作记录不变。原记录保留在操作日志中。</p>
    <label className="span-2">删除原因<textarea name="reason" required maxLength={1000} rows={2} autoFocus disabled={busy} /></label>
    {error && <p role="alert" className="form-error span-2">{error}</p>}
    <div className="form-actions span-2"><button className="button" type="button" onClick={onClose} disabled={busy}>取消</button><button className="button danger" disabled={busy}><Trash2 size={16} />{busy ? '删除中' : '确认删除记录'}</button></div>
  </form></Modal>
}
