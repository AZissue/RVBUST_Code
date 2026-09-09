import { Save } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { api } from '../lib/api'
import { repairStatusLabels } from '../lib/labels'
import type { RepairOrder, RepairStatus } from '../types'

export function RepairStatusEditor({ repair, onSaved }: { repair: RepairOrder; onSaved: () => Promise<void> }) {
  const [target, setTarget] = useState<RepairStatus>(repair.status)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const statuses = Object.keys(repairStatusLabels) as RepairStatus[]
  const needsReason = statuses.indexOf(target) !== statuses.indexOf(repair.status) + 1
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    try {
      await api(`/repairs/${repair.id}/transition`, { method: 'POST', body: JSON.stringify({ status: target, expectedStatus: repair.status, content: String(form.get('content') ?? '').trim(), trackingNo: String(form.get('trackingNo') ?? repair.trackingNo ?? '').trim() || undefined }) })
      await onSaved()
    } catch (e) { setError(e instanceof Error ? e.message : '状态修改失败') }
    finally { setBusy(false) }
  }
  return <form className="drawer-form" onSubmit={submit}>
    <label>修改返修状态<select aria-label="修改返修状态" value={target} disabled={busy} onChange={e => setTarget(e.target.value as RepairStatus)}>{statuses.map(status => <option key={status} value={status}>{repairStatusLabels[status]}</option>)}</select></label>
    {target !== repair.status && <>
      {target === 'SHIPPED' && <label>物流单号<input name="trackingNo" defaultValue={repair.trackingNo ?? ''} required maxLength={100} /></label>}
      <label>调整原因{needsReason ? '（必填）' : '（选填）'}<textarea name="content" required={needsReason} maxLength={2000} rows={2} /></label>
      <div className="drawer-actions"><button className="button primary" disabled={busy}><Save size={15} />{busy ? '保存中' : '确认修改状态'}</button></div>
    </>}
    {error && <p role="alert" className="form-error">{error}</p>}
  </form>
}
