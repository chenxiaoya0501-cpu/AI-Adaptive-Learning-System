import { api } from './client'

export type GoalResultRecord = {
  id: number
  goal_id: number
  test_paper_id?: number | null
  event_type: 'submitted' | 'graded' | string
  title: string
  summary?: string | null
  earned_score?: number | null
  total_score?: number | null
  correct_count?: number | null
  total_count?: number | null
  created_at?: string | null
}

export type LearningGoal = {
  id: number
  user_id: number
  title?: string | null
  exam_type: string
  subject: string
  target_score: number
  current_score_estimate?: number | null
  grade_stage: string
  exam_date?: string | null
  daily_study_minutes?: number | null
  region?: string | null
  status: string
  is_primary: boolean
  learned_chapter_ids: number[]
  learned_kp_ids: string[]
  learned_chapter_count: number
  learned_kp_count: number
  mastery_status: 'pending_test' | 'assessed' | string
  needs_replan: boolean
  recent_results?: GoalResultRecord[]
  created_at?: string | null
  updated_at?: string | null
}

export type GoalCreatePayload = {
  exam_type?: string
  subject?: string
  target_score: number
  grade_stage: string
  exam_date?: string | null
  daily_study_minutes?: number | null
  region?: string | null
  learned_chapter_ids: number[]
  mastery_status?: 'pending_test' | 'assessed'
  title?: string
  set_as_primary?: boolean
}

export type GoalUpdatePayload = Partial<Omit<GoalCreatePayload, 'set_as_primary'>>

export type LearningMapNode = {
  id: string
  node_type: 'knowledge' | 'question'
  label: string
  status: string
  inferred_status?: string | null
  mastery_score?: number | null
  mastery_level?: 'l0' | 'l1' | 'l2' | 'l3' | 'l4' | 'l5' | 'l6'
  confidence?: number
  status_source?: 'combined' | 'none'
  direct_positive?: number
  direct_negative?: number
  inferred_positive?: number
  inferred_negative?: number
  attempt_count?: number
  recent_correct_streak?: number
  recent_wrong_streak?: number
  kp_id?: string
  description?: string
  domain?: string | null
  category_1?: string | null
  category_2?: string | null
  grade?: string | null
  chapter?: string | null
  cognitive_level?: string | null
  is_in_goal_scope?: boolean
  question_stats?: { correct: number; wrong: number; pending: number }
  seq?: number
  question_type?: string
  score?: number
  score_got?: number
  score_percent?: number
  score_level?: 'l1' | 'l2' | 'l3' | 'l4' | 'l5' | 'l6'
  content?: string
  options?: unknown
  source_paper_id?: number | null
  source_question_id?: number | null
  question_identity?: string
  view_scope?: 'attempt' | 'summary'
  test_paper_id?: number | null
  test_paper_title?: string | null
  test_attempt_index?: number | null
  tested_at?: string | null
  user_answer?: string | null
  correct_answer?: string | null
  analysis?: string | null
  kp_ids?: string[]
}

export type LearningMapEdge = {
  id: string
  source: string
  target: string
  type: 'prerequisite' | 'related' | 'question' | string
  label?: string
}

export type LearningMapData = {
  goal: {
    id: number
    title: string
    subject: string
    grade_stage: string
    target_score: number
  }
  paper?: {
    id: number
    title?: string | null
    earned_score?: number | null
    total_score?: number | null
  } | null
  papers: {
    id: number
    title: string
    earned_score?: number | null
    total_score?: number | null
    attempt_index: number
    tested_at?: string | null
    question_count: number
  }[]
  nodes: LearningMapNode[]
  edges: LearningMapEdge[]
  summary: {
    knowledge_count: number
    question_count: number
    summary_question_count?: number
    test_count?: number
    relation_count: number
    has_assessment: boolean
  }
}

export const goalsApi = {
  list: (status: string = 'active') =>
    api.get<LearningGoal[]>('/goals', { params: { status } }),
  primary: () => api.get<LearningGoal | null>('/goals/primary'),
  get: (id: number) => api.get<LearningGoal>(`/goals/${id}`),
  create: (data: GoalCreatePayload) => api.post<LearningGoal>('/goals', data),
  update: (id: number, data: GoalUpdatePayload) => api.put<LearningGoal>(`/goals/${id}`, data),
  setPrimary: (id: number) => api.post<LearningGoal>(`/goals/${id}/set-primary`),
  archive: (id: number) => api.post<LearningGoal>(`/goals/${id}/archive`),
  copy: (id: number) => api.post<LearningGoal>(`/goals/${id}/copy`),
  ackReplan: (id: number) => api.post<LearningGoal>(`/goals/${id}/ack-replan`),
  learningMap: (id: number) =>
    api.get<LearningMapData>(`/goals/${id}/learning-map`, {
      params: { refresh_at: Date.now() },
    }),
  previewKp: (chapter_ids: number[], grade_stage?: string) =>
    api.post<{
      chapter_count: number
      kp_count: number
      kp_ids: string[]
      prior_stages_included?: string[]
    }>('/goals/preview-kp', { chapter_ids, grade_stage }),
}
