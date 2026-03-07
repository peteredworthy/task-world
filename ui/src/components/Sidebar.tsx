import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAgents } from "../hooks/useApi";
import { AgentQuotaBadge } from "./AgentQuotaBadge";
import type { AgentOption, QuotaBucket } from '../types/agents';

const navItems = [
  { icon: '▣', label: 'Dashboard', path: '/' },
  { icon: '📁', label: 'Repositories', path: '/repos' },
  { icon: '🤖', label: 'Agents', path: '/agents' },
  { icon: '📋', label: 'Routine Library', path: '/routines' },
  { icon: '⏱', label: 'History', path: '/history' },
];

function formatReset(isoStr: string): string {
  try {
    const d = new Date(isoStr);
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  } catch {
    return '';
  }
}

function bucketValueClass(bucket: QuotaBucket): string {
  if (bucket.remaining_pct != null) {
    if (bucket.remaining_pct >= 50) return 'text-green-600';
    if (bucket.remaining_pct >= 20) return 'text-amber-600';
    return 'text-red-600';
  }
  if (bucket.remaining_usd != null && bucket.remaining_usd < 0) return 'text-red-600';
  return 'text-text-secondary';
}

function bucketBarClass(pct: number): string {
  if (pct >= 50) return 'bg-green-500';
  if (pct >= 20) return 'bg-amber-500';
  return 'bg-red-500';
}

function formatBucketValue(bucket: QuotaBucket): string {
  if (bucket.remaining_pct != null) {
    return `${Math.round(bucket.remaining_pct)}%`;
  }
  if (bucket.remaining_usd != null) {
    if (bucket.remaining_usd < 0) return `-$${Math.abs(bucket.remaining_usd).toFixed(2)} over limit`;
    return `$${bucket.remaining_usd.toFixed(2)}`;
  }
  return '';
}

function formatStaleness(isoStr: string | null | undefined): string | null {
  if (!isoStr) return null;
  try {
    const fetchedMs = new Date(isoStr).getTime();
    const ageMs = Date.now() - fetchedMs;
    if (ageMs < 90_000) return null; // <90s → not stale
    const mins = Math.round(ageMs / 60_000);
    if (mins < 60) return `updated ${mins}m ago`;
    const hrs = Math.round(mins / 60);
    return `updated ${hrs}h ago`;
  } catch {
    return null;
  }
}

interface AgentQuotaRowProps {
  agent: AgentOption;
}

function AgentQuotaRow({ agent }: AgentQuotaRowProps) {
  const [expanded, setExpanded] = useState(false);
  const hasBreakdown = (agent.quota?.breakdown?.length ?? 0) > 0;
  const staleness = formatStaleness(agent.quota?.fetched_at);

  return (
    <div>
      <button
        onClick={() => hasBreakdown && setExpanded(e => !e)}
        className={`w-full flex items-center justify-between py-1 px-1.5 rounded transition-colors ${hasBreakdown ? 'hover:bg-bg-hover cursor-pointer' : 'cursor-default'}`}
        aria-expanded={hasBreakdown ? expanded : undefined}
      >
        <div className="flex flex-col items-start min-w-0 mr-2">
          <span className="text-text-secondary text-[12px] truncate max-w-full">{agent.name}</span>
          {staleness && <span className="text-text-muted text-[10px]">{staleness}</span>}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <AgentQuotaBadge quota={agent.quota!} />
          {hasBreakdown && (
            <svg
              className={`w-3 h-3 text-text-muted transition-transform duration-150 ${expanded ? 'rotate-180' : ''}`}
              viewBox="0 0 12 12"
              fill="none"
              stroke="currentColor"
              aria-hidden="true"
            >
              <path d="M2 4L6 8L10 4" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </div>
      </button>

      {expanded && hasBreakdown && (
        <div className="mt-1 mb-1 pl-1.5 pr-0.5 space-y-2.5">
          {agent.quota!.breakdown!.map((bucket) => (
            <div key={bucket.label}>
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-text-muted text-[11px]">{bucket.label}</span>
                <span className={`text-[11px] font-medium ${bucketValueClass(bucket)}`}>
                  {formatBucketValue(bucket)}
                </span>
              </div>
              {bucket.remaining_pct != null && (
                <div className="h-1 rounded-full bg-bg-hover overflow-hidden">
                  <div
                    className={`h-full rounded-full ${bucketBarClass(bucket.remaining_pct)}`}
                    style={{ width: `${Math.min(100, Math.max(0, bucket.remaining_pct))}%` }}
                  />
                </div>
              )}
              {bucket.resets_at && (
                <div className="text-text-muted text-[10px] mt-0.5">
                  resets {formatReset(bucket.resets_at)}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function Sidebar() {
  const location = useLocation();
  const { data: agents, isLoading: agentsLoading, error: agentsError } = useAgents();
  const quotaAgents = (agents ?? []).filter(a => a.available && a.quota !== null);

  return (
    <aside className="hidden md:flex w-[220px] bg-bg-primary border-r border-border flex-col shrink-0 h-screen sticky top-0 overflow-y-auto">
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
        <div className="px-3 pb-4">
          <div className="text-text-muted text-[11px] uppercase tracking-wide mb-1 px-1.5">Agent Quotas</div>
          {quotaAgents.map((agent) => (
            <AgentQuotaRow key={agent.agent_type} agent={agent} />
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
