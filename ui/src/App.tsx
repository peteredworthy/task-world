import { Navigate, Route, Routes, useLocation, useParams } from 'react-router-dom';
import { Layout } from './components/Layout';
import { CreateRunProvider } from './context/CreateRunContext';
import { SettingsProvider } from './context/SettingsContext';
import { SettingsModal } from './components/SettingsModal';
import { Dashboard } from './pages/Dashboard';
import { NotFound } from './pages/NotFound';
import { RunDetail } from './components/dashboard/RunDetail';
import { RoutineLibrary } from './pages/RoutineLibrary';
import { AgentRunners } from './pages/AgentRunners';
import { Agents } from './pages/Agents';
import { History } from './pages/History';
import { Repos } from './pages/Repos';

function RunDetailRedirect() {
  const { runId } = useParams<{ runId: string }>();
  const location = useLocation();
  return <Navigate to={`/runs/${runId}/history${location.search}`} replace />;
}

export default function App() {
  return (
    <CreateRunProvider>
      <SettingsProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/runs/:runId" element={<RunDetailRedirect />} />
            <Route path="/runs/:runId/history" element={<RunDetail page="history" />} />
            <Route path="/runs/:runId/changes" element={<RunDetail page="changes" />} />
            <Route path="/routines" element={<RoutineLibrary />} />
            <Route path="/agent-runners" element={<AgentRunners />} />
            <Route path="/agents" element={<Agents />} />
            <Route path="/history" element={<History />} />
            <Route path="/repos" element={<Repos />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
        <SettingsModal />
      </SettingsProvider>
    </CreateRunProvider>
  );
}
