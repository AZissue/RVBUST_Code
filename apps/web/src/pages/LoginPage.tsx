import { ArrowRight, LockKeyhole } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const registered = Boolean((location.state as { registered?: boolean } | null)?.registered)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(''); setBusy(true)
    try { await login(username, password); navigate('/') } catch (reason) { setError(reason instanceof Error ? reason.message : '登录失败') } finally { setBusy(false) }
  }
  return <main className="login-page branded-login">
    <img className="login-product-scene" src="/brand/cameras.png" alt="如本科技相机产品全家福" />
    <section className="login-panel">
      <div className="login-brand"><img src="/brand/logo.png" alt="如本科技" /></div>
      <div className="login-heading"><LockKeyhole size={22} /><h1>技术支持系统</h1><p>Support Operations V2</p></div>
      {registered && <div className="success-text">注册成功，等待管理员审批</div>}
      <form onSubmit={submit}>
        <label>账号<input autoFocus autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} /></label>
        <label>密码<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        {error && <div className="form-error">{error}</div>}
        <button className="button primary full" disabled={busy}>{busy ? '正在验证' : '安全登录'}<ArrowRight size={17} /></button>
      </form>
      <p className="security-note">还没有账号？<Link to="/register">注册账号</Link></p>
    </section>
    <footer className="login-footer">RVBUST · 技术支持工作区</footer>
  </main>
}
