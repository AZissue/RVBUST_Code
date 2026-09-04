import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../lib/api'
import type { User } from '../types'

interface AuthValue {
  user: User | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api<{ user: User }>('/auth/me').then((result) => setUser(result.user)).catch(() => setUser(null)).finally(() => setLoading(false))
  }, [])

  const value = useMemo<AuthValue>(() => ({
    user,
    loading,
    login: async (username, password) => { const result = await api<{ user: User }>('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }); setUser(result.user) },
    logout: async () => { await api('/auth/logout', { method: 'POST' }); setUser(null) },
  }), [user, loading])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}

