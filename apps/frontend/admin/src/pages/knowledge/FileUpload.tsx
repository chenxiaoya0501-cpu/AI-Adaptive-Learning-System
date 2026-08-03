import { useEffect, useState } from 'react'
import { Upload, Button, Table, Tag, Space, Select, message, Card, Typography, Popconfirm } from 'antd'
import { UploadOutlined, DeleteOutlined, FileTextOutlined } from '@ant-design/icons'
import { fileApi } from '../../api'

const { Title } = Typography
const { Option } = Select
const { Dragger } = Upload

export default function FileUpload() {
  const [files, setFiles] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [uploadType, setUploadType] = useState<string>('curriculum')
  const [grade, setGrade] = useState<string>('')
  const [semester, setSemester] = useState<string>('')

  const fetchFiles = async () => {
    setLoading(true)
    try {
      const res = await fileApi.list()
      setFiles(res.data || [])
    } catch {
      message.error('获取文件列表失败')
    }
    setLoading(false)
  }

  useEffect(() => { fetchFiles() }, [])

  const parseFileInfo = (filename: string) => {
    let parsedGrade = ''
    let parsedSemester = ''
    const gradeMap: Record<string, string> = {
      '七': '7', '八': '8', '九': '9',
      '7': '7', '8': '8', '9': '9',
    }
    const gradeMatch = filename.match(/([七八九789])年级/)
    if (gradeMatch) {
      parsedGrade = gradeMap[gradeMatch[1]] || ''
    }
    if (filename.includes('上') || filename.includes('上册') || filename.includes('上学期')) {
      parsedSemester = '上'
    } else if (filename.includes('下') || filename.includes('下册') || filename.includes('下学期')) {
      parsedSemester = '下'
    }
    return { parsedGrade, parsedSemester }
  }

  const guessFileType = (filename: string, selected: string) => {
    // 文件名含课本/教材时自动归为教材，避免误选课标导致后续选不到
    if (/课本|教材|电子书/.test(filename)) return 'textbook'
    return selected
  }

  const handleUpload = async (options: any) => {
    const { file, onSuccess, onError } = options
    const formData = new FormData()
    const resolvedType = guessFileType(file.name, uploadType)
    formData.append('file', file)
    formData.append('file_type', resolvedType)
    if (resolvedType !== uploadType) {
      message.info(`${file.name} 已按文件名识别为「教材」`)
    }

    // 优先使用手动选择的值，否则从文件名自动解析
    const { parsedGrade, parsedSemester } = parseFileInfo(file.name)
    const finalGrade = grade || parsedGrade
    const finalSemester = semester || parsedSemester
    if (finalGrade) formData.append('grade', finalGrade)
    if (finalSemester) formData.append('semester', finalSemester)

    try {
      await fileApi.upload(formData)
      message.success(`${file.name} 上传成功`)
      onSuccess('ok')
      fetchFiles()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '上传失败')
      onError(e)
    }
  }

  const handleDelete = async (id: number) => {
    await fileApi.delete(id)
    message.success('已删除')
    fetchFiles()
  }

  const statusLabels: Record<string, { label: string; color: string }> = {
    uploaded: { label: '已上传', color: 'default' },
    parsing: { label: '解析中', color: 'processing' },
    annotating: { label: '标注中', color: 'processing' },
    parsed: { label: '已解析', color: 'success' },
    failed: { label: '失败', color: 'error' },
  }

  const columns = [
    { title: '文件名', dataIndex: 'original_name', key: 'original_name', ellipsis: true },
    {
      title: '类型', dataIndex: 'file_type', key: 'file_type', width: 140,
      render: (v: 'curriculum' | 'textbook', record: any) => (
        <Select
          size="small"
          value={v}
          style={{ width: 120 }}
          onChange={async (nv: 'curriculum' | 'textbook') => {
            try {
              await fileApi.updateType(record.id, nv)
              message.success('类型已更新')
              fetchFiles()
            } catch (e: any) {
              message.error(e.response?.data?.detail || '更新失败')
            }
          }}
        >
          <Option value="curriculum">课程标准</Option>
          <Option value="textbook">教材</Option>
        </Select>
      )
    },
    { title: '年级', dataIndex: 'grade', key: 'grade', width: 80, render: (v: string) => v ? `${v}年级` : '-' },
    {
      title: '学期', dataIndex: 'semester', key: 'semester', width: 80,
      render: (v: string) => v ? `${v}册` : '-'
    },
    {
      title: '大小', dataIndex: 'file_size', key: 'file_size', width: 100,
      render: (v: number) => v ? `${(v / 1024 / 1024).toFixed(1)} MB` : '-'
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (v: string) => {
        const info = statusLabels[v] || { label: v, color: 'default' }
        return <Tag color={info.color}>{info.label}</Tag>
      }
    },
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
      <Title level={4}>资料上传</Title>

      <Card style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
          <Space wrap>
            <Select value={uploadType} onChange={setUploadType} style={{ width: 150 }}>
              <Option value="curriculum">课程标准</Option>
              <Option value="textbook">教材</Option>
            </Select>
            <Select placeholder="年级(可选)" allowClear value={grade || undefined} onChange={v => setGrade(v || '')} style={{ width: 110 }}>
              <Option value="7">7年级</Option>
              <Option value="8">8年级</Option>
              <Option value="9">9年级</Option>
            </Select>
            <Select placeholder="学期(可选)" allowClear value={semester || undefined} onChange={v => setSemester(v || '')} style={{ width: 110 }}>
              <Option value="上">上册</Option>
              <Option value="下">下册</Option>
            </Select>
          </Space>

          <Dragger
            customRequest={handleUpload}
            accept=".pdf"
            showUploadList={false}
            multiple
          >
            <p className="ant-upload-drag-icon">
              <FileTextOutlined style={{ fontSize: 48, color: '#1890ff' }} />
            </p>
            <p className="ant-upload-text">点击或拖拽PDF文件到此区域上传</p>
            <p className="ant-upload-hint">
              支持课程标准PDF、教材PDF。上传后可在"知识抽取"中进行知识点提取。
            </p>
          </Dragger>
        </Space>
      </Card>

      <Card title="已上传文件" size="small">
        <Table
          columns={columns}
          dataSource={files}
          rowKey="id"
          loading={loading}
          size="small"
          pagination={{ pageSize: 10 }}
        />
      </Card>
    </div>
  )
}
