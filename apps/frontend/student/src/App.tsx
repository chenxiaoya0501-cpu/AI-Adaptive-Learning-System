import { Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import RequireAuth from './auth/RequireAuth'
import StudentLayout from './layouts/StudentLayout'
import Login from './pages/Login'
import Register from './pages/Register'
import Home from './pages/Home'
import Me from './pages/Me'
import Placeholder from './pages/Placeholder'
import GoalList from './pages/goals/GoalList'
import GoalWizard from './pages/goals/GoalWizard'
import LearningMap from './pages/goals/LearningMap'
import PrimaryLearningMap from './pages/goals/PrimaryLearningMap'
import PrimaryLearningPath from './pages/goals/PrimaryLearningPath'
import LearningPath from './pages/goals/LearningPath'
import ExamHome from './pages/exam/ExamHome'
import Taking from './pages/exam/Taking'
import Result from './pages/exam/Result'
import Learn from './pages/learn/Learn'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <StudentLayout />
            </RequireAuth>
          }
        >
          <Route index element={<Home />} />
          <Route path="goals" element={<GoalList />} />
          <Route path="goals/new" element={<GoalWizard />} />
          <Route path="goals/:id/edit" element={<GoalWizard />} />
          <Route path="goals/:id/map" element={<LearningMap />} />
          <Route path="learning-map" element={<PrimaryLearningMap />} />
          <Route path="learning-map/:goalId" element={<LearningMap />} />
          <Route path="learning-path" element={<PrimaryLearningPath />} />
          <Route path="goals/:goalId/path" element={<LearningPath />} />
          <Route path="exam" element={<ExamHome />} />
          <Route path="exam/taking/:paperId" element={<Taking />} />
          <Route path="exam/result/:paperId" element={<Result />} />
          <Route
            path="report"
            element={<Placeholder title="报告" hint="第 5 / 8 步：当次报告与能力诊断（即将开发）" />}
          />
          <Route path="learn" element={<Learn />} />
          <Route path="learn/:pathId/:kpId" element={<Learn />} />
          <Route path="me" element={<Me />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  )
}
