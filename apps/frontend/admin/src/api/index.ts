import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

export type AnalyticsCurvePoint = {
  label: string
  value: number | null
  sample_size: number
}

export type AnalyticsParameter = {
  key: string
  name: string
  description: string
  unit: string
  status: 'ready' | 'limited' | 'unavailable'
  sample_size: number
  curve: AnalyticsCurvePoint[]
  note?: string | null
}

export type LearningAnalyticsResult = {
  scope: 'population' | 'student'
  generated_at: string
  student?: { id: number; name: string; email?: string | null }
  knowledge_scope?: {
    domain?: string | null
    category_1?: string | null
    category_2?: string | null
    kp_id?: string | null
    kp_name?: string | null
    knowledge_point_count: number
  }
  summary: {
    student_count?: number
    goal_count?: number
    graded_paper_count: number
    answer_event_count: number
    course_session_count: number
    ready_parameter_count: number
  }
  parameters: AnalyticsParameter[]
}

export const analyticsApi = {
  getPopulation: (params?: KnowledgeScopeParams) =>
    api.get<LearningAnalyticsResult>('/analytics/population', { params }),
  getKnowledgeOptions: () =>
    api.get<KnowledgeDirectoryOptions>('/analytics/knowledge-options'),
  listStudents: () =>
    api.get<Array<{ id: number; name: string; email?: string | null }>>('/analytics/students'),
  getStudent: (userId: number, params?: KnowledgeScopeParams) =>
    api.get<LearningAnalyticsResult>(`/analytics/students/${userId}`, { params }),
  getMarginalValue: (userId: number, params?: KnowledgeScopeParams) =>
    api.get<MarginalValueAnalysisResult>('/analytics/marginal-value', {
      params: { user_id: userId, ...params },
    }),
  getDiagnosticPriority: (userId: number, params?: KnowledgeScopeParams) =>
    api.get<DiagnosticPriorityAnalysisResult>('/analytics/diagnostic-priority', {
      params: { user_id: userId, ...params },
    }),
  getTargetedPractice: (
    userId: number,
    questionCount: number,
    params?: KnowledgeScopeParams,
  ) =>
    api.get<TargetedPracticeAnalysisResult>('/analytics/targeted-practice', {
      params: { user_id: userId, question_count: questionCount, ...params },
    }),
}

export type KnowledgeScopeParams = {
  domain?: string
  category_1?: string
  category_2?: string
  kp_id?: string
}

export type KnowledgeDirectoryOptions = {
  domains: Array<{ value: string; label: string }>
  categories_1: Array<{ domain: string; value: string; label: string }>
  categories_2: Array<{
    domain: string
    category_1: string
    value: string
    label: string
  }>
  knowledge_points: Array<{
    domain?: string | null
    category_1?: string | null
    category_2?: string | null
    value: string
    label: string
  }>
}

export type MarginalMetric = {
  key: string
  name: string
  unit: string
  sample_size: number
  curve: AnalyticsCurvePoint[]
}

export type MarginalValueAnalysisResult = {
  generated_at: string
  student: { id: number; name: string }
  knowledge_scope: LearningAnalyticsResult['knowledge_scope']
  path: null | {
    id: number
    version: number
    status: string
    algorithm_version: string
    daily_study_minutes?: number | null
    goal_snapshot?: Record<string, unknown>
  }
  summary: {
    node_count: number
    average_marginal_value?: number | null
    total_expected_gain?: number
    total_estimated_minutes?: number
    history_answer_count?: number
    duration_sample_count?: number
    mastery_change_sample_count?: number
    knowledge_relation_count?: number
  }
  metrics: MarginalMetric[]
  supporting_statistics?: {
    learnability: {
      formula: string
      note: string
      success_by_prior_mastery: AnalyticsCurvePoint[]
      model_inputs: AnalyticsCurvePoint[]
    }
    estimated_minutes: {
      formula: string
      note: string
      duration_by_prior_mastery: AnalyticsCurvePoint[]
      model_inputs: AnalyticsCurvePoint[]
    }
  }
  estimation_evidence?: Array<{
    key: 'direct_gain' | 'unlock_gain' | 'estimated_minutes'
    name: string
    symbol: string
    unit: string
    current_mean?: number | null
    status: 'ready' | 'limited' | 'unavailable'
    sample_size: number
    sample_label: string
    estimation_type: string
    formula: string
    history_inputs: string[]
    model_inputs: string[]
    snapshot_note: string
  }>
}

