import type { CSSProperties } from 'react'
import { Alert, Button, Card, Form, Input, Typography, message } from 'antd'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [form] = Form.useForm()

  const onFinish = async (values: { account: string; password: string }) => {
    try {
      await login(values.account.trim(), values.password)
      message.success('登录成功')
      const redirect = params.get('redirect') || '/'
      navigate(redirect.startsWith('/') ? redirect : '/', { replace: true })
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '登录失败')
    }
  }

  return (
    <div style={wrapStyle}>
      <Card style={{ width: 400, maxWidth: '92vw' }} title="学生登录">
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="开发环境可用演示账号"
          description="demo@local / demo123（后端启动时自动创建）"
        />
        <Form form={form} layout="vertical" onFinish={onFinish}>
          <Form.Item name="account" label="手机号或邮箱" rules={[{ required: true, message: '请输入账号' }]}>
            <Input placeholder="demo@local" size="large" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password placeholder="密码" size="large" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block size="large">
            登录
          </Button>
        </Form>
        <Typography.Paragraph style={{ marginTop: 16, marginBottom: 0 }}>
          还没有账号？<Link to="/register">注册</Link>
        </Typography.Paragraph>
      </Card>
    </div>
  )
}

const wrapStyle: CSSProperties = {
  minHeight: '100vh',
  display: 'grid',
  placeItems: 'center',
  background: 'linear-gradient(160deg, #e8f2f0 0%, #f7f4ea 55%, #f0ebe3 100%)',
  padding: 24,
}
