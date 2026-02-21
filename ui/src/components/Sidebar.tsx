import { Link, useLocation } from 'react-router-dom';
import { useAgents } from "../hooks/useApi";
import { AgentQuotaBadge } from "./AgentQuotaBadge";

const navItems = [
  { icon: '▣', label: 'Dashboard', path: '/' },
  { icon: '📁', label: 'Repositories', path: '/repos' },
  { icon: '🤖', label: 'Agents', path: '/agents' },
  { icon: '📋', label: 'Routine Library', path: '/routines' },
  { icon: '⏱', label: 'History', path: '/history' },
];

export function Sidebar() {
  const location = useLocation();
  const { data: agents, isLoading: agentsLoading, error: agentsError } = useAgents();
  const quotaAgents = (agents ?? []).filter(a => a.available && a.quota !== null);

  return (
    <aside className="hidden md:flex w-[220px] bg-bg-primary border-r border-border flex-col shrink-0">
      {/* Logo */}
      <div className="px-3 pt-4 pb-6">
        <Link to="/" className="flex items-center gap-2 mb-1">
          <span className="flex items-center justify-center w-7 h-7 rounded-md bg-gradient-to-br from-accent-purple to-accent-cyan text-white text-xs font-bold">
            O
          </span>
          <span className="text-text-primary text-sm font-semibold">Orchestrator</span>
        </Link>
        <span className="text-text-muted text-[11px] ml-9">Mission Control</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2" role="navigation" aria-label="Main navigation">
        {navItems.map((item) => {
          const isActive = location.pathname === item.path;
          return (
            <Link
              key={item.label}
              to={item.path}
              className={`flex items-center gap-2.5 px-3 py-2.5 rounded-md mb-1 text-[13px] transition-colors ${
                isActive
                  ? 'bg-accent-purple/20 text-text-primary font-medium'
                  : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'
              }`}
              aria-current={isActive ? 'page' : undefined}
            >
              <span className="text-sm">{item.icon}</span>
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Agent Quotas */}
      {agentsLoading && (
        <div className="px-4 pb-4">
          <div className="h-3 w-24 rounded bg-bg-hover animate-pulse mb-2" />
          <div className="h-4 w-full rounded bg-bg-hover animate-pulse mb-1.5" />
          <div className="h-4 w-full rounded bg-bg-hover animate-pulse" />
        </div>
      )}
      {!agentsLoading && !agentsError && quotaAgents.length > 0 && (
        <div className="px-4 pb-4">
          <div className="text-text-muted text-[11px] uppercase tracking-wide mb-2">Agent Quotas</div>
          {quotaAgents.map((agent) => (
            <div key={agent.agent_type} className="flex items-center justify-between mb-1.5">
              <span className="text-text-secondary text-[12px] truncate mr-2">{agent.name}</span>
              <AgentQuotaBadge quota={agent.quota!} />
            </div>
          ))}
        </div>
      )}

      {/* Footer */}
      <div className="border-t border-border px-2 pt-3 pb-3">
        <div className="flex items-center gap-2.5 px-3 py-2.5">
          <div className="w-7 h-7 rounded-full bg-accent-purple flex items-center justify-center text-white text-xs font-semibold">
            D
          </div>
          <div>
            <div className="text-text-primary text-xs">DevUser</div>
            <div className="text-text-muted text-[10px]">Pro Plan</div>
          </div>
        </div>
      </div>
    </aside>
  );
}

/** Mobile bottom navigation bar, visible only below md breakpoint. */
export function MobileBottomNav() {
  const location = useLocation();

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-40 bg-bg-card border-t border-border flex items-center justify-around py-2 md:hidden"
      role="navigation"
      aria-label="Mobile navigation"
    >
      {navItems.map((item) => {
        const isActive = location.pathname === item.path;
        return (
          <Link
            key={item.label}
            to={item.path}
            className={`flex flex-col items-center gap-0.5 px-2 py-1 rounded-md text-[10px] transition-colors ${
              isActive
                ? 'text-accent-purple font-medium'
                : 'text-text-muted'
            }`}
            aria-current={isActive ? 'page' : undefined}
          >
            <span className="text-base">{item.icon}</span>
            <span>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
