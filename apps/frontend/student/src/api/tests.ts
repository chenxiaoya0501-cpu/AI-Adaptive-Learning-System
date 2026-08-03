import { api } from './client'

export type TypeStructureItem = {
  question_type: string
  count: number
  subtotal: number
  score_each?: number | null
}

export type AssemblePreview = {
  goal_id: number
  goal_title?: string | null
  grade_stage: string
  region?: string | null
  learned_chapter_count: number
  learned_kp_count: number
  template_id?: number | null
  template_name?: string | null
  template_status?: string | null
  total_score: number
  type_structure: TypeStructureItem[]
  readiness_ok: boolean
  readiness_messages: string[]
}

export type TestQuestionPublic = {
  id: number
  seq: number
  question_type: string
  content: string
  options?: unknown
  score: number
  primary_kp_id?: string | null
  images?: unknown
  difficulty?: number | null
  source_exam_paper_id?: number | null
}

export type TestPaperSummary = {
  id: number
  goal_id: number
  template_id?: number | null
  paper_kind: string
  bank_type: string
  status: string
  title?: string | null
  total_score: number
  earned_score?: number | null
  question_count: number
  degraded: boolean
  warnings?: string[] | null
  created_at?: string | null
}

export type TestPaperDetail = TestPaperSummary & {
  type_structure?: TypeStructureItem[] | null
  algorithm_version: string
  lambda_value: number
  questions: TestQuestionPublic[]
}

export type AssemblePayload = {
  goal_id: number
  bank_type: 'real' | 'mock'
  lambda?: number
  template_id?: number
  paper_kind?: string
}

export type AnswerPayload = {
  selected_option?: string | null
  answer_text?: string | null
  image_urls?: string[] | null
  is_marked_uncertain?: boolean
}

export type AnswerPublic = {
  test_question_id: number
  selected_option?: string | null
  answer_text?: string | null
  image_urls?: string[] | null
  is_marked_uncertain?: boolean
  is_correct?: boolean | null
  score_got?: number | null
}

export type TakingSession = {
  paper: TestPaperDetail
  answers: AnswerPublic[]
  answered_count: number
  total_count: number
  readonly: boolean
}

export type SubmitResult = {
  paper_id: number
  goal_id: number
  status: string
  answered_count: number
  total_count: number
  correct_count: number
  earned_score?: number | null
  total_score: number
  graded_count: number
  message: string
}

export type QuestionResultItem = {
  question_id: number
  seq: number
  question_type: string
  score: number
  is_correct?: boolean | null
  score_got?: number | null
  selected_option?: string | null
  answer_text?: string | null
  correct_answer?: string | null
  source_exam_paper_id?: number | null
  grading_note?: string | null
  content?: string | null
  options?: unknown
  analysis?: string | null
  source_label?: string | null
  source_year?: string | null
  source_region?: string | null
  source_question_number?: number | null
  ability_dimension?: string | null
  difficulty?: number | null
  primary_kp_id?: string | null
}

export type AssessmentAbilityDist = {
  dimension: string
  wrong_count: number
  attempted: number
  wrong_rate: number
  seqs?: number[]
}

export type AssessmentDiffDist = {
  bucket: string
  wrong_count: number
  attempted: number
  wrong_rate: number
}

export type AssessmentKpDist = {
  kp_id?: string | null
  kp_name: string
  kp_description?: string | null
  category_1?: string
  category_2?: string
  wrong_count: number
  seqs?: number[]
}

export type AssessmentCatDist = {
  category_1: string
  wrong_count: number
  seqs?: number[]
}

export type AssessmentKnowledgeItem = {
  question_id: number
  seq: number
  question_type?: string
  score?: number
  score_got?: number
  ability_dimension?: string | null
  difficulty_bucket?: string
  kp_name?: string
  kp_description?: string | null
  category_1?: string
  category_2?: string
  content_preview?: string
  error_links?: string[]
  ability_gap?: string
  reason?: string
}

export type AbilityAssessment = {
  version?: string
  status?: string
  overall?: {
    summary?: string
    strengths?: string[]
    weaknesses?: string[]
    progress_comment?: string
    progress?: {
      history?: Array<{
        paper_id: number
        title?: string | null
        earned_score: number
        total_score: number
        rate: number
        created_at?: string
      }>
      previous_score?: number | null
      score_delta?: number | null
      history_count?: number
    }
  }
  wrong_analysis?: {
    ability_distribution?: AssessmentAbilityDist[]
    difficulty_distribution?: AssessmentDiffDist[]
    knowledge_distribution?: AssessmentKpDist[]
    category_distribution?: AssessmentCatDist[]
    qualitative?: string
  }
  knowledge_items?: AssessmentKnowledgeItem[]
  ability_overview?: Array<{
    dimension: string
    attempted: number
    correct: number
    wrong: number
    accuracy: number
  }>
  llm_used?: boolean
  error?: string
}

