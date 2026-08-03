import { api } from './client'

export type Readiness = {
  ready_for_diagnostic: boolean
  chapter_count: number
  published_knowledge_point_count: number
  real_question_total: number
  real_question_linked: number
  link_rate: number
  has_default_template: boolean
  reasons: string[]
  message: string
}

export type ChapterNode = {
  id: number
  title: string
  level: string
  grade?: string | null
  semester?: string | null
  sort_order: number
  kp_count?: number
  children: ChapterNode[]
}

export type ChapterTree = {
  uploaded_file_id: number
  filename: string
  grade?: string | null
  semester?: string | null
  nodes: ChapterNode[]
}

export const assetsApi = {
  readiness: () => api.get<Readiness>('/assets/readiness'),
  /** grade_stage 如「九年级下」，只返回对应年级学期教材目录 */
  chapters: (gradeStage?: string) =>
    api.get<ChapterTree[]>('/assets/chapters', {
      params: gradeStage ? { grade_stage: gradeStage } : undefined,
    }),
  summary: () =>
    api.get<{ parsed_papers: number; readiness: Readiness }>('/assets/summary'),
}
