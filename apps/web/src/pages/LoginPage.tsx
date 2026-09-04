import { ArrowRight, LockKeyhole } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(''); setBusy(true)
    try { await login(username, password); navigate('/') } catch (reason) { setError(reason instanceof Error ? reason.message : '登录失败') } finally { setBusy(false) }
  }
  return <main className="login-page">
    <section className="login-panel">
      <div className="login-brand"><div className="brand-mark">TS</div><div><strong>技术支持系统</strong><span>安全内部工作台</span></div></div>
      <div className="login-heading"><LockKeyhole size={22} /><h1>登录工作区</h1><p>使用分配给你的内部账号继续。</p></div>
      <form onSubmit={submit}>
        <label>账号<input autoFocus autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} /></label>
        <label>密码<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        {error && <div className="form-error">{error}</div>}
        <button className="button primary full" disabled={busy}>{busy ? '正在验证' : '安全登录'}<ArrowRight size={17} /></button>
      </form>
      <p className="security-note">会话使用 HttpOnly Cookie，密码不会保存在浏览器中。</p>
    </section>
    <aside className="login-aside"><div><span className="eyebrow">SUPPORT OPERATIONS</span><h2>把技术问题处理过程，变成可追踪的团队资产。</h2><div className="login-metrics"><div><strong>6</strong><span>标准工单状态</span></div><div><strong>4</strong><span>后端角色权限</span></div><div><strong>100%</strong><span>操作可审计</span></div></div></div></aside>
  </main>
}

