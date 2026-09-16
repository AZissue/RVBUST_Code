import { ArrowLeft, Save } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useRemote } from '../hooks/useRemote'
import { api } from '../lib/api'
import type { Contact, Customer, LoanOrder } from '../types'
import { PageError, PageLoading } from './DashboardPage'
import './device-flow.css'

/** 新建借测工单：保存后进入借测队列（排队评分），设备与日期在借出登记时补充 */
export function LoanFormPage() {
  const navigate = useNavigate()
  const form = useRef<HTMLFormElement>(null)
  const customers = useRemote(() => api<Customer[]>('/customers'), [])
  const [organizationId, setOrganizationId] = useState('')
  const [contacts, setContacts] = useState<Contact[]>([])
  const [raw, setRaw] = useState('')
  const [sns, setSns] = useState('')
  const [suggestion, setSuggestion] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!organizationId) { setContacts([]); return }
    void api<Customer>(`/customers/${organizationId}`).then((customer) => setContacts(customer.contacts ?? [])).catch(() => setContacts([]))
  }, [organizationId])

  /** 规则提取：手机号 / SN / 型号 / 顺丰单号，提取结果仅作填入建议，可手动修改 */
  function extract() {
    const phone = raw.match(/(?<!\d)1[3-9]\d{9}(?!\d)/)?.[0]
    const snList = raw.match(/(?:SN|序列号)\s*[:：]?\s*([A-Z0-9_-]+)/gi)?.map((item) => item.replace(/^(?:SN|序列号)\s*[:：]?\s*/i, '')) ?? []
    const model = raw.match(/\b(?:M|I|P)\d{3,5}[A-Z]?\b/i)?.[0]
    const tracking = raw.match(/\bSF\d{10,20}\b/i)?.[0]
    if (snList.length) setSns(snList.join('\n'))
    const filled = [phone && '电话', snList.length && 'SN', model && '型号', tracking && '寄出单号'].filter(Boolean).join('、')
    setSuggestion(filled ? `已识别：${filled}，请核对后保存` : '未识别到明确字段，请手动填写')
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return; setBusy(true); setError('')
    const formData = new FormData(event.currentTarget)
    const get = (key: string) => String(formData.get(key) ?? '').trim()
    try {
      const created = await api<LoanOrder>('/loans', { method: 'POST', body: JSON.stringify({
        organizationId: get('organizationId'), contactId: get('contactId') || undefined,
        purpose: get('purpose'), assessmentResult: get('assessmentResult') || undefined,
        score: get('score') ? Number(get('score')) : undefined, agreementNo: get('agreementNo') || undefined,
        note: [sns.trim() ? `拟借设备：${sns.trim().split('\n').filter(Boolean).join(' / ')}` : '', get('note')].filter(Boolean).join('\n') || undefined,
      }) })
      navigate(`/loans/${created.id}`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '创建失败') } finally { setBusy(false) }
  }

  if (customers.loading) return <PageLoading />
  if (customers.error) return <PageError message={customers.error} retry={customers.refresh} />

  return <div className="page-stack prototype-flow">
    <header className="page-header"><h1>新建借测工单</h1><Link className="button" to="/loans"><ArrowLeft size={16} />返回列表</Link></header>
    <form ref={form} onSubmit={submit}>
      <section className="prototype-semantic">
        <div className="page-header"><h2>智能识别粘贴信息</h2>
          <div className="button-row">
            <button type="button" className="button primary" onClick={extract}>识别并填入</button>
            <button type="button" className="button" onClick={() => { form.current?.reset(); setRaw(''); setSns(''); setSuggestion(''); setOrganizationId(''); setError('') }}>全部清空</button>
          </div></div>
        <textarea aria-label="粘贴信息" value={raw} onChange={(event) => setRaw(event.target.value)} placeholder="粘贴客户需求、聊天记录或邮件，可识别电话、SN、型号、顺丰单号" />
        {suggestion && <output>规则提取：{suggestion}</output>}
      </section>
      <section className="prototype-section"><h2>拟借设备（选填）</h2>
        <div className="prototype-grid">
          <label className="full">SN / 型号<textarea name="sns" rows={2} value={sns} onChange={(event) => setSns(event.target.value)} placeholder="每行一个 SN，借出登记时自动建档为公司样机" /></label>
        </div>
      </section>
      <section className="prototype-section"><h2>客户与联系人</h2>
        <div className="prototype-grid three">
          <label>客户 *<select name="organizationId" required value={organizationId} onChange={(event) => setOrganizationId(event.target.value)}><option value="" disabled>选择客户</option>{customers.data?.map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}</select></label>
          <label>联系人<select name="contactId" defaultValue=""><option value="">不指定</option>{contacts.map((contact) => <option key={contact.id} value={contact.id}>{contact.name}</option>)}</select></label>
          <label>协议编号<input name="agreementNo" /></label>
        </div>
      </section>
      <section className="prototype-section"><h2>借测信息</h2>
        <div className="prototype-grid">
          <label className="full">借测目的 *<textarea name="purpose" required rows={2} placeholder="客户应用场景、测试内容、期望周期" /></label>
          <label className="full">售前评估结论<textarea name="assessmentResult" rows={2} placeholder="需求评估、方案匹配度、是否建议借测" /></label>
          <label>初始评分（0-100，可后补）<input name="score" type="number" min={0} max={100} step={1} /></label>
          <label>备注<input name="note" /></label>
        </div>
        <p className="placeholder-text">保存后进入借测队列，补充评分后按评分排序；信息完善后安排借出，借出时登记设备 SN、日期、物流与协议。</p>
      </section>
      {error && <div className="form-error" role="alert">{error}</div>}
      <footer className="prototype-save">
        <Link className="button" to="/loans">取消</Link>
        <button className="button primary" disabled={busy}><Save size={17} />{busy ? '保存中' : '保存并入队'}</button>
      </footer>
    </form>
  </div>
}
