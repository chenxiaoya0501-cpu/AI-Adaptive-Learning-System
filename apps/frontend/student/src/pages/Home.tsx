import { Button, Typography } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export default function Home() {
  const { user } = useAuth()
  const navigate = useNavigate()

  return (
    <div
      style={{
        minHeight: '60vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        padding: '48px 24px',
      }}
    >
      <Typography.Title level={2} style={{ marginTop: 0, marginBottom: 8 }}>
        你好，{user?.nickname || '同学'}
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 32, maxWidth: 360 }}>
        先创建学习目标，系统再按你的目标与已学范围规划测评与学习。
      </Typography.Paragraph>
      <Button
        type="primary"
        size="large"
        icon={<PlusOutlined />}
        onClick={() => navigate('/goals/new')}
      >
        创建目标
      </Button>
    </div>
  )
}
