import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { useAuth } from './context/AuthContext'
import { AuditPage } from './pages/AuditPage'
import { CustomerDetailPage, CustomersPage } from './pages/CustomersPage'
import { DashboardPage } from './pages/DashboardPage'
import { DevicesPage } from './pages/DevicesPage'
import { LoginPage } from './pages/LoginPage'
import { ReportsPage } from './pages/ReportsPage'
import { SettingsPage, TeamsPage } from './pages/SystemPages'
import { TicketDetailPage, TicketsPage } from './pages/TicketsPage'
import { UsersPage } from './pages/UsersPage'
import { WorklogsPage } from './pages/WorklogsPage'
import { WorkItemsPage } from './pages/WorkItemsPage'

function ProtectedApp() {
  const { user, loading } = useAuth()
  if (loading) return <div className="screen-center"><span className="spinner" />正在校验会话</div>
  if (!user) return <Navigate to="/login" replace />
  if (user.role === 'customer') return <div className="screen-center"><div><h1>客户账号已启用</h1><p className="muted">客户门户将在后续阶段开放。当前账号权限和数据隔离已生效。</p></div></div>
  return <AppShell />
}

export default function App() {
  const { user } = useAuth()
  return <Routes>
    <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />
    <Route path="/" element={<ProtectedApp />}>
      <Route index element={<DashboardPage />} />
      <Route path="my-work" element={<WorkItemsPage mine />} />
      <Route path="work-items" element={<WorkItemsPage />} />
      <Route path="tickets" element={<TicketsPage />} />
      <Route path="tickets/:id" element={<TicketDetailPage />} />
      <Route path="customers" element={<CustomersPage />} />
      <Route path="customers/:id" element={<CustomerDetailPage />} />
      <Route path="devices" element={<DevicesPage />} />
      <Route path="worklogs" element={<WorklogsPage />} />
      <Route path="reports" element={<ReportsPage />} />
      <Route path="stats" element={<ReportsPage />} />
      <Route path="users" element={<UsersPage />} />
      <Route path="teams" element={<TeamsPage />} />
      <Route path="settings" element={<SettingsPage />} />
      <Route path="audit" element={<AuditPage />} />
    </Route>
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>
}
