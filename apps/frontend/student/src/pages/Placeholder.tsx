import { Card, Typography } from 'antd'

export default function Placeholder({ title, hint }: { title: string; hint?: string }) {
  return (
    <Card>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        {title}
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        {hint || '该模块将在后续步骤实现，敬请期待。'}
      </Typography.Paragraph>
    </Card>
  )
}
