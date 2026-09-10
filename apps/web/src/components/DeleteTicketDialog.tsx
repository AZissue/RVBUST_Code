import { Trash2 } from 'lucide-react'
import { useRef, useState, type FormEvent } from 'react'
import { Modal } from './Modal'
import { api } from '../lib/api'
import type { Ticket } from '../types'

export function DeleteTicketDialog({ ticket, onClose, onDeleted }: { ticket: Ticket; onClose: () => void; onDeleted: () => void | Promise<void> }) {
  const lock = useRef(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (lock.current) return
    const reason = String(new FormData(event.currentTarget).get('reason') ?? '').trim()
    lock.current = true; setBusy(true); setError('')
    try { await api(`/tickets/${ticket.id}`, { method: 'DELETE', body: JSON.stringify({ reason }) }); await onDeleted() }
    catch (e) { setError(e instanceof Error ? e.message : '删除失败') }
    finally { lock.current = false; setBusy(false) }
  }
  return <Modal title="移入回收站" onClose={() => { if (!busy) onClose() }}><form className="form-grid" onSubmit={submit}>
    <p className="span-2">{ticket.number} · {ticket.title}</p>
    <label className="span-2">删除原因（选填）<textarea name="reason" maxLength={1000} rows={3} autoFocus disabled={busy} /></label>
    {error && <p className="form-error span-2" role="alert">{error}</p>}
    <div className="form-actions span-2"><button type="button" className="button" disabled={busy} onClick={onClose}>取消</button><button className="button danger" disabled={busy}><Trash2 size={16} />{busy ? '处理中' : '确认移入回收站'}</button></div>
  </form></Modal>
}
