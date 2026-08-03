import React, { useEffect, useState, useMemo, useCallback } from 'react'
import {
  Tree, Card, Typography, Empty, Spin, Select, Button,
  Space, message, Divider, Popconfirm, Tabs, Tag, Collapse,
} from 'antd'
import { RobotOutlined, SaveOutlined, DeleteOutlined, BookOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import { knowledgeApi, resourceApi } from '../../api'
import {
  ExplanationBlocks,
  type ExplanationContentBlock,
} from '../../components/ExplanationBlocks'

const { Title, Text, Paragraph } = Typography

interface KnowledgePoint {
  id: string
  name: string
  short_name?: string
  domain: string
  category_1: string
  category_2: string
  cognitive_level?: string
}

interface TreeNode {
  key: string
  title: string
  children?: TreeNode[]
  isLeaf?: boolean
  kpId?: string
}

interface ExplanationData {
  id?: number
  kp_id: string
  title: string
  summary: string
  content: string
  content_blocks?: ExplanationContentBlock[]
  key_points: string[]
  examples: Array<{ problem: string; solution: string; explanation: string }>
  common_mistakes: Array<{ mistake: string; correction: string; reason: string }>
  difficulty_level: string
  status?: string
  version?: number
  created_at?: string
}

const DIFFICULTY_OPTIONS = [
  { value: 'basic', label: '基础入门' },
  { value: 'intermediate', label: '巩固提高' },
  { value: 'advanced', label: '拓展提升' },
]

export default function AIKnowledgeExplanation() {
  const [points, setPoints] = useState<KnowledgePoint[]>([])
  const [treeLoading, setTreeLoading] = useState(false)
  const [selectedKp, setSelectedKp] = useState<KnowledgePoint | null>(null)

  // Generation
  const [difficultyLevel, setDifficultyLevel] = useState('basic')
  const [generating, setGenerating] = useState(false)
  const [generatedContent, setGeneratedContent] = useState<ExplanationData | null>(null)

  // Saved explanations
  const [savedList, setSavedList] = useState<ExplanationData[]>([])
  const [savedTotal, setSavedTotal] = useState(0)
  const [savedLoading, setSavedLoading] = useState(false)
  const [savingGenerated, setSavingGenerated] = useState(false)

  useEffect(() => { fetchPoints() }, [])

  const fetchPoints = async () => {
    setTreeLoading(true)
    try {
      const all: KnowledgePoint[] = []
      let page = 1
      const pageSize = 500
      while (true) {
        const res = await knowledgeApi.listPoints({ page, page_size: pageSize })
        const items = res.data.items || []
        all.push(...items)
        if (items.length < pageSize || all.length >= (res.data.total || Infinity)) break
        page++
      }
      setPoints(all)
    } catch { /* ignore */ }
    finally { setTreeLoading(false) }
  }

  const fetchSaved = useCallback(async (kpId: string) => {
    setSavedLoading(true)
    try {
      const res = await resourceApi.listExplanations({ kp_id: kpId, page: 1, page_size: 20 })
      setSavedList(res.data.items || [])
      setSavedTotal(res.data.total || 0)
    } catch { setSavedList([]); setSavedTotal(0) }
    finally { setSavedLoading(false) }
  }, [])

  useEffect(() => {
    if (selectedKp) {
      setGeneratedContent(null)
      fetchSaved(selectedKp.id)
    } else {
      setSavedList([])
      setSavedTotal(0)
      setGeneratedContent(null)
    }
  }, [selectedKp, fetchSaved])

  // Build tree
  const treeData = useMemo(() => {
    const domainMap = new Map<string, Map<string, Map<string, KnowledgePoint[]>>>()
    for (const kp of points) {
      const domain = kp.domain || '未分类'
      const cat1 = kp.category_1 || '未分类'
      const cat2 = kp.category_2 || '未分类'
      if (!domainMap.has(domain)) domainMap.set(domain, new Map())
      const cat1Map = domainMap.get(domain)!
      if (!cat1Map.has(cat1)) cat1Map.set(cat1, new Map())
      const cat2Map = cat1Map.get(cat1)!
      if (!cat2Map.has(cat2)) cat2Map.set(cat2, [])
      cat2Map.get(cat2)!.push(kp)
    }
    const tree: TreeNode[] = []
    for (const [domain, cat1Map] of domainMap) {
      const domainNode: TreeNode = { key: `domain:${domain}`, title: domain, children: [] }
      for (const [cat1, cat2Map] of cat1Map) {
        const cat1Node: TreeNode = { key: `cat1:${domain}/${cat1}`, title: cat1, children: [] }
        for (const [cat2, kps] of cat2Map) {
          cat1Node.children!.push({
            key: `cat2:${domain}/${cat1}/${cat2}`,
            title: `${cat2}（${kps.length}）`,
            children: kps.map((kp) => ({
              key: `kp:${kp.id}`,
              title: kp.short_name || kp.name,
              isLeaf: true,
              kpId: kp.id,
            })),
          })
        }
        domainNode.children!.push(cat1Node)
      }
      tree.push(domainNode)
    }
    return tree
  }, [points])

  const handleSelect = (selectedKeys: React.Key[]) => {
    if (!selectedKeys.length) { setSelectedKp(null); return }
    const key = String(selectedKeys[0])
    if (key.startsWith('kp:')) {
      const kpId = key.replace('kp:', '')
      setSelectedKp(points.find((p) => p.id === kpId) || null)
    } else {
      setSelectedKp(null)
    }
  }

  // Generate explanation
  const handleGenerate = async () => {
    if (!selectedKp) return
    setGenerating(true)
    setGeneratedContent(null)
    try {
      const res = await resourceApi.generateExplanation({
        kp_id: selectedKp.id,
        difficulty_level: difficultyLevel,
      })
      setGeneratedContent(res.data)
      message.success('讲解内容生成成功')
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '生成失败，请重试')
    } finally {
      setGenerating(false)
    }
  }

  // Save generated
  const handleSave = async () => {
    if (!generatedContent) return
    setSavingGenerated(true)
    try {
      await resourceApi.saveExplanation(generatedContent)
      message.success('保存成功')
      if (selectedKp) fetchSaved(selectedKp.id)
    } catch (e: any) {
      message.error('保存失败')
    } finally {
      setSavingGenerated(false)
    }
  }

  // Delete saved
  const handleDelete = async (id: number) => {
    try {
      await resourceApi.deleteExplanation(id)
      message.success('删除成功')
      if (selectedKp) fetchSaved(selectedKp.id)
    } catch {
      message.error('删除失败')
    }
  }

  // Render explanation content
  const renderExplanation = (data: ExplanationData) => (
    <div style={{ lineHeight: 1.8 }} className="explanation-content">
      <Title level={4}>{data.title}</Title>
      {data.summary && (
        <Card size="small" style={{ marginBottom: 16, background: '#f6ffed', borderColor: '#b7eb8f' }}>
          <Text strong>📌 核心概要：</Text> {data.summary}
        </Card>
      )}

      {data.content && (
        <div style={{ marginBottom: 16 }}>
          <Title level={5}>📖 图文讲解</Title>
          <ExplanationBlocks blocks={data.content_blocks} fallbackContent={data.content} />
        </div>
      )}

      {data.key_points && data.key_points.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Title level={5}>🔑 重点要点</Title>
          <ul style={{ paddingLeft: 20 }}>
            {data.key_points.map((pt, i) => (
              <li key={i} style={{ marginBottom: 6 }}><ReactMarkdown components={{ p: ({ children }) => <span>{children}</span> }}>{pt}</ReactMarkdown></li>
            ))}
          </ul>
        </div>
      )}

      {data.examples && data.examples.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Title level={5}>✏️ 典型例题</Title>
          <Collapse
            items={data.examples.map((ex, i) => ({
              key: String(i),
              label: <Text strong>例{i + 1}：{ex.problem}</Text>,
              children: (
                <div>
                  {ex.explanation && (
                    <div style={{ marginBottom: 8 }}>
                      <Text type="secondary" strong>💡 思路：</Text>
                      <div style={{ paddingLeft: 16 }}><ReactMarkdown>{ex.explanation}</ReactMarkdown></div>
                    </div>
                  )}
                  <div>
                    <Text type="success" strong>✅ 解答：</Text>
                    <div style={{ paddingLeft: 16 }}><ReactMarkdown>{ex.solution}</ReactMarkdown></div>
                  </div>
                </div>
              ),
            }))}
            defaultActiveKey={['0']}
          />
        </div>
      )}

      {data.common_mistakes && data.common_mistakes.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Title level={5}>⚠️ 常见错误</Title>
          {data.common_mistakes.map((cm, i) => (
            <Card key={i} size="small" style={{ marginBottom: 8, borderColor: '#ffccc7' }}>
              <div style={{ marginBottom: 4 }}><Text type="danger" strong>❌ 错误：</Text>{cm.mistake}</div>
              <div style={{ marginBottom: 4 }}><Text type="success" strong>✅ 正确：</Text>{cm.correction}</div>
              <div><Text type="secondary">💡 原因：</Text>{cm.reason}</div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )

  const renderRightPanel = () => {
    if (!selectedKp) {
      return <Empty description="请从左侧选择一个知识点" style={{ marginTop: 80 }} />
    }
    return (
      <div>
        <Card size="small" style={{ marginBottom: 16, background: '#fff7e6', borderColor: '#ffd591' }}>
          <Title level={5} style={{ margin: 0 }}>{selectedKp.short_name || selectedKp.name}</Title>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {selectedKp.domain} › {selectedKp.category_1} › {selectedKp.category_2}
          </Text>
        </Card>

        <Tabs
          defaultActiveKey="generate"
          items={[
            {
              key: 'generate',
              label: 'AI生成讲解',
              children: (
                <div>
                  <div style={{ marginBottom: 16 }}>
                    <Space>
                      <Text>讲解深度：</Text>
                      <Select
                        value={difficultyLevel}
                        onChange={setDifficultyLevel}
                        options={DIFFICULTY_OPTIONS}
                        style={{ width: 140 }}
                      />
                      <Button
                        type="primary"
                        icon={<RobotOutlined />}
                        loading={generating}
                        onClick={handleGenerate}
                      >
                        AI 生成图文讲解
                      </Button>
                    </Space>
                  </div>

                  {generating && (
                    <div style={{ textAlign: 'center', padding: 40 }}>
                      <Spin size="large" tip="AI 正在生成讲解内容，请稍候..." />
                    </div>
                  )}

                  {generatedContent && !generating && (
                    <Card
                      title="生成结果"
                      extra={
                        <Button
                          type="primary"
                          icon={<SaveOutlined />}
                          loading={savingGenerated}
                          onClick={handleSave}
                        >
                          保存
                        </Button>
                      }
                    >
                      {renderExplanation(generatedContent)}
                    </Card>
                  )}
                </div>
              ),
            },
            {
              key: 'saved',
              label: `已保存 (${savedTotal})`,
              children: (
                <Spin spinning={savedLoading}>
                  {savedList.length === 0 ? (
                    <Empty description="暂无已保存的讲解内容" />
                  ) : (
                    savedList.map((item) => (
                      <Card
                        key={item.id}
                        size="small"
                        style={{ marginBottom: 12 }}
                        title={
                          <span>
                            <BookOutlined style={{ marginRight: 8 }} />
                            {item.title}
                            <Tag style={{ marginLeft: 8 }} color="blue">
                              {DIFFICULTY_OPTIONS.find(d => d.value === item.difficulty_level)?.label || item.difficulty_level}
                            </Tag>
                            <Tag>v{item.version}</Tag>
                          </span>
                        }
                        extra={
                          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(item.id!)}>
                            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
                          </Popconfirm>
                        }
                      >
                        {renderExplanation(item)}
                      </Card>
                    ))
                  )}
                </Spin>
              ),
            },
          ]}
        />
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 140px)' }}>
      {/* Left: Knowledge Tree */}
      <Card
        title="知识点目录"
        size="small"
        style={{ width: 280, flexShrink: 0, overflow: 'auto' }}
        bodyStyle={{ padding: '8px 0', overflow: 'auto', maxHeight: 'calc(100vh - 220px)' }}
      >
        <Spin spinning={treeLoading}>
          {treeData.length > 0 ? (
            <Tree
              treeData={treeData}
              onSelect={handleSelect}
              showLine
              blockNode
              style={{ fontSize: 13 }}
            />
          ) : (
            <Empty description="暂无知识点" />
          )}
        </Spin>
      </Card>

      {/* Right: Content */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {renderRightPanel()}
      </div>
    </div>
  )
}