export type DiagnosticPriorityAnalysisResult = {
  generated_at: string
  student: { id: number; name: string }
  knowledge_scope: LearningAnalyticsResult['knowledge_scope']
  path: null | {
    id: number
    version: number
    status: string
    algorithm_version: string
    goal_id: number
  }
  summary: {
    candidate_count: number
    total_recommended_questions?: number
    total_estimated_minutes?: number
    highest_priority_kp?: string | null
    missing_weight_count?: number
    sufficient_confidence_count?: number
    warnings?: string[]
  }
  metrics: MarginalMetric[]
}

export type TargetedPracticeAnalysisResult = {
  generated_at: string
  student: { id: number; name: string }
  knowledge_scope: LearningAnalyticsResult['knowledge_scope']
  path: null | {
    id: number
    version: number
    status: string
    algorithm_version: string
    goal_id: number
  }
  summary: {
    knowledge_point_count: number
    question_count_per_kp?: number
    planned_question_count?: number
    selected_question_count?: number
    mock_selected_count?: number
    ai_selected_count?: number
    real_selected_count?: number
    history_answer_count?: number
    template_covered_count?: number
    average_template_question_count?: number | null
    average_observed_accuracy?: number | null
    average_ability_estimate?: number | null
    average_predicted_target_success?: number | null
    average_target_difficulty?: number | null
    unique_selected_count?: number
    repeated_selected_count?: number
    warnings?: string[]
  }
  metrics: MarginalMetric[]
  type_distribution: Array<{
    key: 'choice' | 'fill' | 'short_answer'
    label: string
    template_question_count: number
    template_weight: number
    planned_count: number
    selected_count: number
  }>
  difficulty_distribution: Array<{
    difficulty: number
    observed_accuracy?: number | null
    observed_sample_size: number
    predicted_success?: number | null
    planned_count: number
    selected_count: number
  }>
  bank_distribution: Array<{
    key: 'mock' | 'ai' | 'real'
    label: string
    candidate_count: number
    selected_count: number
  }>
}

// 知识点相关
export const knowledgeApi = {
  listPoints: (params: any) => api.get('/knowledge/points', { params }),
  getPoint: (id: string) => api.get(`/knowledge/points/${id}`),
  createPoint: (data: any) => api.post('/knowledge/points', data),
  updatePoint: (id: string, data: any) => api.put(`/knowledge/points/${id}`, data),
  updatePointPrerequisites: (id: string, prerequisiteIds: string[]) =>
    api.put(`/knowledge/points/${id}/prerequisites`, {
      prerequisite_ids: prerequisiteIds,
    }),
  deletePoint: (id: string) => api.delete(`/knowledge/points/${id}`),
  clearAll: () => api.delete('/knowledge/points/clear-all'),
  annotateChapters: (data: { textbook_file_ids: number[]; mode: string }) => api.post('/knowledge/annotate-chapters', data),
  listRelations: (params?: any) => api.get('/knowledge/relations', { params }),
  createRelation: (data: any) => api.post('/knowledge/relations', data),
  deleteRelation: (id: number) => api.delete(`/knowledge/relations/${id}`),
  clearAllRelations: () => api.delete('/knowledge/relations/clear-all'),
  syncRelationPrerequisites: () => api.post('/knowledge/relations/sync-prerequisites'),
  getStats: () => api.get('/knowledge/stats'),
  generateShortNames: (data: { mode: string; domain?: string; grade?: string }) =>
    api.post('/knowledge/points/generate-short-names', data),
  getShortNameProgress: (taskKey: string) =>
    api.get(`/knowledge/points/generate-short-names/progress/${taskKey}`),
  generatePrerequisites: (data: { point_ids?: string[] }) =>
    api.post('/knowledge/points/generate-prerequisites', data),
  getPrerequisiteProgress: (taskKey: string) =>
    api.get(`/knowledge/points/generate-prerequisites/progress/${taskKey}`),
}

