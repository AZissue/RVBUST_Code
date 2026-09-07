import { ArrowRight, UserPlus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'

export function RegisterPage() {
  const navigate = useNavigate()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(''); setBusy(true)
    const form = new FormData(event.currentTarget)
    const value = (key: string) => String(form.get(key) ?? '').trim()
    if (value('password') !== value('confirmPassword')) { setError('两次输入的密码不一致'); setBusy(false); return }
    try {
      await api('/auth/register', { method: 'POST', body: JSON.stringify({ username: value('username'), password: value('password'), name: value('name'), department: value('department') || undefined, phone: value('phone') || undefined }) })
      navigate('/login', { state: { registered: true } })
    } catch (reason) { setError(reason instanceof Error ? reason.message : '注册失败') } finally { setBusy(false) }
  }
  return <main className="login-page">
    <section className="login-panel">
      <div className="login-brand"><div className="brand-mark">TS</div><div><strong>技术支持系统</strong><span>安全内部工作台</span></div></div>
      <div className="login-heading"><UserPlus size={22} /><h1>注册账号</h1><p>提交后需等待管理员审批，审批通过即可登录。</p></div>
      <form onSubmit={submit}>
        <label>用户名<input autoFocus autoComplete="username" name="username" required minLength={4} maxLength={30} pattern="[A-Za-z0-9_]+" title="4-30 位字母、数字或下划线" placeholder="4-30 位字母、数字或下划线" /></label>
        <label>密码<input type="password" autoComplete="new-password" name="password" required minLength={10} placeholder="至少 10 位" /></label>
        <label>确认密码<input type="password" autoComplete="new-password" name="confirmPassword" required minLength={10} /></label>
        <label>姓名<input name="name" required /></label>
        <label>部门（选填）<input name="department" /></label>
        <label>手机（选填）<input name="phone" /></label>
        {error && <div className="form-error">{error}</div>}
        <button className="button primary full" disabled={busy}>{busy ? '正在提交' : '提交注册'}<ArrowRight size={17} /></button>
      </form>
      <p className="security-note">已有账号？<Link to="/login">返回登录</Link></p>
    </section>
    <aside className="login-aside"><div><span className="eyebrow">SUPPORT OPERATIONS</span><h2>把技术问题处理过程，变成可追踪的团队资产。</h2><div className="login-metrics"><div><strong>6</strong><span>标准工单状态</span></div><div><strong>4</strong><span>后端角色权限</span></div><div><strong>100%</strong><span>操作可审计</span></div></div></div></aside>
  </main>
}
