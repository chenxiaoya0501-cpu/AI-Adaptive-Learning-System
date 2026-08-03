import { useEffect, useState } from 'react'
import { Card, Row, Col, Statistic, Typography } from 'antd'
import { ApartmentOutlined, NodeIndexOutlined, FileTextOutlined } from '@ant-design/icons'
import { knowledgeApi } from '../api'

const { Title } = Typography

export default function Dashboard() {
  const [stats, setStats] = useState<any>(null)

  useEffect(() => {
    knowledgeApi.getStats().then(res => setStats(res.data)).catch(() => {})
  }, [])

  return (
    <div>
      <Title level={4}>系统概览</Title>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="知识点总数"
              value={stats?.total || 0}
              prefix={<ApartmentOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="知识关系数"
              value={stats?.relation_count || 0}
              prefix={<NodeIndexOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="已发布"
              value={stats?.by_status?.published || 0}
              prefix={<FileTextOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="待审核"
              value={stats?.by_status?.draft || 0}
              prefix={<FileTextOutlined />}
              valueStyle={{ color: '#faad14' }}
            />
          </Card>
        </Col>
      </Row>

      {stats && (
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col span={12}>
            <Card title="按领域分布">
              {Object.entries(stats.by_domain || {}).map(([domain, count]) => (
                <div key={domain} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
                  <span>{domain}</span>
                  <span style={{ fontWeight: 'bold' }}>{count as number}</span>
                </div>
              ))}
            </Card>
          </Col>
          <Col span={12}>
            <Card title="按年级分布">
              {Object.entries(stats.by_grade || {}).map(([grade, count]) => (
                <div key={grade} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
                  <span>{grade}年级</span>
                  <span style={{ fontWeight: 'bold' }}>{count as number}</span>
                </div>
              ))}
            </Card>
          </Col>
        </Row>
      )}
    </div>
  )
}
