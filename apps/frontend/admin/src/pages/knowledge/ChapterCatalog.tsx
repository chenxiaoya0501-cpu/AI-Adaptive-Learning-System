import { useEffect, useMemo, useState, useRef, useCallback } from 'react'
import {
  Card, Typography, Table, Button, Space, Select, Tag, Input, message,
  Popconfirm, Modal, Form, Empty, List, Drawer, Tooltip, Progress, Popover
} from 'antd'
import {
  ReloadOutlined, EditOutlined, DeleteOutlined, ArrowUpOutlined, ArrowDownOutlined,
  EyeOutlined, FileTextOutlined, FilePdfOutlined
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { chapterApi, fileApi } from '../../api'

const { Title, Text } = Typography
const { Option } = Select

type ChapterNode = {
  id: number
  title: string
  level: string
  sort_order: number
  content_summary?: string
  status: string
  kp_count?: number
  grade?: string
  semester?: string
  children?: ChapterNode[]
}

type TocTree = {
  uploaded_file_id: number
  file_name?: string
  grade?: string
  semester?: string
  chapters: ChapterNode[]
}

export default function ChapterCatalog() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [trees, setTrees] = useState<TocTree[]>([])
  const [selectedFileId, setSelectedFileId] = useState<number | undefined>()
  const [editVisible, setEditVisible] = useState(false)
  const [editing, setEditing] = useState<ChapterNode | null>(null)
  const [form] = Form.useForm()
  const [kpDrawerVisible, setKpDrawerVisible] = useState(false)
  const [kpLoading, setKpLoading] = useState(false)
  const [relatedKps, setRelatedKps] = useState<any[]>([])
  const [viewingChapter, setViewingChapter] = useState<ChapterNode | null>(null)
  const [extracting, setExtracting] = useState(false)
  const [summaryTaskId, setSummaryTaskId] = useState<number | null>(null)
  const [summaryProgress, setSummaryProgress] = useState(0)
  const [summaryDetail, setSummaryDetail] = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 文件选择弹窗
  const [filePickerVisible, setFilePickerVisible] = useState(false)
  const [uploadedFiles, setUploadedFiles] = useState<any[]>([])
  const [filesLoading, setFilesLoading] = useState(false)
  const [pickedFileId, setPickedFileId] = useState<number | null>(null)

  const gradeOrder = (grade?: string) => {
    const g = (grade || '').trim()
    if (g === '7' || g.includes('七')) return 7
    if (g === '8' || g.includes('八')) return 8
    if (g === '9' || g.includes('九')) return 9
    return 99
  }
  const semesterOrder = (semester?: string) => {
    const s = (semester || '').trim()
    if (s.startsWith('上') || s === '1') return 1
    if (s.startsWith('下') || s === '2') return 2
    return 9
  }

  const fetchTrees = async () => {
    setLoading(true)
    try {
      const res = await chapterApi.listTrees()
      const list: TocTree[] = res.data || []
      setTrees(list)
      // 默认选中排序后的第一本有目录教材；若当前选择仍在列表中则保留
      setSelectedFileId(prev => {
        if (prev && list.some(t => t.uploaded_file_id === prev)) return prev
        const sorted = [...list].sort((a, b) => {
          const dg = gradeOrder(a.grade) - gradeOrder(b.grade)
          if (dg !== 0) return dg
          return semesterOrder(a.semester) - semesterOrder(b.semester)
        })
        const first = sorted.find(t => (t.chapters?.length || 0) > 0) || sorted[0]
        return first?.uploaded_file_id
      })
    } catch {
      message.error('获取章节目录失败')
    }
    setLoading(false)
  }

  useEffect(() => { fetchTrees() }, [])

  const bookOverview = useMemo(() => {
    return trees.map(t => ({
      id: t.uploaded_file_id,
      name: t.file_name || `教材#${t.uploaded_file_id}`,
      grade: t.grade,
      semester: t.semester,
      chapterCount: t.chapters?.length || 0,
      sectionCount: (t.chapters || []).reduce((n, ch) => n + (ch.children?.length || 0), 0),
    })).sort((a, b) => {
      const dg = gradeOrder(a.grade) - gradeOrder(b.grade)
      if (dg !== 0) return dg
      const ds = semesterOrder(a.semester) - semesterOrder(b.semester)
      if (ds !== 0) return ds
      return a.name.localeCompare(b.name, 'zh')
    })
  }, [trees])

  const currentTree = trees.find(t => t.uploaded_file_id === selectedFileId)

  const flatRows = useMemo(() => {
    if (!currentTree) return []
    const rows: Array<ChapterNode & { key: number; indent: number }> = []
    for (const ch of currentTree.chapters || []) {
      rows.push({ ...ch, key: ch.id, indent: 0 })
      for (const sec of ch.children || []) {
        rows.push({ ...sec, key: sec.id, indent: 1 })
      }
    }
    return rows
  }, [currentTree])

  const handleEdit = (record: ChapterNode) => {
    setEditing(record)
    form.setFieldsValue({
      title: record.title,
      status: record.status || 'draft',
    })
    setEditVisible(true)
  }

  const handleSaveEdit = async () => {
    if (!editing) return
    const values = await form.validateFields()
    try {
      await chapterApi.updateChapter(editing.id, {
        title: values.title,
        status: values.status,
      })
      message.success('已保存')
      setEditVisible(false)
      fetchTrees()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '保存失败')
    }
  }

  const handleDelete = async (id: number) => {
    try {
      await chapterApi.deleteChapter(id)
      message.success('已删除')
      fetchTrees()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '删除失败')
    }
  }

  const handleClearAll = async () => {
    try {
      const res = await chapterApi.clearAll()
      message.success(res.data?.message || '已清除全部章节目录')
      setSelectedFileId(undefined)
      fetchTrees()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '清除失败')
    }
  }

  const handleViewRelatedKps = async (record: ChapterNode) => {
    setViewingChapter(record)
    setKpDrawerVisible(true)
    setKpLoading(true)
    setRelatedKps([])
    try {
      const res = await chapterApi.listRelatedKnowledgePoints(record.id)
      setRelatedKps(res.data || [])
    } catch (e: any) {
      message.error(e.response?.data?.detail || '获取关联知识点失败')
    }
    setKpLoading(false)
  }

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const startPolling = useCallback((taskId: number) => {
    stopPolling()
    setSummaryTaskId(taskId)
    setExtracting(true)
    setSummaryProgress(0)
    setSummaryDetail('任务已启动…')

    pollRef.current = setInterval(async () => {
      try {
        const res = await chapterApi.getSummaryTaskStatus(taskId)
        const data = res.data
        setSummaryProgress(data.progress || 0)
        setSummaryDetail(data.result_summary?.detail || '')

        if (data.status === 'completed') {
          stopPolling()
          setExtracting(false)
          setSummaryProgress(100)
          setSummaryDetail(data.result_summary?.detail || '提取完成')
          message.success(data.result_summary?.detail || '内容概述提取完成')
          fetchTrees()
        } else if (data.status === 'failed') {
          stopPolling()
          setExtracting(false)
          setSummaryProgress(0)
          setSummaryDetail('')
          message.error(data.error_message || '提取失败')
        }
      } catch {
        // 网络错误不中断轮询，等待恢复
      }
    }, 3000)
  }, [stopPolling])

  // 组件卸载时清理轮询（但不会终止后台任务）
  useEffect(() => {
    return () => stopPolling()
  }, [stopPolling])

  // 当选中教材变化时，检查是否有正在进行的提取任务（用于页面切换回来后恢复进度条）
  useEffect(() => {
    if (!selectedFileId) return
    let cancelled = false
    const checkActive = async () => {
      try {
        const res = await chapterApi.getActiveSummaryTask(selectedFileId)
        if (cancelled) return
        if (res.data?.active && res.data?.task_id) {
          startPolling(res.data.task_id)
          setSummaryProgress(res.data.progress || 0)
          setSummaryDetail(res.data.result_summary?.detail || '任务进行中…')
        } else {
          // 没有活跃任务时重置状态
          stopPolling()
          setExtracting(false)
          setSummaryProgress(0)
          setSummaryDetail('')
        }
      } catch {
        // ignore
      }
    }
    checkActive()
    return () => { cancelled = true }
  }, [selectedFileId, startPolling, stopPolling])

  const openFilePicker = async () => {
    setFilePickerVisible(true)
    setFilesLoading(true)
    setPickedFileId(null)
    try {
      const res = await fileApi.list('textbook')
      const files = (res.data || []).filter((f: any) => f.file_type === 'textbook')
      setUploadedFiles(files)
      // 默认选中当前教材对应的文件
      if (selectedFileId && files.some((f: any) => f.id === selectedFileId)) {
        setPickedFileId(selectedFileId)
      }
    } catch {
      message.error('获取文件列表失败')
      setUploadedFiles([])
    }
    setFilesLoading(false)
  }

  const handleExtractSummaries = async () => {
    if (!pickedFileId) {
      message.warning('请选择一个电子课本文件')
      return
    }
    setFilePickerVisible(false)
    setExtracting(true)
    try {
      const res = await chapterApi.extractSummaries(pickedFileId)
      const taskId = res.data?.task_id
      if (taskId) {
        startPolling(taskId)
      } else {
        setExtracting(false)
      }
    } catch (e: any) {
      message.error(e.response?.data?.detail || '提取失败，请重试')
      setExtracting(false)
    }
  }

  const handleMove = async (record: ChapterNode & { indent: number }, direction: 'up' | 'down') => {
    if (!currentTree) return
    const siblings: ChapterNode[] = record.level === 'chapter'
      ? currentTree.chapters
      : (currentTree.chapters.find(c => (c.children || []).some(s => s.id === record.id))?.children || [])

    const idx = siblings.findIndex(s => s.id === record.id)
    if (idx < 0) return
    const swapIdx = direction === 'up' ? idx - 1 : idx + 1
    if (swapIdx < 0 || swapIdx >= siblings.length) return

    const a = siblings[idx]
    const b = siblings[swapIdx]
    try {
      await chapterApi.reorder([
        { id: a.id, sort_order: b.sort_order },
        { id: b.id, sort_order: a.sort_order },
      ])
      fetchTrees()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '排序失败')
    }
  }

  const columns = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      render: (v: string, record: any) => (
        <span style={{ paddingLeft: record.indent * 24 }}>
          <Tag color={record.level === 'chapter' ? 'blue' : 'default'}>
            {record.level === 'chapter' ? '章' : '节'}
          </Tag>
          {v}
        </span>
      ),
    },
    {
      title: '内容概述',
      dataIndex: 'content_summary',
      key: 'content_summary',
      width: 280,
      ellipsis: true,
      render: (v: string, record: any) => {
        if (record.level === 'chapter') return <Text type="secondary">-</Text>
        if (!v) return <Text type="secondary">未提取</Text>
        return (
          <Popover
            content={
              <div style={{ maxWidth: 400, fontSize: 13, lineHeight: '1.6' }}>
                {v}
              </div>
            }
            title="节内容概述"
            trigger="hover"
            placement="left"
          >
            <span
              style={{
                color: '#1677ff',
                cursor: 'pointer',
                fontSize: 13,
              }}
            >
              {v}
            </span>
          </Popover>
        )
      },
    },
    {
      title: '关联知识点数',
      dataIndex: 'kp_count',
      key: 'kp_count',
      width: 120,
      render: (v: number, record: any) =>
        record.level === 'chapter' ? (v ?? 0) : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (v: string) =>
        v === 'published' ? <Tag color="success">已发布</Tag> : <Tag>草稿</Tag>,
    },
    {
      title: '排序',
      dataIndex: 'sort_order',
      key: 'sort_order',
      width: 70,
    },
    {
      title: '操作',
      key: 'action',
      width: 230,
      align: 'left' as const,
      render: (_: any, record: any) => (
        <Space size="small">
          {/* 章/节按钮占位一致，避免节行缺少「查看」导致后续图标错位 */}
          {record.level === 'chapter' ? (
            <Tooltip title="查看关联知识点">
              <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleViewRelatedKps(record)} />
            </Tooltip>
          ) : (
            <Button type="link" size="small" icon={<EyeOutlined />} disabled style={{ visibility: 'hidden' }} />
          )}
          <Button type="link" size="small" icon={<ArrowUpOutlined />} onClick={() => handleMove(record, 'up')} />
          <Button type="link" size="small" icon={<ArrowDownOutlined />} onClick={() => handleMove(record, 'down')} />
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)} />
          <Popconfirm
            title={record.level === 'chapter' ? '删除该章及其下所有节？' : '确认删除该节？'}
            onConfirm={() => handleDelete(record.id)}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>章节目录</Title>
        <Space>
          <Popconfirm
            title="确认清除全部章节目录？"
            description="将删除所有教材的章/节目录，此操作不可恢复。"
            onConfirm={handleClearAll}
            okText="确认清除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button danger icon={<DeleteOutlined />}>一键清除目录</Button>
          </Popconfirm>
          <Button icon={<ReloadOutlined />} onClick={fetchTrees}>刷新</Button>
          <Button type="primary" onClick={() => navigate('/knowledge/extraction')}>
            去知识抽取
          </Button>
        </Space>
      </div>

      <Card size="small" style={{ marginBottom: 16, background: '#f6ffed', border: '1px solid #b7eb8f' }}>
        <Text>
          多本课本可一次抽取：各本目录分别保存（互不影响）。对同一本重复抽取会覆盖该本旧目录。
          下方先看全部教材概览，再点某一本查看章/节详情。
        </Text>
      </Card>

      <Card size="small" style={{ marginBottom: 16 }} title={`已抽取教材（共 ${bookOverview.length} 本）`}>
        {bookOverview.length === 0 ? (
          <Empty description="暂无章节目录，请先到「知识抽取」运行「章节目录抽取」">
            <Button type="primary" onClick={() => navigate('/knowledge/extraction')}>
              去创建抽取任务
            </Button>
          </Empty>
        ) : (
          <List
            loading={loading}
            grid={{ gutter: 12, column: 2 }}
            dataSource={bookOverview}
            renderItem={(item) => (
              <List.Item>
                <Card
                  size="small"
                  hoverable
                  onClick={() => setSelectedFileId(item.id)}
                  style={{
                    borderColor: selectedFileId === item.id ? '#1677ff' : undefined,
                    background: selectedFileId === item.id ? '#e6f4ff' : undefined,
                  }}
                >
                  <div style={{ fontWeight: 500, marginBottom: 6 }}>{item.name}</div>
                  <Space size={4} wrap>
                    {item.grade && <Tag>{item.grade}</Tag>}
                    {item.semester && <Tag>{item.semester}册</Tag>}
                    <Tag color={item.chapterCount > 0 ? 'blue' : 'default'}>
                      {item.chapterCount}章 / {item.sectionCount}节
                    </Tag>
                  </Space>
                </Card>
              </List.Item>
            )}
          />
        )}
      </Card>

      {currentTree && (
        <Card
          title={
            <Space wrap>
              <span>{currentTree.file_name || `教材#${currentTree.uploaded_file_id}`}</span>
              {currentTree.grade && <Tag>{currentTree.grade}</Tag>}
              {currentTree.semester && <Tag>{currentTree.semester}</Tag>}
              <Text type="secondary">{currentTree.chapters?.length || 0} 章</Text>
            </Space>
          }
          extra={
            <Space direction="vertical" size={4} align="end">
              <Button
                icon={<FileTextOutlined />}
                loading={extracting}
                onClick={openFilePicker}
              >
                提取节内容概述
              </Button>
              {extracting && (
                <div style={{ width: 220 }}>
                  <Progress percent={summaryProgress} size="small" status="active" />
                  <Text type="secondary" style={{ fontSize: 12 }}>{summaryDetail}</Text>
                </div>
              )}
            </Space>
          }
        >
          {flatRows.length === 0 ? (
            <Empty description="该教材尚未识别到章节（可能是扫描版PDF无文本）" />
          ) : (
            <Table
              columns={columns}
              dataSource={flatRows}
              rowKey="key"
              loading={loading}
              size="small"
              pagination={false}
            />
          )}
        </Card>
      )}

      <Modal
        title={`编辑${editing?.level === 'chapter' ? '章' : '节'}`}
        open={editVisible}
        onOk={handleSaveEdit}
        onCancel={() => setEditVisible(false)}
        okText="保存"
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select>
              <Option value="draft">草稿</Option>
              <Option value="published">已发布</Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="选择电子课本文件"
        open={filePickerVisible}
        onCancel={() => setFilePickerVisible(false)}
        onOk={handleExtractSummaries}
        okText="开始提取"
        cancelText="取消"
        okButtonProps={{ disabled: !pickedFileId }}
        width={600}
        destroyOnClose
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          请选择用于提取节内容概述的教材PDF文件
        </Text>
        {filesLoading ? (
          <div style={{ textAlign: 'center', padding: 32 }}><Progress type="circle" percent={0} size={40} /></div>
        ) : uploadedFiles.length === 0 ? (
          <Empty description="暂无已上传的教材文件，请先到「资料上传」页面上传" />
        ) : (
          <div style={{ maxHeight: 360, overflow: 'auto' }}>
            {uploadedFiles.map((f: any) => (
              <Card
                key={f.id}
                size="small"
                hoverable
                onClick={() => setPickedFileId(f.id)}
                style={{
                  marginBottom: 8,
                  cursor: 'pointer',
                  borderColor: pickedFileId === f.id ? '#1677ff' : undefined,
                  background: pickedFileId === f.id ? '#e6f4ff' : undefined,
                }}
              >
                <Space>
                  <FilePdfOutlined style={{ fontSize: 18, color: '#cf1322' }} />
                  <div>
                    <div style={{ fontWeight: 500 }}>{f.original_name || f.filename}</div>
                    <Space size={4}>
                      {f.grade && <Tag>{f.grade}</Tag>}
                      {f.semester && <Tag>{f.semester}</Tag>}
                      {f.file_size && <Text type="secondary" style={{ fontSize: 12 }}>{(f.file_size / 1024 / 1024).toFixed(1)} MB</Text>}
                      <Tag color={f.status === 'parsed' ? 'green' : 'default'}>{f.status === 'parsed' ? '已解析' : f.status}</Tag>
                    </Space>
                  </div>
                </Space>
              </Card>
            ))}
          </div>
        )}
      </Modal>

      <Drawer
        title={`关联知识点 · ${viewingChapter?.title || ''}`}
        open={kpDrawerVisible}
        onClose={() => setKpDrawerVisible(false)}
        width={720}
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          按知识点「所属章节」与当前章标题匹配（忽略全角/半角空格差异），共 {relatedKps.length} 条
        </Text>
        <Table
          size="small"
          loading={kpLoading}
          rowKey="id"
          dataSource={relatedKps}
          pagination={{ pageSize: 20, showTotal: t => `共 ${t} 条` }}
          locale={{ emptyText: '暂无匹配的知识点（需知识点已标注章节字段）' }}
          columns={[
            { title: 'ID', dataIndex: 'id', key: 'id', width: 130 },
            { title: '名称', dataIndex: 'name', key: 'name', ellipsis: true },
            { title: '所属章节', dataIndex: 'chapter', key: 'chapter', width: 160, ellipsis: true },
            { title: '年级', dataIndex: 'grade', key: 'grade', width: 80 },
            {
              title: '状态', dataIndex: 'status', key: 'status', width: 80,
              render: (v: string) => v || '-',
            },
          ]}
        />
      </Drawer>
    </div>
  )
}
