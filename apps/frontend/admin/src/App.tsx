import { Routes, Route, Navigate } from 'react-router-dom'
import AdminLayout from './layouts/AdminLayout'
import Dashboard from './pages/Dashboard'
import KnowledgePoints from './pages/knowledge/KnowledgePoints'
import KnowledgeRelations from './pages/knowledge/KnowledgeRelations'
import FileUpload from './pages/knowledge/FileUpload'
import ExtractionTasks from './pages/knowledge/ExtractionTasks'
import ChapterCatalog from './pages/knowledge/ChapterCatalog'
import QuestionBank from './pages/questions/QuestionBank'
import AIGeneratedBank from './pages/questions/AIGeneratedBank'
import AIKnowledgeExplanation from './pages/resources/AIKnowledgeExplanation'
import SystemConfig from './pages/system/SystemConfig'
import LearningAnalytics from './pages/analytics/LearningAnalytics'
import MarginalValueAnalytics from './pages/analytics/MarginalValueAnalytics'
import DiagnosticPriorityAnalytics from './pages/analytics/DiagnosticPriorityAnalytics'
import TargetedPracticeAnalytics from './pages/analytics/TargetedPracticeAnalytics'

function App() {
  return (
    <Routes>
      <Route path="/" element={<AdminLayout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        {/* 知识图谱管理 */}
        <Route path="knowledge/points" element={<KnowledgePoints />} />
        <Route path="knowledge/relations" element={<KnowledgeRelations />} />
        <Route path="knowledge/files" element={<FileUpload />} />
        <Route path="knowledge/extraction" element={<ExtractionTasks />} />
        <Route path="knowledge/chapters" element={<ChapterCatalog />} />
        {/* 系统配置 */}
        <Route path="system/config" element={<SystemConfig />} />
        {/* 题库与试卷管理 */}
        <Route path="questions/papers" element={<QuestionBank key="papers" defaultTab="papers" />} />
        <Route path="questions/real" element={<QuestionBank key="real" defaultTab="real-questions" />} />
        <Route path="questions/mock" element={<QuestionBank key="mock" defaultTab="mock-questions" />} />
        <Route path="questions/ai-bank" element={<QuestionBank key="ai" defaultTab="ai-questions" />} />
        <Route path="questions/ai-generated" element={<AIGeneratedBank />} />
        {/* 课程与资源管理 */}
        <Route path="resources/ai-explanation" element={<AIKnowledgeExplanation />} />
        <Route path="review/*" element={<Placeholder title="生成内容审核与质检" />} />
        <Route path="analytics" element={<Navigate to="/analytics/population" replace />} />
        <Route path="analytics/population" element={<LearningAnalytics mode="population" />} />
        <Route path="analytics/personal" element={<LearningAnalytics mode="student" />} />
        <Route path="analytics/marginal-value" element={<MarginalValueAnalytics />} />
        <Route path="analytics/diagnostic-priority" element={<DiagnosticPriorityAnalytics />} />
        <Route path="analytics/targeted-practice" element={<TargetedPracticeAnalytics />} />
        <Route path="users/*" element={<Placeholder title="用户与权限管理" />} />
      </Route>
    </Routes>
  )
}

function Placeholder({ title }: { title: string }) {
  return (
    <div style={{ padding: 48, textAlign: 'center', color: '#999' }}>
      <h2>{title}</h2>
      <p style={{ marginTop: 16 }}>该模块尚未开发，敬请期待</p>
    </div>
  )
}

export default App
