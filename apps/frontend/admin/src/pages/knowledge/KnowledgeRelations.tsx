import { useEffect, useState } from 'react'
import { Table, Button, Space, Tag, Modal, Form, Input, Select, message, Popconfirm, Card, Typography } from 'antd'
import { PlusOutlined, DeleteOutlined, SyncOutlined } from '@ant-design/icons'
import { knowledgeApi } from '../../api'

const { Title } = Typography
const { Option } = Select

export default function KnowledgeRelations() {
  const [loading, setLoading] = useState(false)
  const [relations, setRelations] = useState<any[]>([])
  const [modalVisible, setModalVisible] = useState(false)
  const [form] = Form.useForm()
  const [filterType, setFilterType] = useState<string | undefined>()
  const [filterPointId, setFilterPointId] = useState<string | undefined>()

  const fetchData = async () => {
    setLoading(true)
    try {
      const params: any = {}
      if (filterType) params.relation_type = filterType
      if (filterPointId) params.point_id = filterPointId
      const res = await knowledgeApi.listRelations(params)
      setRelations(res.data || [])
    } catch {
      message.error('获取数据失败')
    }
    setLoading(false)
  }

  useEffect(() => { fetchData() }, [filterType, filterPointId])

  const handleCreate = async () => {
    const values = await form.validateFields()
    try {
      await knowledgeApi.createRelation(values)
      message.success('创建成功')
      setModalVisible(false)
      form.resetFields()
      fetchData()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '创建失败')
    }
  }

  const handleDelete = async (id: number) => {
    await knowledgeApi.deleteRelation(id)
    message.success('已删除')
    fetchData()
  }

  const handleClearAll = async () => {
    try {
      const res = await knowledgeApi.clearAllRelations()
      message.success(res.data?.message || '已清除全部关系')
      fetchData()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '清除失败')
    }
  }

  const handleSyncPrerequisites = async () => {
    try {
      const res = await knowledgeApi.syncRelationPrerequisites()
      message.success(res.data?.message || '依赖知识点同步完成')
    } catch (e: any) {
      message.error(e.response?.data?.detail || '同步失败')
    }
  }

  const relationTypeLabels: Record<string, { label: string; color: string; desc: string }> = {
    prerequisite: { label: '前置依赖', color: 'red', desc: '学目标知识点前必须先学起始知识点' },
    related: { label: '相关', color: 'blue', desc: '两个知识点属于同类或有类比关系，无严格先后' },
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: '起始知识点ID', dataIndex: 'from_point_id', key: 'from_point_id', width: 140 },
    { title: '起始知识点描述', dataIndex: 'from_point_name', key: 'from_point_name', width: 250, ellipsis: true,
      render: (v: string) => v || '-'
    },
    { title: '起始知识点名称', dataIndex: 'from_point_short_name', key: 'from_point_short_name', width: 120,
      render: (v: string) => v || '-'
    },
    { title: '目标知识点ID', dataIndex: 'to_point_id', key: 'to_point_id', width: 140 },
    { title: '目标知识点描述', dataIndex: 'to_point_name', key: 'to_point_name', width: 250, ellipsis: true,
      render: (v: string) => v || '-'
    },
    { title: '目标知识点名称', dataIndex: 'to_point_short_name', key: 'to_point_short_name', width: 120,
      render: (v: string) => v || '-'
    },
    {
      title: '关系类型', dataIndex: 'relation_type', key: 'relation_type', width: 120,
      render: (v: string) => {
        const info = relationTypeLabels[v] || { label: v, color: 'default', desc: '' }
        return <Tag color={info.color}>{info.label}</Tag>
      }
    },
    { title: '权重', dataIndex: 'weight', key: 'weight', width: 80 },
    {
      title: '操作', key: 'action', width: 80,
      render: (_: any, record: any) => (
        <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id)}>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      )
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>知识点关系管理</Title>
        <Space>
          <Button icon={<SyncOutlined />} onClick={handleSyncPrerequisites}>
            同步依赖知识点
          </Button>
          <Popconfirm
            title="确认清除全部关系？"
            description="将删除所有知识点关系，此操作不可恢复。"
            onConfirm={handleClearAll}
            okText="确认清除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button danger icon={<DeleteOutlined />}>一键清除关系</Button>
          </Popconfirm>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalVisible(true)}>新建关系</Button>
        </Space>
      </div>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space>
          <Input
            placeholder="按知识点ID筛选"
            allowClear
            style={{ width: 200 }}
            onChange={e => setFilterPointId(e.target.value || undefined)}
          />
          <Select placeholder="关系类型" allowClear style={{ width: 130 }} onChange={v => setFilterType(v)}>
            <Option value="prerequisite">前置依赖</Option>
            <Option value="related">相关</Option>
          </Select>
        </Space>
      </Card>

      <Card size="small" style={{ marginBottom: 16, background: '#fffbe6', border: '1px solid #ffe58f' }}>
        <p style={{ margin: 0 }}>
          <strong>关系含义：</strong>
          <Tag color="red">前置依赖</Tag> 学目标知识点前必须先学起始知识点 &nbsp;|&nbsp;
          <Tag color="blue">相关</Tag> 两个知识点属于同类或有类比关系，无严格先后顺序
        </p>
      </Card>

      <Table
        columns={columns}
        dataSource={relations}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={{ pageSize: 20, showTotal: t => `共 ${t} 条` }}
        scroll={{ x: 1450 }}
      />

      <Modal
        title="新建知识点关系"
        open={modalVisible}
        onOk={handleCreate}
        onCancel={() => { setModalVisible(false); form.resetFields() }}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="from_point_id" label="起始知识点ID（被依赖方）" rules={[{ required: true }]}>
            <Input placeholder="如: MATH-7-01-001" />
          </Form.Item>
          <Form.Item name="to_point_id" label="目标知识点ID（依赖方）" rules={[{ required: true }]}>
            <Input placeholder="如: MATH-7-01-002" />
          </Form.Item>
          <Form.Item name="relation_type" label="关系类型" rules={[{ required: true }]}>
            <Select placeholder="选择关系类型">
              <Option value="prerequisite">前置依赖（学目标知识点前必须先学起始知识点）</Option>
              <Option value="related">相关（同类知识或类比关系，无严格先后）</Option>
            </Select>
          </Form.Item>
          <Form.Item name="weight" label="权重" initialValue={1.0}>
            <Input type="number" min={0} max={10} step={0.1} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
