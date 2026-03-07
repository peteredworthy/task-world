import { Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { CreateRunProvider } from './context/CreateRunContext';
import { SettingsProvider } from './context/SettingsContext';
import { SettingsModal } from './components/SettingsModal';
import { Dashboard } from './pages/Dashboard';
import { NotFound } from './pages/NotFound';
import { RunDetail } from './pages/RunDetail';
import { RoutineLibrary } from './pages/RoutineLibrary';
import { AgentRunners } from './pages/AgentRunners';
import { History } from './pages/History';
import { Repos } from './pages/Repos';

export default function App() {
  return (
    <CreateRunProvider>
      <SettingsProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/runs/:runId" element={<RunDetail />} />
            <Route path="/routines" element={<RoutineLibrary />} />
            <Route path="/agent-runners" element={<AgentRunners />} />
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
