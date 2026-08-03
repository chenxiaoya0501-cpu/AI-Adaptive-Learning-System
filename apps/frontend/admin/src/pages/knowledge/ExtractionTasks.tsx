import { useEffect, useRef, useState } from 'react'
import { Table, Button, Space, Tag, Select, message, Card, Typography, Modal, Progress, Popconfirm, Tooltip } from 'antd'
import { ReloadOutlined, RocketOutlined, DeleteOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { extractionApi, fileApi } from '../../api'
import { formatDateTime } from '../../utils/datetime'

const { Title } = Typography
const { Option } = Select

const ACTIVE_STATUSES = new Set(['pending', 'running'])

export default function ExtractionTasks() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState<any[]>([])
  const [files, setFiles] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [taskType, setTaskType] = useState<string>('chapter_toc_extraction')
  const [selectedFileIds, setSelectedFileIds] = useState<number[]>([])
  const prevActiveIdsRef = useRef<Set<number>>(new Set())

  const fetchTasks = async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const res = await extractionApi.listTasks()
      const list = res.data || []
      setTasks(list)

      // 有任务刚从进行中变为完成/失败时提示一次
      const activeIds = new Set<number>(
        list
          .filter((t: any) => ACTIVE_STATUSES.has(t.status))
          .map((t: any) => Number(t.id))
      )
      const prev = prevActiveIdsRef.current
      if (prev.size > 0) {
        for (const id of prev) {
          if (!activeIds.has(id)) {
            const done = list.find((t: any) => t.id === id)
            if (done?.status === 'completed') {
              message.success(`任务 #${id} 已完成`)
            } else if (done?.status === 'failed') {
              message.error(`任务 #${id} 失败：${done.error_message || '未知错误'}`)
            }
          }
        }
      }
      prevActiveIdsRef.current = activeIds
    } catch {
      if (!silent) message.error('获取任务列表失败')
    }
    if (!silent) setLoading(false)
  }

  const fetchFiles = async () => {
    try {
      const res = await fileApi.list()
      setFiles(res.data || [])
    } catch {}
  }

  useEffect(() => { fetchTasks(); fetchFiles() }, [])

  // 存在等待中/运行中任务时自动轮询进度（所有任务类型）
  const hasActiveTask = tasks.some(t => ACTIVE_STATUSES.has(t.status))
  useEffect(() => {
    if (!hasActiveTask) return
    const timer = window.setInterval(() => {
      fetchTasks(true)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [hasActiveTask])

  // 章节目录：从资料上传的全部 PDF 中选（不强制 file_type=textbook，避免课本被误标课标后选不到）
  const chapterSourceFiles = files

  const handleDeleteTask = async (id: number) => {
    try {
      await extractionApi.deleteTask(id)
      message.success('已删除任务记录')
      fetchTasks()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '删除失败')
    }
  }

  const handleStartTask = async () => {
    if (taskType === 'knowledge_extraction' && selectedFileIds.length === 0) {
      message.warning('请选择源文件')
      return
    }
    if (taskType === 'chapter_toc_extraction' && selectedFileIds.length === 0) {
      message.warning('请选择资料上传中的PDF文件')
      return
    }
    try {
      await extractionApi.start({
        task_type: taskType,
        source_file_ids:
          taskType === 'knowledge_extraction' || taskType === 'chapter_toc_extraction'
            ? selectedFileIds
            : undefined,
      })
      message.success(
        taskType === 'chapter_toc_extraction'
          ? '章节目录抽取已启动，完成后可在「章节目录」查看'
          : '任务已启动'
      )
      setModalVisible(false)
      setSelectedFileIds([])
      fetchTasks()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '启动失败')
    }
  }

  const statusLabels: Record<string, { label: string; color: string }> = {
    pending: { label: '等待中', color: 'default' },
    running: { label: '运行中', color: 'processing' },
    completed: { label: '已完成', color: 'success' },
    failed: { label: '失败', color: 'error' },
  }

  const taskTypeLabels: Record<string, string> = {
    knowledge_extraction: '知识点抽取',
    relation_extraction: '关系抽取',
    annotation: '年级段/章节标注',
    chapter_toc_extraction: '章节目录抽取',
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    {
      title: '任务类型', dataIndex: 'task_type', key: 'task_type', width: 140,
      render: (v: string) => taskTypeLabels[v] || v
    },
    {
      title: '源文件', dataIndex: 'source_file_names', key: 'source_file_names', width: 260, ellipsis: true,
      render: (v: string, record: any) => {
        if (v) {
          return <Tooltip title={v}><span>{v}</span></Tooltip>
        }
        if (record.task_type === 'relation_extraction') {
          return <span style={{ color: '#999' }}>全部知识点</span>
        }
        return record.source_file_ids || '-'
      }
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (v: string) => {
        const info = statusLabels[v] || { label: v, color: 'default' }
        return <Tag color={info.color}>{info.label}</Tag>
      }
    },
    {
      title: '进度', dataIndex: 'progress', key: 'progress', width: 150,
      render: (v: number, record: any) => (
        <Progress
          percent={v}
          size="small"
          status={record.status === 'failed' ? 'exception' : record.status === 'completed' ? 'success' : 'active'}
        />
      )
    },
    {
      title: '结果', dataIndex: 'result_summary', key: 'result_summary', width: 260,
      render: (v: any, record: any) => {
        if (!v) return '-'
        if (record.status === 'running' || record.status === 'pending') {
          if (v.detail) {
            return <span style={{ color: '#1677ff' }}>{v.detail}</span>
          }
          if (v.stage === 'ocr_cache') {
            return <span style={{ color: '#1677ff' }}>命中OCR缓存…</span>
          }
          if (v.stage === 'parsing_pdf' || v.stage === 'ocr' || v.stage === 'ocr_init') {
            return <span style={{ color: '#1677ff' }}>正在解析PDF…</span>
          }
        }
        if (record.task_type === 'chapter_toc_extraction') {
          const fileN = v.files ?? (Array.isArray(v.per_file) ? v.per_file.length : 0)
          return (
            <Space size={4} wrap>
              <span>{fileN}本 · {v.chapters ?? 0}章 / {v.sections ?? 0}节</span>
              {record.status === 'completed' && (
                <Button type="link" size="small" onClick={() => navigate('/knowledge/chapters')}>
                  查看目录
                </Button>
              )}
            </Space>
          )
        }
        return JSON.stringify(v)
      }
    },

    {
      title: '错误信息', dataIndex: 'error_message', key: 'error_message', width: 160,
      ellipsis: true,
      render: (v: string) => v ? <span style={{ color: '#ff4d4f' }}>{v}</span> : '-'
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170,
      render: (v: string) => formatDateTime(v),
    },
    {
      title: '操作', key: 'action', width: 80, fixed: 'right' as const,
      render: (_: any, record: any) => {
        const running = record.status === 'pending' || record.status === 'running'
        return (
          <Popconfirm
            title="确认删除该任务记录？"
            description="仅删除任务记录，不会回滚已抽取的知识点/目录等结果。"
            onConfirm={() => handleDeleteTask(record.id)}
            disabled={running}
          >
            <Button
              type="link"
              size="small"
              danger
              icon={<DeleteOutlined />}
              disabled={running}
              title={running ? '进行中的任务不可删除' : '删除'}
            />
          </Popconfirm>
        )
      }
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>知识抽取任务</Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void fetchTasks()}>刷新</Button>
          <Button type="primary" icon={<RocketOutlined />} onClick={() => setModalVisible(true)}>新建任务</Button>
        </Space>
      </div>

      <Card size="small" style={{ marginBottom: 16, background: '#f6ffed', border: '1px solid #b7eb8f' }}>
        <p><strong>使用说明：</strong></p>
        <ol style={{ margin: 0, paddingLeft: 20 }}>
          <li>先在「系统配置 → 运行设置」中配置大模型（章节目录抽取不依赖大模型）</li>
          <li>在「资料上传」中上传课程标准PDF或教材PDF</li>
          <li>「章节目录抽取」：选择教材PDF，抽取章/节目录，结果在「章节目录」查看编辑</li>
          <li>「知识点抽取」：选择课标/教材PDF，抽取知识点</li>
          <li>「关系抽取」：分析已有知识点之间的依赖关系</li>
        </ol>
      </Card>

      <Table
        columns={columns}
        dataSource={tasks}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={{ pageSize: 20 }}
        scroll={{ x: 1200 }}
      />

      <Modal
        title="新建抽取任务"
        open={modalVisible}
        onOk={handleStartTask}
        onCancel={() => { setModalVisible(false); setSelectedFileIds([]) }}
        okText="启动"
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
          <div>
            <label style={{ display: 'block', marginBottom: 8 }}>任务类型：</label>
            <Select
              value={taskType}
              onChange={(v) => { setTaskType(v); setSelectedFileIds([]) }}
              style={{ width: '100%' }}
            >
              <Option value="chapter_toc_extraction">章节目录抽取（从教材PDF提取章/节）</Option>
              <Option value="knowledge_extraction">知识点抽取（从PDF中提取知识点）</Option>
              <Option value="relation_extraction">关系抽取（分析知识点间依赖关系）</Option>
            </Select>
          </div>

          {taskType === 'knowledge_extraction' && (
            <div>
              <label style={{ display: 'block', marginBottom: 8 }}>选择源文件：</label>
              <Select
                mode="multiple"
                placeholder="选择已上传的PDF文件（可多选）"
                style={{ width: '100%' }}
                value={selectedFileIds}
                onChange={setSelectedFileIds}
              >
                {files.map(f => (
                  <Option key={f.id} value={f.id}>
                    {f.original_name} ({f.file_type === 'curriculum' ? '课标' : '教材'}{f.grade ? ` ${f.grade}年级` : ''})
                  </Option>
                ))}
              </Select>
            </div>
          )}

          {taskType === 'chapter_toc_extraction' && (
            <div>
              <label style={{ display: 'block', marginBottom: 8 }}>选择PDF（来自资料上传）：</label>
              <Select
                mode="multiple"
                placeholder="选择已上传的课本/教材PDF"
                style={{ width: '100%' }}
                value={selectedFileIds}
                onChange={setSelectedFileIds}
                optionFilterProp="label"
                showSearch
              >
                {chapterSourceFiles.map(f => (
                  <Option
                    key={f.id}
                    value={f.id}
                    label={f.original_name}
                  >
                    {f.original_name}
                    {' '}
                    <Tag color={f.file_type === 'curriculum' ? 'purple' : 'cyan'}>
                      {f.file_type === 'curriculum' ? '课标' : '教材'}
                    </Tag>
                    {f.grade ? ` ${f.grade}年级` : ''}
                    {f.semester ? ` ${f.semester}册` : ''}
                  </Option>
                ))}
              </Select>
              {chapterSourceFiles.length === 0 && (
                <div style={{ color: '#999', marginTop: 8 }}>
                  暂无已上传文件，请先到「资料上传」上传PDF
                </div>
              )}
              <div style={{ color: '#666', marginTop: 8 }}>
                列表与「资料上传」一致。选课本即可（即使类型显示为课标也可抽）。不调用大模型；重复抽取会覆盖该文件旧目录。
              </div>
            </div>
          )}

          {taskType === 'relation_extraction' && (
            <div style={{ color: '#666' }}>
              关系抽取将分析数据库中所有已有知识点，自动识别它们之间的前置依赖、关联和进阶关系。
            </div>
          )}
        </Space>
      </Modal>
    </div>
  )
}
