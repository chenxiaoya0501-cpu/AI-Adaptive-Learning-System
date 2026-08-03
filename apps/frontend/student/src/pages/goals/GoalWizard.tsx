import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Steps,
  Typography,
  message,
} from 'antd'
import dayjs from 'dayjs'
import { useNavigate, useParams } from 'react-router-dom'
import { assetsApi, type ChapterNode, type ChapterTree } from '../../api/assets'
import { goalsApi, type LearningGoal } from '../../api/goals'
import ChapterPicker from './ChapterPicker'

/** 仅章级 id（不含节） */
function collectChapterIds(nodes: ChapterNode[]): number[] {
  const ids: number[] = []
  nodes.forEach((n) => {
    if (n.level === 'section') return
    ids.push(n.id)
  })
  return ids
}

const GRADE_OPTIONS = [
  '七年级上',
  '七年级下',
  '八年级上',
  '八年级下',
  '九年级上',
  '九年级下',
]

export default function GoalWizard() {
  const { id } = useParams()
  const editingId = id ? Number(id) : null
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [form] = Form.useForm()
  const [trees, setTrees] = useState<ChapterTree[]>([])
  const [chapterIds, setChapterIds] = useState<number[]>([])
  const [kpCount, setKpCount] = useState(0)
  const [loading, setLoading] = useState(false)
  const [existing, setExisting] = useState<LearningGoal | null>(null)
  const [chaptersLoading, setChaptersLoading] = useState(false)
  const gradeStage = Form.useWatch('grade_stage', form)

  useEffect(() => {
    if (!editingId) return
    ;(async () => {
      try {
        const { data } = await goalsApi.get(editingId)
        setExisting(data)
        form.setFieldsValue({
          exam_type: data.exam_type,
          subject: data.subject,
          target_score: data.target_score,
          grade_stage: data.grade_stage,
          region: data.region || '浙江',
          daily_study_minutes: data.daily_study_minutes ?? undefined,
          exam_date: data.exam_date ? dayjs(data.exam_date) : undefined,
        })
        setChapterIds(data.learned_chapter_ids || [])
        setKpCount(data.learned_kp_count || 0)
      } catch {
        message.error('目标不存在或无权访问')
        navigate('/goals')
      }
    })()
  }, [editingId, form, navigate])

  // 按年级阶段拉取对应教材目录；切换年级时剔除不在新目录中的已选章节
  useEffect(() => {
    if (!gradeStage) {
      setTrees([])
      return
    }
    let cancelled = false
    ;(async () => {
      setChaptersLoading(true)
      try {
        const { data } = await assetsApi.chapters(gradeStage)
        if (cancelled) return
        setTrees(data)
        const allowed = new Set(data.flatMap((t) => collectChapterIds(t.nodes)))
        setChapterIds((prev) => prev.filter((id) => allowed.has(id)))
      } catch {
        if (!cancelled) {
          message.error('加载章节目录失败')
          setTrees([])
        }
      } finally {
        if (!cancelled) setChaptersLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [gradeStage])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      if (!chapterIds.length) {
        setKpCount(0)
        return
      }
      try {
        const { data } = await goalsApi.previewKp(chapterIds, gradeStage)
        if (!cancelled) setKpCount(data.kp_count)
      } catch {
        if (!cancelled) setKpCount(0)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [chapterIds, gradeStage])

  const nextGoalStep = async () => {
    await form.validateFields([
      'exam_type',
      'subject',
      'region',
      'target_score',
    ])
    setStep(1)
  }

  const nextStatusStep = async () => {
    await form.validateFields(['grade_stage'])
    setStep(2)
  }

  const cancelWizard = () => {
    Modal.confirm({
      title: editingId ? '取消编辑？' : '取消创建？',
      content: '未保存的修改将丢失。',
      okText: '确定取消',
      cancelText: '继续填写',
      onOk: () => navigate('/goals'),
    })
  }

  const formatExamDate = (v: unknown): string | null => {
    if (v == null || v === '') return null
    if (typeof v === 'string') return v.slice(0, 10)
    if (dayjs.isDayjs(v) && v.isValid()) return v.format('YYYY-MM-DD')
    // Ant Design 偶发回传 dayjs-like / Date
    const d = dayjs(v as any)
    return d.isValid() ? d.format('YYYY-MM-DD') : null
  }

  const submit = async () => {
    // 确认步会卸载前两步表单项，需用 true 取出全部已填字段
    const values = form.getFieldsValue(true)
    if (values.target_score == null || values.target_score === '') {
      message.error('请返回填写目标分数')
      setStep(0)
      return
    }
    if (!values.grade_stage) {
      message.error('请返回选择年级阶段')
      setStep(1)
      return
    }
    setLoading(true)
    try {
      const base = {
        exam_type: values.exam_type || '中考',
        subject: values.subject || '数学',
        region: values.region || '浙江',
        target_score: Number(values.target_score),
        exam_date: formatExamDate(values.exam_date),
        daily_study_minutes:
          values.daily_study_minutes == null || values.daily_study_minutes === ''
            ? null
            : Number(values.daily_study_minutes),
        grade_stage: values.grade_stage as string,
        learned_chapter_ids: chapterIds,
        mastery_status: 'pending_test' as const,
      }
      if (editingId) {
        // 更新接口不接受 set_as_primary
        await goalsApi.update(editingId, base)
        message.success('已保存')
      } else {
        const { data } = await goalsApi.create({ ...base, set_as_primary: true })
        message.success(`已创建「${data.title || '学习目标'}」，可在列表中查看`)
      }
      navigate('/goals', { replace: true })
    } catch (e: any) {
      const d = e?.response?.data?.detail
      const msg =
        typeof d === 'string'
          ? d
          : Array.isArray(d)
            ? d.map((x: any) => x.msg || x.loc?.join('.') || JSON.stringify(x)).join('；')
            : e?.message
              ? `保存失败：${e.message}`
              : '保存失败，请确认后端已启动'
      message.error(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        {editingId ? '编辑学习目标与状态' : '新建学习目标与状态'}
      </Typography.Title>
      <Steps
        current={step}
        style={{ marginBottom: 24 }}
        items={[
          { title: '学习目标设置' },
          { title: '现有状态设置' },
          { title: '确认' },
        ]}
      />

      <Card>
        <Form
          form={form}
          layout="vertical"
          preserve
          initialValues={{
            exam_type: '中考',
            subject: '数学',
            region: '浙江',
            target_score: 110,
            grade_stage: '九年级上',
          }}
        >
          {step === 0 && (
            <>
              <Typography.Paragraph type="secondary">
                先设定你想达到的考试目标与学习节奏。
              </Typography.Paragraph>
              <Row gutter={16}>
                <Col xs={24} sm={12}>
                  <Form.Item name="exam_type" label="考试类型" rules={[{ required: true }]}>
                    <Select
                      options={[
                        { value: '中考', label: '中考' },
                        { value: '高考', label: '高考（预留）' },
                        { value: '职业教育', label: '职业教育（预留）' },
                        { value: '其它', label: '其它' },
                      ]}
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item name="subject" label="科目" rules={[{ required: true }]}>
                    <Select options={[{ value: '数学', label: '数学' }]} />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16}>
                <Col xs={24} sm={12}>
                  <Form.Item name="region" label="考区" rules={[{ required: true, message: '请选择考区' }]}>
                    <Select
                      options={[
                        { value: '浙江', label: '浙江' },
                        { value: '其它', label: '其它' },
                      ]}
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item
                    name="target_score"
                    label="目标分数"
                    rules={[{ required: true, message: '请填写目标分' }]}
                  >
                    <InputNumber min={0} max={200} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16}>
                <Col xs={24} sm={12}>
                  <Form.Item name="exam_date" label="考试日（可选）">
                    <DatePicker style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item name="daily_study_minutes" label="每日可学时长（分钟，可选）">
                    <InputNumber min={0} max={1440} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
              <Space>
                <Button onClick={cancelWizard}>取消</Button>
                <Button type="primary" onClick={nextGoalStep}>
                  下一步：现有状态
                </Button>
              </Space>
            </>
          )}

          {step === 1 && (
            <>
              <Typography.Paragraph type="secondary">
                描述你当前的学习进度；掌握情况通过测评体现，创建时不必马上测试。
              </Typography.Paragraph>
              <Form.Item
                name="grade_stage"
                label="年级阶段"
                rules={[{ required: true, message: '请选择年级' }]}
              >
                <Select
                  options={GRADE_OPTIONS.map((g) => ({ value: g, label: g }))}
                  onChange={() => {
                    // 切换年级时先清空勾选，避免残留其它年级章节
                    setChapterIds([])
                  }}
                />
              </Form.Item>

              <Typography.Text strong>已学章节</Typography.Text>
              <Alert
                type="info"
                showIcon
                style={{ margin: '8px 0 12px' }}
                message={
                  chaptersLoading
                    ? `正在加载「${gradeStage || ''}」目录…`
                    : `「${gradeStage || ''}」· 已选 ${chapterIds.length} 章 · 约 ${kpCount} 个知识点`
                }
                description="仅展示本册章目录。勾选本册已学章后，系统会自动把此前各册（如九年级上会含七、八年级）全部计入测评知识点范围。"
              />
              <ChapterPicker
                trees={trees}
                value={chapterIds}
                onChange={setChapterIds}
                rootLabel={gradeStage}
              />

              <Alert
                type="info"
                showIcon
                style={{ marginTop: 20, marginBottom: 16 }}
                message="掌握情况"
                description="掌握程度通过测评来体现。创建完成后，你可以随时发起测评，不必现在测试。"
              />

              <Space>
                <Button onClick={cancelWizard}>取消</Button>
                <Button onClick={() => setStep(0)}>上一步</Button>
                <Button type="primary" onClick={nextStatusStep}>
                  下一步：确认
                </Button>
              </Space>
            </>
          )}

          {step === 2 && (
            <>
              <Typography.Title level={5}>学习目标</Typography.Title>
              <Typography.Paragraph>
                {form.getFieldValue('exam_type')} · {form.getFieldValue('subject')} ·{' '}
                {form.getFieldValue('region')} · 目标{' '}
                <strong>{form.getFieldValue('target_score')}</strong> 分
                {form.getFieldValue('exam_date')
                  ? ` · 考试日 ${form.getFieldValue('exam_date').format('YYYY-MM-DD')}`
                  : ''}
                {form.getFieldValue('daily_study_minutes') != null
                  ? ` · 每日 ${form.getFieldValue('daily_study_minutes')} 分钟`
                  : ''}
              </Typography.Paragraph>

              <Typography.Title level={5}>现有状态</Typography.Title>
              <Typography.Paragraph>
                年级：{form.getFieldValue('grade_stage')}
                <br />
                已学章节 {chapterIds.length} 个，约 {kpCount} 个知识点
                {!chapterIds.length && (
                  <Typography.Text type="warning">（未勾选章节时，正式测评将不可启动）</Typography.Text>
                )}
                <br />
                掌握情况：创建后可随时测评
              </Typography.Paragraph>

              {existing?.needs_replan && (
                <Alert
                  style={{ marginBottom: 12 }}
                  type="warning"
                  showIcon
                  message="保存后将标记为「建议重测或重规划」"
                />
              )}
              <Space>
                <Button onClick={cancelWizard}>取消</Button>
                <Button onClick={() => setStep(1)}>上一步</Button>
                <Button type="primary" loading={loading} onClick={submit}>
                  {editingId ? '保存' : '完成创建'}
                </Button>
              </Space>
            </>
          )}
        </Form>
      </Card>
    </div>
  )
}
