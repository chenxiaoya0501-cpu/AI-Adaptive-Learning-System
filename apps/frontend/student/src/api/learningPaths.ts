import { api } from './client'

export type LearningPathNode = {
  id?: number
  kp_id: string
  name: string
  order_index: number
  stage_index: number
  stage_type: 'foundation' | 'core' | 'transfer' | 'review' | string
  role: 'prerequisite' | 'verify' | 'remediate' | 'strengthen' | 'review' | string
  current_mastery?: number | null
  target_mastery: number
  confidence: number
  exam_weight: number
  priority: number
  expected_gain: number
  estimated_minutes: number
  prerequisite_kp_ids: string[]
  reason: {
    summary?: string
    score_gap?: number
    stage_theme?: string
    direct_gain?: number
    optimistic_gain?: number
    base_direct_gain?: number
    base_target_mastery?: number
    reinforcement_gain?: number
    reinforcement_minutes?: number
    reinforcement_passes?: number
    reinforcement_blocks?: {
      pass_index: number
      from_mastery: number
      to_mastery: number
      estimated_minutes: number
      expected_gain: number
      optimistic_gain: number
    }[]
    unlock_gain?: number
    information_value?: number
    information_value_explanation?: string
    strategic_value?: number
    weight_source?: string
    admission_reason?: string[]
    [key: string]: unknown
  }
  status: string
}

export type LearningPathTask = {
  id?: number
  path_node_id?: number
  kp_id: string
  scheduled_date: string
  sequence: number
  task_type: string
  title: string
  instruction?: string
  estimated_minutes: number
  status: 'blocked' | 'pending' | 'in_progress' | 'completed' | 'skipped' | string
  result?: Record<string, unknown> | null
}

export type LearningPath = {
  id?: number
  goal_id: number
  version?: number
  status: 'preview' | 'draft' | 'current' | 'archived' | string
  algorithm_version: string
  generation_reason: string
  source_paper_ids: number[]
  summary: {
    current_score: number
    target_score: number
    score_gap: number
    expected_gain: number
    expected_gain_conservative?: number
    expected_gain_optimistic?: number
    planning_round?: number
    planning_scope?: 'first_pass' | string
    first_round_expected_gain_conservative?: number
    first_round_expected_gain_optimistic?: number
    first_round_completion_date?: string | null
    first_round_planned_days?: number
    insufficient_mastery_evidence_count?: number
    next_round_requires_reassessment?: boolean
    expected_score_range?: [number, number]
    target_feasibility?: 'reachable' | 'tight' | 'insufficient' | 'maintain'
    capacity_minutes?: number
    total_minutes: number
    unused_minutes?: number
    daily_study_minutes: number
    horizon_days: number
    knowledge_count: number
    task_count: number
    completed_task_count?: number
    progress_percent?: number
    deferred_count?: number
    deferred_nodes?: { kp_id: string; reason: string }[]
    deferred_reinforcement_count?: number
    deferred_reinforcement_minutes?: number
    suggested_daily_minutes?: number | null
    reinforcement_saturated?: boolean
    excluded_count?: number
    excluded_reason_counts?: Record<string, number>
    current_score_source?: string
    weight_source?: string
    is_stale?: boolean
    completed_at?: string | null
    warnings?: string[]
  }
  nodes: LearningPathNode[]
  tasks: LearningPathTask[]
  created_at?: string
}

export type PathGenerateOptions = {
  daily_study_minutes?: number
  start_date?: string
  horizon_days?: number
  generation_reason?: string
}

export const learningPathsApi = {
  get: (pathId: number) =>
    api.get<LearningPath>(`/learning-paths/${pathId}`),
  current: (goalId: number) =>
    api.get<LearningPath | null>(`/goals/${goalId}/learning-path/current`),
  preview: (goalId: number, options: PathGenerateOptions = {}) =>
    api.post<LearningPath>(`/goals/${goalId}/learning-path/preview`, options),
  generate: (goalId: number, options: PathGenerateOptions = {}) =>
    api.post<LearningPath>(`/goals/${goalId}/learning-path/generate`, options),
  activate: (pathId: number) =>
    api.post<LearningPath>(`/learning-paths/${pathId}/activate`),
  replan: (goalId: number, options: PathGenerateOptions = {}) =>
    api.post<LearningPath>(`/goals/${goalId}/learning-path/replan`, options),
  versions: (goalId: number) =>
    api.get<LearningPath[]>(`/goals/${goalId}/learning-paths`),
  updateTask: (
    taskId: number,
    payload: { status: 'pending' | 'in_progress' | 'completed' | 'skipped'; result?: Record<string, unknown> },
  ) => api.patch<LearningPath>(`/learning-tasks/${taskId}`, payload),
}
