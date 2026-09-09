import { Download, Save } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Modal } from './Modal'
import { api } from '../lib/api'
import { useRemote } from '../hooks/useRemote'
import type { Attachment, Customer, Device, RepairOrder, ReturnForm } from '../types'

export async function downloadRepairPdf(id: string) {
  const attachment = await api<Attachment>(`/repairs/${id}/pdf`, { method: 'POST' })
  const response = await fetch(`/api/files/${attachment.id}`, { credentials: 'include' })
  if (!response.ok) throw new Error('PDF 已归档，下载失败，请从返修详情附件重试')
  const url = URL.createObjectURL(await response.blob())
  const a = document.createElement('a'); a.href = url; a.download = attachment.originalName; a.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 60000)
}

export function ReturnRepairForm({ repair, onClose, onSaved }: { repair?: RepairOrder; onClose: () => void; onSaved: () => Promise<void> }) {
  const customers = useRemote(() => api<Customer[]>('/customers'), [])
  const [organizationId, setOrganizationId] = useState(repair?.organization.id ?? '')
  const [deviceId, setDeviceId] = useState(repair?.device?.id ?? '')
  const [serialMode, setSerialMode] = useState<'manual' | 'linked'>(repair?.device ? 'linked' : 'manual')
  const [devices, setDevices] = useState<Device[]>([])
  const [data, setData] = useState<ReturnForm>(repair?.returnForm ?? {
    companyName: repair?.organization.name ?? '', reportedAt: new Date().toLocaleDateString('en-CA'),
    reporterName: repair?.contact?.name ?? '', reporterPhone: '', serialNumber: repair?.serialNumber ?? repair?.device?.serialNumber ?? '',
    appearance: '', returnAddress: '', salesContact: '李辉', afterSalesContact: '刘海焕',
  })
  const [symptom, setSymptom] = useState(repair?.symptom ?? '')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [savedId, setSavedId] = useState<string | null>(null)
  const lock = useRef(false)
  useEffect(() => {
    let active = true
    setDevices([])
    if (organizationId) void api<Device[]>(`/devices?organizationId=${organizationId}`).then(items => { if (active) setDevices(items) }).catch(() => { if (active) setError('设备加载失败，请重新选择客户') })
    return () => { active = false }
  }, [organizationId])
  const field = (key: keyof ReturnForm, value: string) => setData(current => ({ ...current, [key]: value }))
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (lock.current) return
    lock.current = true; setBusy(true); setError('')
    const exportPdf = (event.nativeEvent as SubmitEvent).submitter?.getAttribute('value') === 'pdf'
    try {
      if (!repair && serialMode === 'linked' && !deviceId) throw new Error('请选择关联设备')
      let id = savedId
      if (!id) {
        const body = repair ? { returnForm: data, symptom } : { organizationId, manualSerialNumber: serialMode === 'manual', deviceId: serialMode === 'linked' ? deviceId : undefined, serialNumber: data.serialNumber, symptom, returnForm: data }
        const result = await api<RepairOrder>(repair ? `/repairs/${repair.id}` : '/repairs', { method: repair ? 'PATCH' : 'POST', body: JSON.stringify(body) })
        id = result.id; setSavedId(id)
      }
      if (exportPdf) await downloadRepairPdf(id)
      await onSaved()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败') }
    finally { lock.current = false; setBusy(false) }
  }
  return <Modal title={repair ? '返厂维修单' : '新建返厂单'} onClose={() => { if (!busy) onClose() }} wide>
    <form onSubmit={submit}>
      {savedId && <p role="status" className="success-text">返修记录已保存，可重试生成 PDF，不会重复建单。</p>}
      <fieldset disabled={busy || Boolean(savedId)} className="return-form-fields form-grid">
        {!repair && <div className="span-2 serial-mode" role="group" aria-label="序列号填写方式"><label><input type="radio" name="serialMode" checked={serialMode === 'manual'} onChange={() => { setSerialMode('manual'); setDeviceId('') }} />手动填写 SN</label><label><input type="radio" name="serialMode" checked={serialMode === 'linked'} onChange={() => { setSerialMode('linked'); field('serialNumber', '') }} />关联已有设备</label></div>}
        {!repair && <><label>关联客户<select required value={organizationId} onChange={e => { setOrganizationId(e.target.value); setDeviceId(''); field('companyName', customers.data?.find(c => c.id === e.target.value)?.name ?? ''); field('serialNumber', '') }}><option value="">选择客户</option>{customers.data?.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
          {serialMode === 'linked' && <label>关联设备<select required value={deviceId} onChange={e => { setDeviceId(e.target.value); field('serialNumber', devices.find(d => d.id === e.target.value)?.serialNumber ?? '') }}><option value="">选择已有设备</option>{devices.map(d => <option key={d.id} value={d.id}>{d.name} · {d.serialNumber}</option>)}</select></label>}</>}
        <label>报修单位名称<input required maxLength={200} value={data.companyName} onChange={e => field('companyName', e.target.value)} /></label>
        <label>报修日期<input type="date" required value={data.reportedAt.slice(0,10)} onChange={e => field('reportedAt', e.target.value)} /></label>
        <label>报修人<input required maxLength={100} value={data.reporterName} onChange={e => field('reporterName', e.target.value)} /></label>
        <label>报修人电话<input type="tel" required maxLength={80} value={data.reporterPhone} onChange={e => field('reporterPhone', e.target.value)} /></label>
        <label>报修设备 SN<input readOnly={serialMode === 'linked'} required maxLength={120} value={data.serialNumber} onChange={e => field('serialNumber', e.target.value)} /></label>
        <label>外观情况<textarea required maxLength={1000} rows={2} value={data.appearance} onChange={e => field('appearance', e.target.value)} /></label>
        <label className="span-2">报修原因<textarea required maxLength={1000} rows={3} value={symptom} onChange={e => setSymptom(e.target.value)} /></label>
        <label className="span-2">回寄地址及联系人<textarea required maxLength={2000} rows={2} value={data.returnAddress} onChange={e => field('returnAddress', e.target.value)} /></label>
        <label>设备方销售<input maxLength={100} value={data.salesContact} onChange={e => field('salesContact', e.target.value)} /></label>
        <label>设备方售后<input maxLength={100} value={data.afterSalesContact} onChange={e => field('afterSalesContact', e.target.value)} /></label>
      </fieldset>
      <details className="return-notes"><summary>返厂寄送须知</summary><ol>
        <li>报修设备需经过设备方售后确认方可寄回。</li>
        <li>为防止快递暴力运输导致的损坏，建议对设备做好减震并用顺丰快递。</li>
        <li>报修原因请尽量详细描述故障现象或者原因，如不清楚可以找设备方售后进行咨询。</li>
        <li>返厂维修寄送地址为：深圳市宝安区华丰国际机器人产业园二期A座301 刘海焕：19377730597</li>
      </ol></details>
      {error && <p role="alert" className="form-error">{error}</p>}
      <div className="form-actions"><button type="button" className="button" disabled={busy} onClick={onClose}>关闭</button><button className="button" value="save" disabled={busy}><Save size={16} />保存记录</button><button className="button primary" value="pdf" disabled={busy}><Download size={16} />{busy ? '处理中' : savedId ? '重新生成 PDF' : '保存并生成 PDF'}</button></div>
    </form>
  </Modal>
}
