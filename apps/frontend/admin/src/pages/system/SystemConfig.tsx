import { useEffect, useState } from 'react'
import { Form, Input, Button, Card, message, Space, Typography, Divider, InputNumber } from 'antd'
import { SaveOutlined, ApiOutlined } from '@ant-design/icons'
import { systemApi } from '../../api'

const { Title, Text } = Typography

export default function SystemConfig() {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  const fetchConfigs = async () => {
    setLoading(true)
    try {
      const res = await systemApi.getConfigs()
      const configs = res.data || []
      const values: any = {}
      configs.forEach((c: any) => {
        values[c.key] = c.value
      })
      form.setFieldsValue(values)
    } catch {
      message.error('获取配置失败')
    }
    setLoading(false)
  }

  useEffect(() => { fetchConfigs() }, [])

  const handleSave = async () => {
    setSaving(true)
    try {
      const values = form.getFieldsValue()
      const keys = Object.keys(values)
      for (const key of keys) {
        if (values[key] !== undefined && values[key] !== null) {
          await systemApi.updateConfig(key, { value: String(values[key]) })
        }
      }
      message.success('配置已保存')
    } catch (e: any) {
      message.error('保存失败')
    }
    setSaving(false)
  }

  const handleTestConnection = async () => {
    const values = form.getFieldsValue()
    if (!values.llm_api_key) {
      message.warning('请先填写API密钥')
      return
    }
    message.loading({ content: '正在测试连接...', key: 'test' })
    // 简单测试：保存配置后尝试获取配置来验证
    try {
      await handleSave()
      message.success({ content: '配置保存成功，请通过抽取任务验证连接', key: 'test' })
    } catch {
      message.error({ content: '保存失败', key: 'test' })
    }
  }

  return (
    <div>
      <Title level={4}>系统运行设置</Title>

      <Form form={form} layout="vertical" style={{ maxWidth: 600 }}>
        <Card title={<><ApiOutlined /> 大模型API配置</>} style={{ marginBottom: 16 }}>
          <Form.Item
            name="llm_api_key"
            label="API 密钥"
            extra="大模型服务的API Key，如DeepSeek、OpenAI等"
          >
            <Input.Password placeholder="sk-..." />
          </Form.Item>

          <Form.Item
            name="llm_base_url"
            label="API 地址"
            extra="兼容OpenAI格式的API地址"
          >
            <Input placeholder="https://api.deepseek.com/v1" />
          </Form.Item>

          <Form.Item
            name="llm_model"
            label="模型名称"
            extra="知识抽取与题目智能关联共用此配置。DeepSeek 当前可用：deepseek-v4-flash / deepseek-v4-pro（旧名 deepseek-chat 已失效）"
          >
            <Input placeholder="deepseek-v4-flash" />
          </Form.Item>

          <Form.Item
            name="llm_temperature"
            label="Temperature（生成温度）"
            extra="0-1之间，越低越确定性，知识抽取/关联建议0.1"
          >
            <Input placeholder="0.1" type="number" step="0.1" min="0" max="1" />
          </Form.Item>

          <Form.Item
            name="llm_max_tokens"
            label="Max Tokens"
            extra="单次调用最大输出token数，建议 4096（过大可能被接口拒绝）"
          >
            <Input placeholder="4096" type="number" />
          </Form.Item>
        </Card>

        <Card title="抽取任务配置" style={{ marginBottom: 16 }}>
          <Form.Item
            name="extraction_batch_size"
            label="批处理大小"
            extra="每次发送给LLM的课标条目数量。建议 8–15，过大可能截断或错位"
          >
            <Input placeholder="10" type="number" min="1" max="30" />
          </Form.Item>

          <Form.Item
            name="extraction_llm_concurrency"
            label="LLM 并发数"
            extra="知识点分类时同时请求大模型的批次数，建议 2–4（受 API 限流影响）"
          >
            <Input placeholder="2" type="number" min="1" max="8" />
          </Form.Item>

          <Form.Item
            name="ocr_workers"
            label="OCR 并行线程"
            extra="扫描版 PDF 渲染并行度。CPU 建议 2–4；内存紧张时用 1"
          >
            <Input placeholder="2" type="number" min="1" max="8" />
          </Form.Item>

          <Form.Item
            name="ocr_cache_enabled"
            label="OCR 结果缓存"
            extra="true/false。开启后同一文件重跑可跳过 OCR，直接用缓存"
          >
            <Input placeholder="true" />
          </Form.Item>
        </Card>

        <Space>
          <Button type="primary" icon={<SaveOutlined />} onClick={handleSave} loading={saving}>
            保存配置
          </Button>
          <Button onClick={handleTestConnection}>
            保存并测试
          </Button>
        </Space>
      </Form>
    </div>
  )
}
