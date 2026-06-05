import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Competitions from './pages/Competitions'
import CompetitionDetail from './pages/CompetitionDetail'
import Solve from './pages/Solve'
import ActivityPage from './pages/ActivityPage'
import Knowledge from './pages/Knowledge'
import McpManager from './pages/McpManager'
import Settings from './pages/Settings'
import PromptManager from './pages/PromptManager'
import Skills from './pages/Skills'
import IdeasPage from './pages/IdeasPage'
import Memories from './pages/Memories'
import TagManager from './pages/TagManager'
import AuditProjects from './pages/AuditProjects'
import AuditTask from './pages/AuditTask'
import AuditDashboard from './pages/AuditDashboard'
import PentestTargets from './pages/PentestTargets'
import PentestTask from './pages/PentestTask'
import PentestDashboard from './pages/PentestDashboard'
import PentestDiverge from './pages/PentestDiverge'
import InspectionDashboard from './pages/InspectionDashboard'
import InspectionHosts from './pages/InspectionHosts'
import InspectionResults from './pages/InspectionResults'
import SolveRecords from './pages/SolveRecords'
import AgentArena from './pages/AgentArena'
import ReverseLab from './pages/ReverseLab'
import Onboarding from './pages/Onboarding'
import TitleBar from './components/TitleBar'
import { useSettingsStore } from './stores/settingsStore'
import { getModeHomePath } from './utils/modeRoutes'

export default function App() {
  const agentMode = useSettingsStore((s) => s.agentMode)

  return (
    <div className="flex flex-col h-full">
      <TitleBar />
      <div className="flex-1 overflow-hidden">
        <Routes>
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="/" element={<Layout />}>
            <Route index element={<Navigate to={getModeHomePath(agentMode)} replace />} />
            {/* CTF mode */}
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="competitions" element={<Competitions />} />
            <Route path="competitions/:competitionId" element={<CompetitionDetail />} />
            <Route path="challenges" element={<Navigate to="/competitions" replace />} />
            <Route path="solve/:challengeId" element={<Solve />} />
            <Route path="agent-arena" element={<AgentArena />} />
            {/* Audit mode */}
            <Route path="audit/dashboard" element={<AuditDashboard />} />
            <Route path="audit/projects" element={<AuditProjects />} />
            <Route path="audit/task/:projectId" element={<AuditTask />} />
            {/* Pentest mode */}
            <Route path="pentest/dashboard" element={<PentestDashboard />} />
            <Route path="pentest/targets" element={<PentestTargets />} />
            <Route path="pentest/task/:targetId" element={<PentestTask />} />
            <Route path="pentest/diverge/:findingId" element={<PentestDiverge />} />
            {/* Inspection mode */}
            <Route path="inspection/dashboard" element={<InspectionDashboard />} />
            <Route path="inspection/hosts" element={<InspectionHosts />} />
            <Route path="inspection/results/:hostId" element={<InspectionResults />} />
            {/* Common — shared across all modes */}
            <Route path="activity" element={<ActivityPage />} />
            <Route path="solve-records" element={<SolveRecords />} />
            <Route path="ideas" element={<IdeasPage />} />
            <Route path="prompts" element={<PromptManager />} />
            <Route path="knowledge" element={<Knowledge />} />
            <Route path="skills" element={<Skills />} />
            <Route path="memories" element={<Memories />} />
            <Route path="tags" element={<TagManager />} />
            <Route path="reverse-lab" element={<ReverseLab />} />
            <Route path="mcp" element={<McpManager />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </div>
    </div>
  )
}
