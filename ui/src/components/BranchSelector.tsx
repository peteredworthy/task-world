import { useState, useEffect, useRef } from 'react';
import { useBranchCount, useBranches } from '../hooks/useApi';

interface BranchSelectorProps {
  repoName: string;
  value: string;
  onChange: (branch: string) => void;
  includeRemote?: boolean;
}

/**
 * BranchSelector - Text input with debounced branch matching
 *
 * Features:
 * - Debounced text input (300ms)
 * - Uses glob pattern filtering
 * - Shows dropdown when branch count <= 100
 * - Shows "refine pattern" message when 100+ branches
 * - Allows selecting from dropdown or typing custom branch
 */
export function BranchSelector({ repoName, value, onChange, includeRemote = false }: BranchSelectorProps) {
  const [inputValue, setInputValue] = useState(value);
  const [debouncedPattern, setDebouncedPattern] = useState(value);
  const [showDropdown, setShowDropdown] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Debounce the pattern used for API calls
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedPattern(inputValue);
    }, 300);

    return () => clearTimeout(timer);
  }, [inputValue]);

  // Build the glob pattern - if empty, match all; otherwise use as glob
  const pattern = debouncedPattern.trim() || '*';

  // Fetch branch count first
  const { data: countData } = useBranchCount(repoName, {
    pattern,
    include_remote: includeRemote
  });

  // Only fetch branches if count <= 100
  const shouldFetchBranches = countData && countData.count <= 100;
  const { data: branchesData } = useBranches(
    shouldFetchBranches ? repoName : undefined,
    { pattern, include_remote: includeRemote }
  );

  const branchCount = countData?.count ?? 0;
  const branches = branchesData?.branches ?? [];

  // Handle input change
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newValue = e.target.value;
    setInputValue(newValue);
    onChange(newValue);
    setShowDropdown(true);
  };

  // Handle branch selection from dropdown
  const handleBranchSelect = (branchName: string) => {
    setInputValue(branchName);
    onChange(branchName);
    setShowDropdown(false);
    inputRef.current?.focus();
  };

  // Handle click outside to close dropdown
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setShowDropdown(false);
      }
    }

    if (showDropdown) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [showDropdown]);

  // Show dropdown when focused if we have data
  const handleFocus = () => {
    if (branchCount > 0) {
      setShowDropdown(true);
    }
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <input
        ref={inputRef}
        type="text"
        placeholder="e.g. main or feature/*"
        value={inputValue}
        onChange={handleInputChange}
        onFocus={handleFocus}
        className="w-full rounded-md border border-border bg-bg-card px-3 py-2 text-sm text-text-primary shadow-sm placeholder:text-text-muted focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50"
      />

      {/* Dropdown for branch count <= 100 */}
      {showDropdown && branchCount > 0 && branchCount <= 100 && branches.length > 0 && (
        <div className="absolute z-10 mt-1 w-full rounded-md border border-border bg-bg-card shadow-lg max-h-60 overflow-y-auto">
          {branches.map((branch) => (
            <button
              key={branch.name}
              type="button"
              onClick={() => handleBranchSelect(branch.name)}
              className="w-full text-left px-3 py-2 text-sm text-text-primary hover:bg-bg-hover transition-colors flex items-center justify-between"
            >
              <span className="truncate">{branch.name}</span>
              {branch.is_remote && (
                <span className="text-xs text-text-muted ml-2 flex-shrink-0">remote</span>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Message for too many branches */}
      {showDropdown && branchCount > 100 && (
        <div className="absolute z-10 mt-1 w-full rounded-md border border-border bg-bg-card shadow-lg px-3 py-2">
          <p className="text-sm text-text-muted">
            Too many branches ({branchCount}). Refine your search pattern.
          </p>
        </div>
      )}

      {/* Helper text */}
      <p className="mt-1 text-xs text-text-muted">
        {branchCount === 0 && debouncedPattern !== '*' && (
          <span>No branches match pattern "{debouncedPattern}"</span>
        )}
        {branchCount > 0 && branchCount <= 100 && (
          <span>{branchCount} {branchCount === 1 ? 'branch' : 'branches'} match</span>
        )}
        {branchCount > 100 && (
          <span>{branchCount} branches match - type to narrow down</span>
        )}
      </p>
    </div>
  );
}
