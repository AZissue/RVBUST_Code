import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { useAuth } from './context/AuthContext'
import { AuditPage } from './pages/AuditPage'
import { BugsPage } from './pages/BugsPage'
import { CustomerProfilePage } from './pages/CustomerProfilePage'
import { DeviceDetailPage } from './pages/DeviceDetailPage'
import { CustomersPage } from './pages/CustomersPage'
import { DashboardPage } from './pages/DashboardPage'
import { DevicesPage } from './pages/DevicesPage'
import { LoansPage } from './pages/LoansPage'
import { LoanDetailPage } from './pages/LoanDetailPage'
import { LoanFormPage } from './pages/LoanFormPage'
import { LoginPage } from './pages/LoginPage'
import { RegisterPage } from './pages/RegisterPage'
import { RepairsPage } from './pages/RepairsPage'
import { RepairFormPage } from './pages/RepairFormPage'
import { ReportsPage } from './pages/ReportsPage'
import { ReportCalendarPage } from './pages/ReportCalendarPage'
import { SettingsPage, TeamsPage } from './pages/SystemPages'
import { TicketDetailPage, TicketsPage } from './pages/TicketsPage'
import { RecycleBinPage } from './pages/RecycleBinPage'
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
    <Route path="/register" element={user ? <Navigate to="/" replace /> : <RegisterPage />} />
    <Route path="/" element={<ProtectedApp />}>
      <Route index element={<DashboardPage />} />
      <Route path="my-work" element={<TicketsPage mine />} />
      <Route path="work-items" element={<WorkItemsPage />} />
      <Route path="tickets" element={<TicketsPage />} />
      <Route path="tickets/recycle-bin" element={<RecycleBinPage />} />
      <Route path="tickets/:id" element={<TicketDetailPage />} />
      <Route path="customers" element={<CustomersPage />} />
      <Route path="customers/:id" element={<CustomerProfilePage />} />
      <Route path="devices" element={<DevicesPage />} />
      <Route path="devices/:id" element={<DeviceDetailPage />} />
      <Route path="loans" element={<LoansPage />} />
      <Route path="loans/new" element={<LoanFormPage />} />
      <Route path="loans/:id" element={<LoanDetailPage />} />
      <Route path="repairs" element={<RepairsPage />} />
      <Route path="repairs/new" element={<RepairFormPage />} />
      <Route path="worklogs" element={<WorklogsPage />} />
      <Route path="reports" element={<ReportCalendarPage />} />
      <Route path="stats" element={<ReportsPage />} />
      <Route path="users" element={<UsersPage />} />
      <Route path="teams" element={<TeamsPage />} />
      <Route path="settings" element={<SettingsPage />} />
      <Route path="audit" element={<AuditPage />} />
      <Route path="bugs" element={<BugsPage />} />
    </Route>
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>
}
