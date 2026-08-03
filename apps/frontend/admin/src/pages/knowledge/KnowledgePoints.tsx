import { useEffect, useState } from 'react'
import { Table, Button, Space, Tag, Input, Select, Modal, Form, message, Popconfirm, Card, Typography, Tooltip, Radio, Progress, Alert } from 'antd'
import { PlusOutlined, SearchOutlined, EditOutlined, DeleteOutlined, ClearOutlined, PlusCircleOutlined, BookOutlined, RobotOutlined, ApartmentOutlined } from '@ant-design/icons'
import { knowledgeApi, fileApi, extractionApi } from '../../api'

const { Title } = Typography
const { Option } = Select

export default function KnowledgePoints() {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [filters, setFilters] = useState<any>({})
  const [modalVisible, setModalVisible] = useState(false)
  const [editingPoint, setEditingPoint] = useState<any>(null)
  const [form] = Form.useForm()
  const [annotateVisible, setAnnotateVisible] = useState(false)
  const [textbookFiles, setTextbookFiles] = useState<any[]>([])
  const [selectedTextbookIds, setSelectedTextbookIds] = useState<number[]>([])
  const [annotating, setAnnotating] = useState(false)
  const [annotateMode, setAnnotateMode] = useState<'overwrite' | 'append'>('overwrite')
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([])
  const [shortNameVisible, setShortNameVisible] = useState(false)
  const [shortNameMode, setShortNameMode] = useState<'empty_only' | 'overwrite'>('empty_only')
  const [shortNameRunning, setShortNameRunning] = useState(false)
  const [shortNameProgress, setShortNameProgress] = useState<any>(null)
  const [prerequisiteVisible, setPrerequisiteVisible] = useState(false)
  const [prerequisiteRunning, setPrerequisiteRunning] = useState(false)
  const [prerequisiteProgress, setPrerequisiteProgress] = useState<any>(null)
  const [prerequisiteOptions, setPrerequisiteOptions] = useState<any[]>([])
  const [prerequisiteLoading, setPrerequisiteLoading] = useState(false)

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await knowledgeApi.listPoints({ page, page_size: pageSize, ...filters })
      setData(res.data.items || [])
      setTotal(res.data.total || 0)
    } catch {
      message.error('获取数据失败')
    }
    setLoading(false)
  }

  useEffect(() => { fetchData() }, [page, pageSize, filters])

  const handleCreate = () => {
    setEditingPoint(null)
    form.resetFields()
    setModalVisible(true)
    void loadPrerequisiteOptions()
  }

  const loadPrerequisiteOptions = async (pointId?: string) => {
    setPrerequisiteLoading(true)
    try {
      const requests: Promise<any>[] = [
        knowledgeApi.listPoints({ page: 1, page_size: 500 }),
      ]
      if (pointId) {
        requests.push(knowledgeApi.listRelations({ point_id: pointId }))
      }
      const [pointsResponse, relationsResponse] = await Promise.all(requests)
      setPrerequisiteOptions(
        (pointsResponse.data.items || []).filter(
          (point: any) => point.id !== pointId,
        ),
      )
      return (relationsResponse?.data || [])
        .filter(
          (relation: any) =>
            relation.relation_type === 'prerequisite' &&
            relation.to_point_id === pointId,
        )
        .map((relation: any) => relation.from_point_id)
    } catch {
      message.error('获取依赖知识点列表失败')
      return []
    } finally {
      setPrerequisiteLoading(false)
    }
  }

  const handleEdit = async (record: any) => {
    setEditingPoint(record)
    setModalVisible(true)
    form.setFieldsValue({ ...record, prerequisite_ids: [] })
    const prerequisiteIds = await loadPrerequisiteOptions(record.id)
    form.setFieldValue('prerequisite_ids', prerequisiteIds)
  }

  const handleDelete = async (id: string) => {
    await knowledgeApi.deletePoint(id)
    message.success('已删除')
    fetchData()
  }

  const handleClearAll = async () => {
    try {
      await knowledgeApi.clearAll()
      message.success('已清除所有知识点')
      fetchData()
    } catch {
      message.error('清除失败')
    }
  }

  const fetchTextbooks = async () => {
    try {
      const res = await fileApi.list()
      setTextbookFiles(res.data || [])
    } catch {
      message.error('获取教材文件列表失败')
    }
  }

  const handleOpenAnnotate = () => {
    fetchTextbooks()
    setSelectedTextbookIds([])
    setAnnotateVisible(true)
  }

  const handleAnnotate = async () => {
    if (selectedTextbookIds.length === 0) {
      message.warning('请至少选择一个教材文件')
      return
    }
    setAnnotating(true)
    try {
      const payload: any = { textbook_file_ids: selectedTextbookIds, mode: annotateMode }
      if (selectedRowKeys.length > 0) {
        payload.point_ids = selectedRowKeys
      }
      await knowledgeApi.annotateChapters(payload)
      message.success(`标注任务已启动（${selectedTextbookIds.length}本教材），请稍后刷新查看结果`)
      setAnnotateVisible(false)
      fetchData()
    } catch {
      message.error('标注失败')
    }
    setAnnotating(false)
  }

  const handleGenerateShortNames = async () => {
    setShortNameRunning(true)
    setShortNameProgress(null)
    try {
      const payload: any = { mode: shortNameMode }
      if (selectedRowKeys.length > 0) {
        payload.point_ids = selectedRowKeys
      }
      const res = await knowledgeApi.generateShortNames(payload)
      const taskKey = res.data?.task_key
      if (!taskKey) { message.error('启动失败'); setShortNameRunning(false); return }
      message.info('生成任务已启动')
      // 轮询进度
      const poll = setInterval(async () => {
        try {
          const p = await knowledgeApi.getShortNameProgress(taskKey)
          const prog = p.data
          setShortNameProgress(prog)
          if (prog.status === 'completed' || prog.status === 'failed') {
            clearInterval(poll)
            setShortNameRunning(false)
            if (prog.status === 'completed') {
              message.success(`生成完成，已处理 ${prog.done || 0} 个知识点`)
              setShortNameVisible(false)
              fetchData()
            } else {
              message.error(prog.error || '生成失败')
            }
          }
        } catch {
          clearInterval(poll)
          setShortNameRunning(false)
        }
      }, 1500)
    } catch (e: any) {
      message.error(e.response?.data?.detail || '启动失败')
      setShortNameRunning(false)
    }
  }

  const handleGeneratePrerequisites = async () => {
    setPrerequisiteRunning(true)
    setPrerequisiteProgress(null)
    try {
      const payload =
        selectedRowKeys.length > 0 ? { point_ids: selectedRowKeys } : {}
      const res = await knowledgeApi.generatePrerequisites(payload)
      const taskKey = res.data?.task_key
      if (!taskKey) {
        message.error('启动失败')
        setPrerequisiteRunning(false)
        return
      }
      message.info('前置知识点生成任务已启动')
      const poll = setInterval(async () => {
        try {
          const response = await knowledgeApi.getPrerequisiteProgress(taskKey)
          const progress = response.data
          setPrerequisiteProgress(progress)
          if (progress.status === 'completed' || progress.status === 'failed') {
            clearInterval(poll)
            setPrerequisiteRunning(false)
            if (progress.status === 'completed') {
              message.success(
                `生成完成，处理 ${progress.done || 0} 个知识点，新增 ${progress.created || 0} 条前置关系`,
              )
              setPrerequisiteVisible(false)
              fetchData()
            } else {
              message.error(progress.error || '生成失败')
            }
          }
        } catch {
          clearInterval(poll)
          setPrerequisiteRunning(false)
          message.error('获取生成进度失败')
        }
      }, 1500)
    } catch (e: any) {
      message.error(e.response?.data?.detail || '启动失败')
      setPrerequisiteRunning(false)
    }
  }

  const handleInsertBelow = (record: any) => {
    setEditingPoint(null)
    form.resetFields()
    // 预填充当前行的分类信息，方便用户快速录入
    form.setFieldsValue({
      subject: record.subject,
      domain: record.domain,
      category_1: record.category_1,
      category_2: record.category_2,
      grade: record.grade,
      chapter: record.chapter,
    })
    setModalVisible(true)
    void loadPrerequisiteOptions()
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    const prerequisiteIds = values.prerequisite_ids || []
    delete values.prerequisite_ids
    delete values.prerequisites
    if (editingPoint) {
      await knowledgeApi.updatePoint(editingPoint.id, values)
      await knowledgeApi.updatePointPrerequisites(editingPoint.id, prerequisiteIds)
      message.success('更新成功')
    } else {
      const response = await knowledgeApi.createPoint(values)
      await knowledgeApi.updatePointPrerequisites(response.data.id, prerequisiteIds)
      message.success('创建成功')
    }
    setModalVisible(false)
    fetchData()
  }

  /** 一级/二级分类、知识点：悬停展示全文，白底样式一致 */
  const renderFullTextTooltip = (v?: string) => {
    if (!v) return '-'
    return (
      <Tooltip
        title={v}
        color="white"
        overlayStyle={{ maxWidth: 480 }}
        overlayInnerStyle={{ color: '#333' }}
      >
        <span>{v}</span>
      </Tooltip>
    )
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 130, ellipsis: true, fixed: 'left' as const },
    { title: '学科类别', dataIndex: 'subject', key: 'subject', width: 80 },
    { title: '知识领域', dataIndex: 'domain', key: 'domain', width: 100, render: (v: string) => v ? <Tag color="blue">{v}</Tag> : '-' },
    {
      title: '一级分类', dataIndex: 'category_1', key: 'category_1', width: 110, ellipsis: true,
      render: (v: string) => renderFullTextTooltip(v),
    },
    {
      title: '二级分类', dataIndex: 'category_2', key: 'category_2', width: 110, ellipsis: true,
      render: (v: string) => renderFullTextTooltip(v),
    },
    {
      title: '知识点', dataIndex: 'name', key: 'name', width: 280, ellipsis: true,
      render: (v: string) => renderFullTextTooltip(v),
    },
    {
      title: '知识点名称', dataIndex: 'short_name', key: 'short_name', width: 120, ellipsis: true,
      render: (v: string) => v || '-',
    },
    {
      title: '典型题目', dataIndex: 'typical_questions', key: 'typical_questions', width: 120, ellipsis: true,
      render: (v: string) => v ? <Tooltip title={v}><span>{v.substring(0, 20)}...</span></Tooltip> : '-'
    },
    { title: '年级段', dataIndex: 'grade', key: 'grade', width: 90, render: (v: string) => v || '-' },
    { title: '所属章节', dataIndex: 'chapter', key: 'chapter', width: 140, ellipsis: true },
    {
      title: '依赖知识点', dataIndex: 'prerequisites', key: 'prerequisites', width: 120, ellipsis: true,
      render: (v: string) => v || '-'
    },
    { title: '能力等级', dataIndex: 'cognitive_level', key: 'cognitive_level', width: 80 },
    {
      title: '操作', key: 'action', width: 120, fixed: 'right' as const,
      render: (_: any, record: any) => (
        <Space size="small">
          <Tooltip title="编辑">
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)} />
          </Tooltip>
          <Tooltip title="插入下一行">
            <Button type="link" size="small" icon={<PlusCircleOutlined />} onClick={() => handleInsertBelow(record)} />
          </Tooltip>
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id)}>
            <Tooltip title="删除">
              <Button type="link" size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      )
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>知识点管理</Title>
        <Space>
          <Popconfirm title="确认清除所有知识点？此操作不可恢复！" onConfirm={handleClearAll} okText="确认清除" cancelText="取消" okButtonProps={{ danger: true }}>
            <Button danger icon={<ClearOutlined />}>清除知识点</Button>
          </Popconfirm>
          <Button icon={<RobotOutlined />} onClick={() => { setShortNameVisible(true); setShortNameProgress(null) }}>
            AI生成知识点名称{selectedRowKeys.length > 0 ? `(${selectedRowKeys.length})` : ''}
          </Button>
          <Button
            icon={<ApartmentOutlined />}
            onClick={() => {
              setPrerequisiteVisible(true)
              setPrerequisiteProgress(null)
            }}
          >
            生成前置知识点{selectedRowKeys.length > 0 ? `(${selectedRowKeys.length})` : ''}
          </Button>
          <Button icon={<BookOutlined />} onClick={handleOpenAnnotate}>
            标注章节/年级段{selectedRowKeys.length > 0 ? `(${selectedRowKeys.length})` : ''}
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新建知识点</Button>
        </Space>
      </div>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Input
            placeholder="搜索知识点"
            prefix={<SearchOutlined />}
            allowClear
            style={{ width: 200 }}
            onPressEnter={(e: any) => setFilters({ ...filters, keyword: e.target.value })}
            onChange={(e) => { if (!e.target.value) setFilters({ ...filters, keyword: undefined }) }}
          />
          <Select placeholder="知识领域" allowClear style={{ width: 130 }} onChange={v => setFilters({ ...filters, domain: v })}>
            <Option value="数与代数">数与代数</Option>
            <Option value="图形与几何">图形与几何</Option>
            <Option value="统计与概率">统计与概率</Option>
            <Option value="综合与实践">综合与实践</Option>
          </Select>
          <Select placeholder="年级段" allowClear style={{ width: 120 }} onChange={v => setFilters({ ...filters, grade: v })}>
            <Option value="七年级">七年级</Option>
            <Option value="八年级">八年级</Option>
            <Option value="九年级">九年级</Option>
          </Select>
          <Select placeholder="能力等级" allowClear style={{ width: 110 }} onChange={v => setFilters({ ...filters, cognitive_level: v })}>
            <Option value="了解">了解</Option>
            <Option value="理解">理解</Option>
            <Option value="掌握">掌握</Option>
            <Option value="运用">运用</Option>
          </Select>
          <Select placeholder="状态" allowClear style={{ width: 100 }} onChange={v => setFilters({ ...filters, status: v })}>
            <Option value="draft">草稿</Option>
            <Option value="reviewed">已审核</Option>
            <Option value="published">已发布</Option>
          </Select>
        </Space>
      </Card>

      <Table
        columns={columns}
        dataSource={data}
        rowKey="id"
        loading={loading}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys as string[]),
        }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条${selectedRowKeys.length > 0 ? `，已选 ${selectedRowKeys.length} 条` : ''}`,
          onChange: (p, ps) => { setPage(p); setPageSize(ps) },
        }}
        size="small"
        scroll={{ x: 1600 }}
      />

      <Modal
        title="标注章节/年级段"
        open={annotateVisible}
        onOk={handleAnnotate}
        onCancel={() => setAnnotateVisible(false)}
        okText="开始标注"
        confirmLoading={annotating}
        destroyOnClose
      >
        <p style={{ marginBottom: 16, color: '#666' }}>
          选择教材文件后，系统将自动分析教材内容，为{selectedRowKeys.length > 0 ? `已选的 ${selectedRowKeys.length} 个` : '全部'}知识点标注对应的年级段和所属章节。
        </p>
        <Select
          mode="multiple"
          placeholder="请选择教材文件（可多选）"
          style={{ width: '100%', marginBottom: 16 }}
          value={selectedTextbookIds}
          onChange={(v) => setSelectedTextbookIds(v)}
        >
          {textbookFiles.map((f: any) => (
            <Option key={f.id} value={f.id}>{f.original_name || f.filename}</Option>
          ))}
        </Select>
        <div style={{ marginBottom: 8, fontWeight: 500 }}>标注模式：</div>
        <Radio.Group value={annotateMode} onChange={(e) => setAnnotateMode(e.target.value)}>
          <Radio value="overwrite">覆盖（清除已有标注，重新标注）</Radio>
          <Radio value="append">追加（保留已有标注，补充新标注）</Radio>
        </Radio.Group>
      </Modal>

      <Modal
        title="AI生成知识点名称"
        open={shortNameVisible}
        onOk={handleGenerateShortNames}
        onCancel={() => { if (!shortNameRunning) setShortNameVisible(false) }}
        okText={shortNameRunning ? '生成中...' : '开始生成'}
        confirmLoading={shortNameRunning}
        closable={!shortNameRunning}
        maskClosable={!shortNameRunning}
        destroyOnClose
      >
        <p style={{ marginBottom: 16, color: '#666' }}>
          系统将调用AI大模型，自动将{selectedRowKeys.length > 0 ? `已选的 ${selectedRowKeys.length} 个` : '全部'}知识点的描述内容概括为2-8字的简短名称，填入「知识点名称」列。
        </p>
        <div style={{ marginBottom: 16 }}>
          <div style={{ marginBottom: 8, fontWeight: 500 }}>生成范围：</div>
          <Radio.Group value={shortNameMode} onChange={(e) => setShortNameMode(e.target.value)}>
            <Radio value="empty_only">仅生成空白项（推荐，保留已有名称）</Radio>
            <Radio value="overwrite">全部重新生成（覆盖已有名称）</Radio>
          </Radio.Group>
        </div>
        {shortNameProgress && (
          <div style={{ marginTop: 16 }}>
            <Progress
              percent={shortNameProgress.progress || 0}
              status={shortNameProgress.status === 'failed' ? 'exception' : shortNameProgress.status === 'completed' ? 'success' : 'active'}
            />
            <p style={{ color: '#999', fontSize: 12, marginTop: 4 }}>
              已处理 {shortNameProgress.done || 0} / {shortNameProgress.total || 0} 个知识点
            </p>
            {shortNameProgress.error && (
              <p style={{ color: '#ff4d4f', fontSize: 12 }}>{shortNameProgress.error}</p>
            )}
          </div>
        )}
      </Modal>

      <Modal
        title="AI生成前置知识点"
        open={prerequisiteVisible}
        onOk={handleGeneratePrerequisites}
        onCancel={() => {
          if (!prerequisiteRunning) setPrerequisiteVisible(false)
        }}
        okText={prerequisiteRunning ? '生成中...' : '开始生成'}
        confirmLoading={prerequisiteRunning}
        closable={!prerequisiteRunning}
        maskClosable={!prerequisiteRunning}
        destroyOnClose
      >
        <p style={{ marginBottom: 12, color: '#666', lineHeight: 1.7 }}>
          系统将调用 AI 大模型，为
          {selectedRowKeys.length > 0
            ? `已选的 ${selectedRowKeys.length} 个`
            : `全部 ${total} 个`}
          知识点分析必要的前置知识点，并写入关系管理与“依赖知识点”列。
        </p>
        <Alert
          type="info"
          showIcon
          message="现有人工关系会保留"
          description="本功能只新增尚不存在的前置依赖关系，不会删除或覆盖已有关系；每个知识点最多生成 3 个前置知识点。"
        />
        {prerequisiteProgress && (
          <div style={{ marginTop: 18 }}>
            <Progress
              percent={prerequisiteProgress.progress || 0}
              status={
                prerequisiteProgress.status === 'failed'
                  ? 'exception'
                  : prerequisiteProgress.status === 'completed'
                    ? 'success'
                    : 'active'
              }
            />
            <p style={{ color: '#999', fontSize: 12, marginTop: 4 }}>
              已处理 {prerequisiteProgress.done || 0} / {prerequisiteProgress.total || 0}
              个知识点 · 已新增 {prerequisiteProgress.created || 0} 条关系
            </p>
            {prerequisiteProgress.error && (
              <p style={{ color: '#ff4d4f', fontSize: 12 }}>
                {prerequisiteProgress.error}
              </p>
            )}
          </div>
        )}
      </Modal>

      <Modal
        title={editingPoint ? '编辑知识点' : '新建知识点'}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        width={720}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          {!editingPoint && (
            <Form.Item name="id" label="知识点ID" rules={[{ required: true, message: '请输入ID' }]}>
              <Input placeholder="如: MATH-01-001" />
            </Form.Item>
          )}
          <Form.Item name="name" label="知识点" rules={[{ required: true, message: '请输入知识点内容' }]}>
            <Input.TextArea rows={2} placeholder="知识点描述内容" />
          </Form.Item>
          <Form.Item name="short_name" label="知识点名称">
            <Input placeholder="简短名称，如：有理数、一元二次方程" />
          </Form.Item>
          <Space style={{ width: '100%' }} size={16}>
            <Form.Item name="subject" label="学科类别" style={{ width: 120 }}>
              <Input placeholder="如：数学" />
            </Form.Item>
            <Form.Item name="domain" label="知识领域" style={{ width: 150 }}>
              <Select placeholder="选择领域">
                <Option value="数与代数">数与代数</Option>
                <Option value="图形与几何">图形与几何</Option>
                <Option value="统计与概率">统计与概率</Option>
                <Option value="综合与实践">综合与实践</Option>
              </Select>
            </Form.Item>
            <Form.Item name="cognitive_level" label="能力等级" style={{ width: 120 }}>
              <Select placeholder="能力等级">
                <Option value="了解">了解</Option>
                <Option value="理解">理解</Option>
                <Option value="掌握">掌握</Option>
                <Option value="运用">运用</Option>
              </Select>
            </Form.Item>
          </Space>
          <Space style={{ width: '100%' }} size={16}>
            <Form.Item name="category_1" label="一级分类" style={{ width: 200 }}>
              <Input placeholder="如：数与式" />
            </Form.Item>
            <Form.Item name="category_2" label="二级分类" style={{ width: 200 }}>
              <Input placeholder="如：有理数" />
            </Form.Item>
          </Space>
          <Space style={{ width: '100%' }} size={16}>
            <Form.Item name="grade" label="年级段" style={{ width: 200 }}>
              <Select placeholder="年级段">
                <Option value="七年级上">七年级上</Option>
                <Option value="七年级下">七年级下</Option>
                <Option value="八年级上">八年级上</Option>
                <Option value="八年级下">八年级下</Option>
                <Option value="九年级上">九年级上</Option>
                <Option value="九年级下">九年级下</Option>
              </Select>
            </Form.Item>
            <Form.Item name="chapter" label="所属章节" style={{ width: 250 }}>
              <Input placeholder="如：第一章 有理数" />
            </Form.Item>
          </Space>
          <Form.Item name="typical_questions" label="典型题目">
            <Input.TextArea rows={2} placeholder="典型题目描述" />
          </Form.Item>
          <Form.Item name="prerequisite_ids" label="依赖知识点（前置知识点）">
            <Select
              mode="multiple"
              allowClear
              showSearch
              loading={prerequisiteLoading}
              optionFilterProp="label"
              placeholder="请选择该知识点需要先掌握的知识点"
              options={prerequisiteOptions.map((point) => ({
                value: point.id,
                label: `${point.short_name || point.name}（${point.id}）`,
              }))}
            />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select placeholder="状态">
              <Option value="draft">草稿</Option>
              <Option value="reviewed">已审核</Option>
              <Option value="published">已发布</Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
