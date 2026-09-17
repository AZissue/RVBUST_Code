import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export function DeviceFlowHost() {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="screen-center"><span className="spinner" />正在校验会话</div>
  if (!user) return <Navigate to="/login" replace />
  const tab = new URLSearchParams(location.search).get('tab')
  const query = tab && ['dashboard', 'repairs', 'loans', 'recycle'].includes(tab) ? `?tab=${tab}` : ''
  return <iframe title="设备流转管理" src={`/device-flow.html${query}`} style={{ display: 'block', width: '100%', height: '100dvh', border: 0 }} />
}
