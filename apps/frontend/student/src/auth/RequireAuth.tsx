import { Navigate, useLocation } from 'react-router-dom'
import { Spin } from 'antd'
import { useAuth } from './AuthContext'

export default function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div style={{ display: 'grid', placeItems: 'center', minHeight: '100vh' }}>
        <Spin size="large" tip="加载中…" />
      </div>
    )
  }

  if (!user) {
    const redirect = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?redirect=${redirect}`} replace />
  }

  return <>{children}</>
}