export type PaperResultDetail = {
  paper_id: number
  goal_id: number
  title?: string | null
  status: string
  earned_score?: number | null
  total_score: number
  answered_count: number
  correct_count: number
  total_count: number
  items: QuestionResultItem[]
  assessment_status?: string | null
  assessment?: AbilityAssessment | null
}

export type WrongQuestionItem = {
  id: string
  source_type: 'assessment' | 'practice'
  question_id: number
  paper_id?: number | null
  paper_title?: string | null
  path_id?: number | null
  kp_id?: string | null
  seq?: number | null
  question_type: string
  content: string
  options?: unknown
  user_answer?: string | null
  correct_answer?: string | null
  analysis?: string | null
  source_exam_paper_id?: number | null
  difficulty?: number | null
  created_at?: string | null
  generated_exercises: Array<AiExercise & {
    user_answer?: string | null
    is_correct?: boolean | null
    correct_answer?: string | null
    analysis?: string | null
    created_at?: string | null
  }>
}

export type WrongQuestionList = {
  total: number
  assessment_count: number
  practice_count: number
  items: WrongQuestionItem[]
}

export type AiExercise = {
  id: number
  mode: 'similar' | 'deeper'
  question_type: string
  content: string
  options?: unknown
  difficulty: number
}

export type AiExerciseResult = AiExercise & {
  user_answer: string
  is_correct: boolean
  correct_answer: string
  analysis: string
}

export const testsApi = {
  preview: (goalId: number) =>
    api.get<AssemblePreview>('/tests/preview', { params: { goal_id: goalId } }),
  assemble: (data: AssemblePayload) => api.post<TestPaperDetail>('/tests/assemble', data),
  list: (goalId?: number) =>
    api.get<TestPaperSummary[]>('/tests', { params: goalId ? { goal_id: goalId } : {} }),
  get: (paperId: number) => api.get<TestPaperDetail>(`/tests/${paperId}`),
  delete: (paperId: number) => api.delete<{ ok: boolean }>(`/tests/${paperId}`),
  start: (paperId: number) => api.post<TakingSession>(`/tests/${paperId}/start`),
  taking: (paperId: number) => api.get<TakingSession>(`/tests/${paperId}/taking`),
  saveAnswer: (paperId: number, questionId: number, data: AnswerPayload) =>
    api.put<AnswerPublic>(`/tests/${paperId}/answers/${questionId}`, data),
  saveProgress: (
    paperId: number,
    answers: Array<AnswerPayload & { test_question_id: number }>,
  ) => api.post<TakingSession>(`/tests/${paperId}/save`, { answers }),
  submit: (paperId: number) => api.post<SubmitResult>(`/tests/${paperId}/submit`),
  result: (paperId: number) => api.get<PaperResultDetail>(`/tests/${paperId}/result`),
  wrongQuestions: () => api.get<WrongQuestionList>('/tests/wrong-questions'),
  generateWrongQuestionExercise: (
    sourceType: 'assessment' | 'practice',
    questionId: number,
    mode: 'similar' | 'deeper',
  ) => api.post<AiExercise>(
    '/tests/wrong-questions/generate',
    { source_type: sourceType, question_id: questionId, mode },
    { timeout: 130000 },
  ),
  submitWrongQuestionExercise: (exerciseId: number, answer: string) =>
    api.post<AiExerciseResult>(
      `/tests/wrong-questions/exercises/${exerciseId}/submit`,
      { answer },
    ),
}

export const TYPE_LABELS: Record<string, string> = {
  choice: '选择题',
  fill: '填空题',
  answer: '解答题',
  proof: '证明题',
}

export const BANK_LABELS: Record<string, string> = {
  real: '真题',
  mock: '模拟题',
}

/** 学生端历史组卷展示态：未测试 / 测试中 / 已测试 */
export const STATUS_LABELS: Record<string, string> = {
  assembled: '未测试',
  in_progress: '测试中',
  submitted: '已测试',
  grading: '已测试',
  graded: '已测试',
}

export function isPaperTested(status?: string | null) {
  return status === 'submitted' || status === 'grading' || status === 'graded'
}

export function isPaperTesting(status?: string | null) {
  return status === 'in_progress'
}
