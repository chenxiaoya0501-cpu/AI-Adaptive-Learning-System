import type { CSSProperties } from 'react'
import { Button, Card, Form, Input, Typography, message } from 'antd'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export default function Register() {
  const { register } = useAuth()
  const navigate = useNavigate()

  const onFinish = async (values: {
    email?: string
    phone?: string
    password: string
    nickname?: string
  }) => {
    if (!values.email?.trim() && !values.phone?.trim()) {
      message.error('请填写手机号或邮箱')
      return
    }
    try {
      await register({
        email: values.email?.trim() || undefined,
        phone: values.phone?.trim() || undefined,
        password: values.password,
        nickname: values.nickname?.trim() || undefined,
      })
      message.success('注册成功')
      navigate('/', { replace: true })
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      message.error(typeof detail === 'string' ? detail : '注册失败')
    }
  }

  return (
    <div style={wrapStyle}>
      <Card style={{ width: 420, maxWidth: '92vw' }} title="学生注册">
        <Form layout="vertical" onFinish={onFinish}>
          <Form.Item name="nickname" label="昵称">
            <Input placeholder="可选" size="large" />
          </Form.Item>
          <Form.Item name="email" label="邮箱">
            <Input placeholder="邮箱（与手机号二选一）" size="large" />
          </Form.Item>
          <Form.Item name="phone" label="手机号">
            <Input placeholder="手机号（与邮箱二选一）" size="large" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[
              { required: true, message: '请输入密码' },
              { min: 6, message: '至少 6 位' },
            ]}
          >
            <Input.Password size="large" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block size="large">
            注册并登录
          </Button>
        </Form>
        <Typography.Paragraph style={{ marginTop: 16, marginBottom: 0 }}>
          已有账号？<Link to="/login">去登录</Link>
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
