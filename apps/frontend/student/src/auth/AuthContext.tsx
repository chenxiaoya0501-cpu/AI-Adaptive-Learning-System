import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import {
  authApi,
  clearSession,
  loadCachedUser,
  saveSession,
  type UserPublic,
} from '../api/auth'
import { getToken } from '../api/client'

type AuthContextValue = {
  user: UserPublic | null
  loading: boolean
  login: (account: string, password: string) => Promise<void>
  register: (payload: {
    email?: string
    phone?: string
    password: string
    nickname?: string
  }) => Promise<void>
  logout: () => void
  refreshMe: () => Promise<void>
  setUser: (u: UserPublic | null) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(() => loadCachedUser())
  const [loading, setLoading] = useState(true)

  const refreshMe = useCallback(async () => {
    if (!getToken()) {
      setUser(null)
      return
    }
    const { data } = await authApi.me()
    setUser(data)
    localStorage.setItem('student_user', JSON.stringify(data))
  }, [])

  useEffect(() => {
    ;(async () => {
      try {
        if (getToken()) {
          await refreshMe()
        } else {
          setUser(null)
        }
      } catch {
        clearSession()
        setUser(null)
      } finally {
        setLoading(false)
      }
    })()
  }, [refreshMe])

  const login = useCallback(async (account: string, password: string) => {
    const { data } = await authApi.login({ account, password })
    saveSession(data)
    setUser(data.user)
  }, [])

  const register = useCallback(
    async (payload: {
      email?: string
      phone?: string
      password: string
      nickname?: string
    }) => {
      const { data } = await authApi.register(payload)
      saveSession(data)
      setUser(data.user)
    },
    [],
  )

  const logout = useCallback(() => {
    clearSession()
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, loading, login, register, logout, refreshMe, setUser }),
    [user, loading, login, register, logout, refreshMe],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
