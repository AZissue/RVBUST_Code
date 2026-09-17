import { memo, useEffect, useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { Navigate } from 'react-router-dom'
import markup from './device-flow-body.html?raw'
import './device-flow.css'

interface DeviceFlowApp {
  init: () => Promise<void>
  dispose: () => void
}

declare global {
  interface Window { deviceFlowApp?: DeviceFlowApp }
}

/* 挂载容器单独 memo：父组件任何重渲染都不得触碰 innerHTML，
   否则会把设备流转应用渲染好的 DOM 重置回原始片段。 */
const DeviceFlowMount = memo(function DeviceFlowMount({ html }: { html: string }) {
  return <div className="device-flow-mount is-ready" dangerouslySetInnerHTML={{ __html: html }} />
})

let appLoading: Promise<void> | null = null

function loadScript(src: string) {
  return new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = src
    script.onload = () => resolve()
    script.onerror = () => reject(new Error(`加载 ${src} 失败`))
    document.body.append(script)
  })
}

function ensureDeviceFlowApp() {
  appLoading ??= (async () => {
    await loadScript('/flow-online.js')
    await loadScript('/device-flow-app.js')
  })()
  return appLoading
}

export function DeviceFlowPage() {
  const { user, loading } = useAuth()
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!user) return
    let cancelled = false
    setReady(false)
    setError('')
    ensureDeviceFlowApp()
      .then(() => window.deviceFlowApp!.init())
      .then(() => { if (!cancelled) setReady(true) })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : '设备流转页面加载失败') })
    return () => {
      cancelled = true
      window.deviceFlowApp?.dispose()
    }
  }, [user])

  if (loading) return <div className="screen-center"><span className="spinner" />正在校验会话</div>
  if (!user) return <Navigate to="/login" replace />
  if (error) return <div className="state-page"><strong>设备流转管理加载失败</strong><span>{error}</span></div>

  return <div className="device-flow-page">
    <div className="page-header">
      <div>
        <h1>设备服务管理</h1>
        <p>维修 · 借测 · 设备档案，数据实时保存到服务器</p>
      </div>
    </div>
    {!ready && <div className="flow-loading"><span className="spinner" />正在加载设备流转数据…</div>}
    <div style={ready ? undefined : { display: 'none' }}>
      <DeviceFlowMount html={markup} />
    </div>
  </div>
}
