import { ArrowLeft, Download, Save } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { downloadRepairPdf } from '../components/ReturnRepairForm'
import { useRemote } from '../hooks/useRemote'
import { api } from '../lib/api'
import type { Customer, Device, RepairOrder, ReturnForm } from '../types'
import { PageError, PageLoading } from './DashboardPage'
import './device-flow.css'

/** 新建返厂单：整页表单，保存后进入返修流程；可保存并生成返厂 PDF */
export function RepairFormPage() {
  const navigate = useNavigate()
  const customers = useRemote(() => api<Customer[]>('/customers'), [])
  const [organizationId, setOrganizationId] = useState('')
  const [serialMode, setSerialMode] = useState<'manual' | 'linked'>('manual')
  const [deviceId, setDeviceId] = useState('')
  const [devices, setDevices] = useState<Device[]>([])
  const [raw, setRaw] = useState('')
  const [suggestion, setSuggestion] = useState('')
  const [data, setData] = useState<ReturnForm>({
    companyName: '', reportedAt: new Date().toLocaleDateString('en-CA'), reporterName: '', reporterPhone: '',
    serialNumber: '', appearance: '', returnAddress: '', salesContact: '李辉', afterSalesContact: '刘海焕',
  })
  const [symptom, setSymptom] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [savedId, setSavedId] = useState<string | null>(null)
  const lock = useRef(false)

  useEffect(() => {
    let active = true
    setDevices([])
    if (organizationId) void api<Device[]>(`/devices?organizationId=${organizationId}`).then((items) => { if (active) setDevices(items) }).catch(() => { if (active) setError('设备加载失败，请重新选择客户') })
    return () => { active = false }
  }, [organizationId])

  const field = (key: keyof ReturnForm, value: string) => setData((current) => ({ ...current, [key]: value }))

  /** 规则提取：手机号 / SN / 顺丰单号，提取结果仅作填入建议，可手动修改 */
  function extract() {
    const phone = raw.match(/(?<!\d)1[3-9]\d{9}(?!\d)/)?.[0]
    const sn = raw.match(/(?:SN|序列号)\s*[:：]?\s*([A-Z0-9_-]+)/i)?.[1]
    const tracking = raw.match(/\bSF\d{10,20}\b/i)?.[0]
    if (phone) field('reporterPhone', phone)
    if (sn && serialMode === 'manual') field('serialNumber', sn)
    const filled = [phone && '电话', sn && 'SN', tracking && '顺丰单号'].filter(Boolean).join('、')
    setSuggestion(filled ? `已识别：${filled}，请核对后保存` : '未识别到明确字段，请手动填写')
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (lock.current) return
    lock.current = true; setBusy(true); setError('')
    const exportPdf = (event.nativeEvent as SubmitEvent).submitter?.getAttribute('value') === 'pdf'
    try {
      if (serialMode === 'linked' && !deviceId) throw new Error('请选择关联设备')
      let id = savedId
      if (!id) {
        const result = await api<RepairOrder>('/repairs', { method: 'POST', body: JSON.stringify({ organizationId, manualSerialNumber: serialMode === 'manual', deviceId: serialMode === 'linked' ? deviceId : undefined, serialNumber: data.serialNumber, symptom, returnForm: data }) })
        id = result.id; setSavedId(id)
      }
      if (exportPdf) await downloadRepairPdf(id)
      navigate('/repairs')
    } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败') } finally { lock.current = false; setBusy(false) }
  }

  if (customers.loading) return <PageLoading />
  if (customers.error) return <PageError message={customers.error} retry={customers.refresh} />

  return <div className="page-stack prototype-flow">
    <header className="page-header"><h1>新建返厂单</h1><Link className="button" to="/repairs"><ArrowLeft size={16} />返回列表</Link></header>
    <form onSubmit={submit}>
      <section className="prototype-semantic">
        <div className="page-header"><h2>智能识别粘贴信息</h2>
          <div className="button-row">
            <button type="button" className="button primary" onClick={extract}>识别并填入</button>
            <button type="button" className="button" onClick={() => { setRaw(''); setSuggestion(''); setError('') }}>清空粘贴</button>
          </div></div>
        <textarea aria-label="粘贴信息" value={raw} onChange={(event) => setRaw(event.target.value)} placeholder="粘贴客户报修信息，可识别电话、SN、顺丰单号" />
        {suggestion && <output>规则提取：{suggestion}</output>}
      </section>
      <section className="prototype-section"><h2>报修设备</h2>
        <div className="prototype-grid">
          <div className="full serial-mode" role="group" aria-label="序列号填写方式"><label><input type="radio" name="serialMode" checked={serialMode === 'manual'} onChange={() => { setSerialMode('manual'); setDeviceId('') }} />手动填写 SN</label><label><input type="radio" name="serialMode" checked={serialMode === 'linked'} onChange={() => { setSerialMode('linked'); field('serialNumber', '') }} />关联已有设备</label></div>
          <label>关联客户 *<select required value={organizationId} onChange={(event) => { setOrganizationId(event.target.value); setDeviceId(''); field('companyName', customers.data?.find((customer) => customer.id === event.target.value)?.name ?? ''); field('serialNumber', '') }}><option value="">选择客户</option>{customers.data?.map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}</select></label>
          {serialMode === 'linked' && <label>关联设备 *<select required value={deviceId} onChange={(event) => { setDeviceId(event.target.value); field('serialNumber', devices.find((device) => device.id === event.target.value)?.serialNumber ?? '') }}><option value="">选择已有设备</option>{devices.map((device) => <option key={device.id} value={device.id}>{device.name} · {device.serialNumber}</option>)}</select></label>}
          <label>报修设备 SN *<input required maxLength={120} readOnly={serialMode === 'linked'} value={data.serialNumber} onChange={(event) => field('serialNumber', event.target.value)} /></label>
        </div>
      </section>
      <section className="prototype-section"><h2>报修信息</h2>
        <div className="prototype-grid three">
          <label>报修单位名称 *<input required maxLength={200} value={data.companyName} onChange={(event) => field('companyName', event.target.value)} /></label>
          <label>报修日期 *<input type="date" required value={data.reportedAt.slice(0, 10)} onChange={(event) => field('reportedAt', event.target.value)} /></label>
          <label>报修人 *<input required maxLength={100} value={data.reporterName} onChange={(event) => field('reporterName', event.target.value)} /></label>
          <label>报修人电话 *<input type="tel" required maxLength={80} value={data.reporterPhone} onChange={(event) => field('reporterPhone', event.target.value)} /></label>
          <label>设备方销售<input maxLength={100} value={data.salesContact} onChange={(event) => field('salesContact', event.target.value)} /></label>
          <label>设备方售后<input maxLength={100} value={data.afterSalesContact} onChange={(event) => field('afterSalesContact', event.target.value)} /></label>
          <label className="full">外观情况 *<textarea required maxLength={1000} rows={2} value={data.appearance} onChange={(event) => field('appearance', event.target.value)} /></label>
          <label className="full">报修原因 *<textarea required maxLength={1000} rows={3} value={symptom} onChange={(event) => setSymptom(event.target.value)} /></label>
          <label className="full">回寄地址及联系人 *<textarea required maxLength={2000} rows={2} value={data.returnAddress} onChange={(event) => field('returnAddress', event.target.value)} /></label>
        </div>
      </section>
      <details className="return-notes"><summary>返厂寄送须知</summary><ol>
        <li>报修设备需经过设备方售后确认方可寄回。</li>
        <li>为防止快递暴力运输导致的损坏，建议对设备做好减震并用顺丰快递。</li>
        <li>报修原因请尽量详细描述故障现象或者原因，如不清楚可以找设备方售后进行咨询。</li>
        <li>返厂维修寄送地址为：深圳市宝安区华丰国际机器人产业园二期A座301 刘海焕：19377730597</li>
      </ol></details>
      {savedId && <p role="status" className="success-text">返修记录已保存，可重试生成 PDF，不会重复建单。</p>}
      {error && <div className="form-error" role="alert">{error}</div>}
      <footer className="prototype-save">
        <Link className="button" to="/repairs">取消</Link>
        <button className="button" value="save" disabled={busy || Boolean(savedId)}><Save size={16} />保存记录</button>
        <button className="button primary" value="pdf" disabled={busy}><Download size={16} />{busy ? '处理中' : savedId ? '重新生成 PDF' : '保存并生成 PDF'}</button>
      </footer>
    </form>
  </div>
}
