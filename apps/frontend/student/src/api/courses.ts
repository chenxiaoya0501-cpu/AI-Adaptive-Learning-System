import { api } from './client'
import type { ExplanationContentBlock } from '../components/ExplanationBlocks'

export interface CourseSummary {
  path_id: number
  goal_id: number
  goal_title: string
  kp_id: string
  kp_name: string
  node_id: number
  stage_index: number
  estimated_minutes: number
  status: string
  available: boolean
}

export interface CourseQuestion {
  id: number
  question_type: string
  content: string
  options?: Record<string, string> | string[]
  difficulty: number
  source?: string
  bank_type: string
  images?: string[]
}

export interface Course {
  path_id: number
  goal_id: number
  node_id: number
  kp_id: string
  kp_name: string
  stage_index: number
  role: string
  current_mastery?: number
  target_mastery: number
  estimated_minutes: number
  objectives: string[]
  explanation: {
    id?: number
    title: string
    summary?: string
    content: string
    content_blocks: ExplanationContentBlock[]
    key_points: string[]
    examples: Array<{ problem?: string; solution?: string; explanation?: string }>
    common_mistakes: string[]
    difficulty_level: string
    source: string
  }
  external_resources: Array<{
    title: string
    url: string
    platform: string
    resource_type: string
    note?: string
  }>
  questions: CourseQuestion[]
  progress: {
    node_status: string
    tasks: Record<string, string>
    evaluation?: MasteryEvaluation
    answered_question_ids?: number[]
    mastery_sync?: MasterySyncInfo
  }
  warnings: string[]
}

export interface MasteryEvaluation {
  mastery_score: number
  target_mastery: number
  achieved: boolean
  evidence_sufficient: boolean
  answered_count: number
  correct_count: number
  accuracy?: number
  weighted_accuracy: number
  confidence: number
  confidence_level: 'low' | 'medium' | 'high'
  prior_mastery?: number
  minimum_pass_questions: number
  recommended_questions: number
  recommendation: string
  difficulty_breakdown: Record<string, { answered: number; correct: number }>
  rule_version: string
}

export interface MasterySyncInfo {
  mastery_score: number
  confidence: number
  achieved: boolean
  synced_at: string
}

export interface CourseCompleteResult {
  path_id: number
  node_id: number
  kp_id: string
  answered_count: number
  correct_count: number
  accuracy?: number
  completed: boolean
  task_statuses: Record<string, string>
  question_results: Array<{
    question_id: number
    is_correct: boolean
    correct_answer?: string
    analysis?: string
    difficulty: number
    bank_type: string
  }>
  evaluation: MasteryEvaluation
}

export interface CourseTutorTurn {
  role: 'user' | 'assistant'
  content: string
}

export interface CourseTutorResponse {
  answer: string
  suggested_questions: string[]
}

export const coursesApi = {
  list: async () => (await api.get<CourseSummary[]>('/courses')).data,
  get: async (pathId: number, kpId: string) =>
    (await api.get<Course>(`/courses/${pathId}/${encodeURIComponent(kpId)}`)).data,
  complete: async (
    pathId: number,
    kpId: string,
    data: {
      explanation_completed: boolean
      answers: Array<{ question_id: number; selected_option?: string; answer_text?: string }>
    },
  ) => (
    await api.post<CourseCompleteResult>(
      `/courses/${pathId}/${encodeURIComponent(kpId)}/complete`,
      data,
    )
  ).data,
  syncMastery: async (pathId: number, kpId: string) => (
    await api.post<MasterySyncInfo & { path_id: number; goal_id: number; kp_id: string }>(
      `/courses/${pathId}/${encodeURIComponent(kpId)}/sync-mastery`,
    )
  ).data,
  askTutor: async (
    pathId: number,
    kpId: string,
    data: { question: string; history: CourseTutorTurn[] },
  ) => (
    await api.post<CourseTutorResponse>(
      `/courses/${pathId}/${encodeURIComponent(kpId)}/tutor`,
      data,
      { timeout: 130000 },
    )
  ).data,
}