// 文件相关
export const fileApi = {
  upload: (formData: FormData) => api.post('/files/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),
  list: (fileType?: string) => api.get('/files/list', { params: { file_type: fileType } }),
  updateType: (id: number, fileType: 'curriculum' | 'textbook') => {
    const formData = new FormData()
    formData.append('file_type', fileType)
    return api.put(`/files/${id}/type`, formData)
  },
  delete: (id: number) => api.delete(`/files/${id}`),
}

// 系统配置
export const systemApi = {
  getConfigs: () => api.get('/system/configs'),
  updateConfig: (key: string, data: { value: string; description?: string }) =>
    api.put(`/system/configs/${key}`, data),
  getLLMConfig: () => api.get('/system/llm-config'),
}

// 知识抽取
export const extractionApi = {
  start: (data: { task_type: string; source_file_ids?: number[]; config?: any }) =>
    api.post('/extraction/start', data),
  listTasks: () => api.get('/extraction/tasks'),
  getTask: (id: number) => api.get(`/extraction/tasks/${id}`),
  deleteTask: (id: number) => api.delete(`/extraction/tasks/${id}`),
}

// 题库管理
export const questionApi = {
  // 试卷
  uploadPaper: (formData: FormData) => api.post('/questions/papers/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  }),
  listPapers: (params?: any) => api.get('/questions/papers', { params }),
  updatePaper: (id: number, data: {
    title?: string
    paper_type?: string
    grade?: string
    year?: string
    region?: string
    subject?: string
  }) => api.put(`/questions/papers/${id}`, data),
  deletePaper: (id: number) => api.delete(`/questions/papers/${id}`),
  reparsePaper: (id: number) => api.post(`/questions/papers/${id}/reparse`),
  clearAll: (bankType?: 'real' | 'mock') =>
    api.delete('/questions/clear-all', { params: bankType ? { bank_type: bankType } : undefined }),
  // 题目
  listQuestions: (params?: any) => api.get('/questions/list', { params }),
  getQuestion: (id: number) => api.get(`/questions/${id}`),
  createQuestion: (data: any) => api.post('/questions/', data),
  updateQuestion: (id: number, data: any) => api.put(`/questions/${id}`, data),
  deleteQuestion: (id: number) => api.delete(`/questions/${id}`),
  batchDeleteQuestions: (data: { question_ids: number[] }) =>
    api.post('/questions/batch-delete', data),
  // 智能关联主知识点
  startKpLink: (data: {
    exam_paper_id?: number
    only_unlinked?: boolean
    question_ids?: number[]
    bank_type?: 'real' | 'mock'
  }) => api.post('/questions/kp-link/start', data),
  getKpLinkTask: (id: number) => api.get(`/questions/kp-link/tasks/${id}`),
  listKpLinkSuggestions: (params?: { task_id?: number; status?: string }) =>
    api.get('/questions/kp-link/suggestions', { params }),
  confirmKpLink: (data: { items: Array<{ suggestion_id: number; action: string; kp_id?: string }> }) =>
    api.post('/questions/kp-link/confirm', data),
  batchSetPrimaryKp: (data: { question_ids: number[]; primary_kp_id: string }) =>
    api.post('/questions/batch-set-primary-kp', data),
  /** 启动图片答案转文本任务（仅生成待确认建议） */
  startAnswerRewrite: (data: {
    question_ids?: number[]
    exam_paper_id?: number
    bank_type?: 'real' | 'mock'
  }) => api.post('/questions/answer-rewrite/start', data),
  getAnswerRewriteTask: (id: number) => api.get(`/questions/answer-rewrite/tasks/${id}`),
  listAnswerRewriteSuggestions: (params?: { task_id?: number; status?: string }) =>
    api.get('/questions/answer-rewrite/suggestions', { params }),
  confirmAnswerRewrite: (data: {
    items: Array<{ suggestion_id: number; action: string }>
  }) => api.post('/questions/answer-rewrite/confirm', data),
  /** 能力维度 AI 批量标注 */
  startAbilityLabel: (data: {
    question_ids?: number[]
    exam_paper_id?: number
    bank_type?: 'real' | 'mock'
    only_unlabeled?: boolean
  }) => api.post('/questions/ability-label/start', data),
  getAbilityLabelTask: (id: number) => api.get(`/questions/ability-label/tasks/${id}`),
  listAbilityLabelSuggestions: (params?: { task_id?: number; status?: string }) =>
    api.get('/questions/ability-label/suggestions', { params }),
  confirmAbilityLabel: (data: {
    items: Array<{ suggestion_id: number; action: string; ability_dimension?: string }>
  }) => api.post('/questions/ability-label/confirm', data),
  /** @deprecated 兼容旧入口，后端已改为启动待确认任务 */
  batchRewriteImageAnswers: (data: {
    question_ids?: number[]
    exam_paper_id?: number
    bank_type?: 'real' | 'mock'
    dry_run?: boolean
  }) => api.post('/questions/batch-rewrite-image-answers', data),
  // 分值方案 / 结构模板
  listScoreSchemes: () => api.get('/questions/score-schemes'),
  applyScoreScheme: (paperId: number, data?: { scheme_id?: number; overwrite?: boolean }) =>
    api.post(`/questions/papers/${paperId}/apply-score-scheme`, data || {}),
  buildTemplate: (paperId: number, data?: { scheme_id?: number }) =>
    api.post(`/questions/papers/${paperId}/build-template`, data || {}),
  buildTemplateFromPapers: (data: { paper_ids: number[]; scheme_id?: number }) =>
    api.post('/questions/templates/build', data),
  listTemplates: (params?: { subject?: string; region?: string }) =>
    api.get('/questions/templates', { params }),
  getTemplateBySource: (paperIds: number[]) =>
    api.get('/questions/templates/by-source', {
      params: { paper_ids: paperIds.slice().sort((a, b) => a - b).join(',') },
    }),
  getLatestAverageTemplate: () => api.get('/questions/templates/latest-average'),
  getTemplate: (id: number) => api.get(`/questions/templates/${id}`),
  setDefaultTemplate: (id: number) => api.post(`/questions/templates/${id}/set-default`),
  unsetDefaultTemplate: (id: number) => api.post(`/questions/templates/${id}/unset-default`),
  deleteTemplate: (id: number) => api.delete(`/questions/templates/${id}`),
  /** AI 出题 */
  aiGenerate: (data: {
    kp_id: string
    question_type?: string
    count?: number
    sample_ids?: number[]
    difficulty?: number
  }) => api.post('/questions/ai-generate', data, { timeout: 120000 }),
}

// 章节目录
export const chapterApi = {
  listTrees: (params?: { grade?: string; uploaded_file_id?: number }) =>
    api.get('/chapters/trees', { params }),
  updateChapter: (id: number, data: { title?: string; sort_order?: number; status?: string }) =>
    api.put(`/chapters/${id}`, data),
  deleteChapter: (id: number) => api.delete(`/chapters/${id}`),
  clearAll: () => api.delete('/chapters/clear-all'),
  listRelatedKnowledgePoints: (id: number) => api.get(`/chapters/${id}/knowledge-points`),
  reorder: (items: Array<{ id: number; sort_order: number }>) =>
    api.post('/chapters/reorder', items),
  extractSummaries: (uploadedFileId: number) =>
    api.post(`/chapters/extract-summaries/${uploadedFileId}`, {}, { timeout: 30000 }),
  getSummaryTaskStatus: (taskId: number) =>
    api.get(`/chapters/extract-summaries/task/${taskId}`),
  getActiveSummaryTask: (uploadedFileId: number) =>
    api.get(`/chapters/extract-summaries/active/${uploadedFileId}`),
}

// 课程与资源管理
export const resourceApi = {
  generateExplanation: (data: { kp_id: string; difficulty_level?: string }) =>
    api.post('/resources/ai-explanation/generate', data, { timeout: 120000 }),
  saveExplanation: (data: any) => api.post('/resources/ai-explanation/save', data),
  listExplanations: (params: { kp_id: string; page?: number; page_size?: number }) =>
    api.get('/resources/ai-explanation/list', { params }),
  getExplanation: (id: number) => api.get(`/resources/ai-explanation/${id}`),
  deleteExplanation: (id: number) => api.delete(`/resources/ai-explanation/${id}`),
}

export default api
