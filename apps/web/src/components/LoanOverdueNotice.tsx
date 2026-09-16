import { useEffect, useRef, useState } from 'react'
import { TriangleAlert } from 'lucide-react'
import { useRemote } from '../hooks/useRemote'
import { api } from '../lib/api'

type OverdueResult = {
  total: number
  items: { id: string; organization: { name: string }; overdueDays: number }[]
}

/** 逾期提醒：进入借测管理时强制确认；同一天且逾期数量不变时不重复打断 */
export function LoanOverdueNotice({ onReview }: { onReview: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [acknowledged, setAcknowledged] = useState(false)
  const remote = useRemote(() => api<OverdueResult>('/loans/list?status=overdue&pageSize=20'), [])
  useEffect(() => {
    if (!remote.data?.total) return
    const day = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date())
    const key = `crm-overdue-ack:${day}:${remote.data.total}`
    let alreadyAcknowledged = false
    try { alreadyAcknowledged = sessionStorage.getItem(key) === '1' } catch { /* 浏览器可能禁用存储 */ }
    if (alreadyAcknowledged) { setAcknowledged(true); return }
    if (!acknowledged && remote.data.total > 0 && !dialog.current?.open) dialog.current?.showModal()
  }, [remote.data, acknowledged])

  function acknowledge(review: boolean) {
    dialog.current?.close()
    setAcknowledged(true)
    const day = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date())
    if (remote.data) {
      try { sessionStorage.setItem(`crm-overdue-ack:${day}:${remote.data.total}`, '1') } catch { /* 存储不可用时忽略 */ }
    }
    if (review) onReview()
  }

  return (
    <dialog ref={dialog} className="loan-overdue-dialog" aria-labelledby="loan-overdue-title" onCancel={(event) => event.preventDefault()}>
      <div className="loan-overdue-heading">
        <TriangleAlert size={25} />
        <h2 id="loan-overdue-title">借测设备逾期提醒</h2>
      </div>
      <p>有 <strong>{remote.data?.total || 0}</strong> 条借测记录已逾期，尚未归还。</p>
      <ul>
        {remote.data?.items.slice(0, 3).map((row) => (
          <li key={row.id}><span>{row.organization.name}</span><strong>逾期 {row.overdueDays} 天</strong></li>
        ))}
      </ul>
      <footer>
        <button type="button" className="button" onClick={() => acknowledge(false)}>我已知晓</button>
        <button type="button" className="button primary" onClick={() => acknowledge(true)}>查看逾期记录</button>
      </footer>
    </dialog>
  )
}
