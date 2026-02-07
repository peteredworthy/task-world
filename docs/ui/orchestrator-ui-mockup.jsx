import React, { useState } from 'react';

// Mock data matching the spec
const mockRuns = [
  {
    id: '8392-A',
    name: 'Feat: User Auth Implementation',
    status: 'active',
    routine_name: 'Scaffold-Agent-v4',
    project_name: 'Core-API',
    started_at: '2m 30s ago',
    current_action: 'Generating Code...',
    tokens_read: 14204,
    tokens_write: 2105,
    duration: '00:48',
    cost: 0.042,
    steps: [
      {
        id: 'S1',
        title: 'INIT',
        status: 'completed',
        tasks: [
          {
            id: 'T-00',
            title: 'Context Loading',
            status: 'completed',
            attempts: [
              { grades: { required: ['A', 'A'], expected: ['B'], optional: [] } }
            ]
          }
        ]
      },
      {
        id: 'S2',
        title: 'PLAN',
        status: 'completed',
        tasks: [
          {
            id: 'T-01',
            title: 'Architecture',
            status: 'completed',
            attempts: [
              { grades: { required: ['A'], expected: ['B', 'B'], optional: ['A'] } }
            ]
          }
        ]
      },
      {
        id: 'S3',
        title: 'CODE GEN',
        status: 'in_progress',
        tasks: [
          {
            id: 'T-02',
            title: 'Draft Implementation',
            status: 'building',
            attempts: [
              { grades: { required: ['F', 'D'], expected: ['D'], optional: [] } },
              { grades: { required: ['C', 'C'], expected: ['B'], optional: [] } },
              { status: 'retrying' }
            ]
          }
        ]
      },
      {
        id: 'S4',
        title: 'REVIEW',
        status: 'pending',
        tasks: [
          {
            id: 'T-03',
            title: 'Code Review',
            status: 'pending',
            attempts: []
          }
        ]
      }
    ]
  },
  {
    id: '8393-B',
    name: 'Fix: Race condition in API',
    status: 'paused',
    routine_name: 'Debug-Bot',
    project_name: 'Core-API',
    started_at: '15m ago',
    current_action: 'Awaiting Input',
    tokens_read: 8420,
    tokens_write: 1205,
    duration: '3:42',
    cost: 0.028,
    steps: [
      {
        id: 'S1',
        title: 'ANALYZE',
        status: 'completed',
        tasks: [
          {
            id: 'T-00',
            title: 'Stack Trace Analysis',
            status: 'completed',
            attempts: [
              { grades: { required: ['A'], expected: ['A', 'B'], optional: [] } }
            ]
          }
        ]
      },
      {
        id: 'S2',
        title: 'FIX',
        status: 'in_progress',
        tasks: [
          {
            id: 'T-01',
            title: 'Implement Fix',
            status: 'paused',
            attempts: [
              { grades: { required: ['B', 'C'], expected: ['C'], optional: ['B'] } }
            ]
          }
        ]
      },
      {
        id: 'S3',
        title: 'TEST',
        status: 'pending',
        tasks: [
          {
            id: 'T-02',
            title: 'Regression Tests',
            status: 'pending',
            attempts: []
          }
        ]
      }
    ]
  },
  {
    id: '8390-B',
    name: 'Docs: Update Readme',
    status: 'completed',
    routine_name: 'Doc-Updater',
    project_name: 'Core-API',
    duration: '45s',
    tokens_read: 3200,
    tokens_write: 890,
    cost: 0.012,
    steps: [
      {
        id: 'S1',
        title: 'SCAN',
        status: 'completed',
        tasks: [
          {
            id: 'T-00',
            title: 'Analyze Codebase',
            status: 'completed',
            attempts: [
              { grades: { required: ['A'], expected: ['A'], optional: [] } }
            ]
          }
        ]
      },
      {
        id: 'S2',
        title: 'DRAFT',
        status: 'completed',
        tasks: [
          {
            id: 'T-01',
            title: 'Generate Docs',
            status: 'completed',
            attempts: [
              { grades: { required: ['B'], expected: ['A', 'A'], optional: ['A'] } }
            ]
          }
        ]
      },
      {
        id: 'S3',
        title: 'REVIEW',
        status: 'completed',
        tasks: [
          {
            id: 'T-02',
            title: 'Quality Check',
            status: 'completed',
            attempts: [
              { grades: { required: ['A', 'A'], expected: ['A'], optional: [] } }
            ]
          }
        ]
      }
    ]
  },
  {
    id: '8389-C',
    name: 'Test: Generate Unit Tests',
    status: 'completed',
    routine_name: 'Test-Gen-v2',
    project_name: 'Auth-Service',
    duration: '1m 12s',
    tokens_read: 5600,
    tokens_write: 2100,
    cost: 0.021,
    steps: [
      {
        id: 'S1',
        title: 'ANALYZE',
        status: 'completed',
        tasks: [
          {
            id: 'T-00',
            title: 'Parse Functions',
            status: 'completed',
            attempts: [
              { grades: { required: ['A'], expected: [], optional: ['A', 'B'] } }
            ]
          }
        ]
      },
      {
        id: 'S2',
        title: 'GENERATE',
        status: 'completed',
        tasks: [
          {
            id: 'T-01',
            title: 'Write Tests',
            status: 'completed',
            attempts: [
              { grades: { required: ['C', 'D'], expected: ['C'], optional: [] } },
              { grades: { required: ['B', 'B'], expected: ['A'], optional: [] } }
            ]
          }
        ]
      }
    ]
  }
];

const mockRoutines = [
  {
    id: 'planning',
    name: 'Planning',
    description: 'Generates a comprehensive step-by-step implementation plan for a given feature request or architectural change.',
    source: 'local',
    version: 'v1.2',
    steps: 5,
    inputs: 2,
    icon: '🏗'
  },
  {
    id: 'bug-fix',
    name: 'Bug-fix',
    description: 'Analyzes the provided stack trace and error logs to identify the root cause and suggests a code patch.',
    source: 'local',
    version: 'v2.0',
    steps: 3,
    inputs: 1,
    icon: '🐛'
  },
  {
    id: 'refactor-module',
    name: 'Refactor-module',
    description: 'Automated technical debt cleanup for the currently selected module. Enforces linting rules and simplifies logic.',
    source: 'project',
    version: 'beta',
    steps: 8,
    inputs: 0,
    icon: '🔧'
  },
  {
    id: 'doc-gen',
    name: 'Doc-gen',
    description: 'Scans the codebase and updates README.md and inline documentation blocks based on recent changes.',
    source: 'project',
    version: 'v1.0',
    steps: 4,
    inputs: 1,
    icon: '📄'
  }
];

const gradeColors = {
  'A': '#22c55e',
  'B': '#3b82f6',
  'C': '#eab308',
  'D': '#f97316',
  'F': '#ef4444'
};

const statusColors = {
  active: '#22c55e',
  paused: '#eab308',
  completed: '#22c55e',
  failed: '#ef4444',
  pending: '#64748b'
};

// Grade badge component
const GradeBadge = ({ grade }) => {
  if (!grade || grade === '-') {
    return (
      <div style={{
        width: 32,
        height: 26,
        borderRadius: 4,
        background: '#1e2432',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#4b5563',
        fontSize: 11,
        fontWeight: 600
      }}>
        -
      </div>
    );
  }
  return (
    <div style={{
      width: 32,
      height: 26,
      borderRadius: 4,
      background: gradeColors[grade] + '25',
      color: gradeColors[grade],
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: 12,
      fontWeight: 700
    }}>
      {grade}
    </div>
  );
};

// Three-tier grade display with separators
const GradeRow = ({ grades, compact = false }) => {
  const required = grades?.required || [];
  const expected = grades?.expected || [];
  const optional = grades?.optional || [];
  
  const hasRequired = required.length > 0;
  const hasExpected = expected.length > 0;
  const hasOptional = optional.length > 0;
  
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
      {/* Required grades (left) */}
      <div style={{ display: 'flex', gap: 2 }}>
        {hasRequired ? required.map((g, i) => <GradeBadge key={`r${i}`} grade={g} />) : <GradeBadge grade="-" />}
      </div>
      
      {/* Separator */}
      <div style={{ width: 1, height: 20, background: '#374151', margin: '0 2px' }} />
      
      {/* Expected grades (center) */}
      <div style={{ display: 'flex', gap: 2 }}>
        {hasExpected ? expected.map((g, i) => <GradeBadge key={`e${i}`} grade={g} />) : <GradeBadge grade="-" />}
      </div>
      
      {/* Separator */}
      <div style={{ width: 1, height: 20, background: '#374151', margin: '0 2px' }} />
      
      {/* Optional grades (right) */}
      <div style={{ display: 'flex', gap: 2 }}>
        {hasOptional ? optional.map((g, i) => <GradeBadge key={`o${i}`} grade={g} />) : <GradeBadge grade="-" />}
      </div>
    </div>
  );
};

// Step badge for collapsed view
const StepBadge = ({ id, status }) => {
  const isCompleted = status === 'completed';
  const isActive = status === 'in_progress';
  const isPending = status === 'pending';
  
  return (
    <div style={{
      width: 28,
      height: 22,
      borderRadius: 4,
      background: isPending ? 'transparent' : isActive ? '#22c55e' : '#8b5cf6',
      border: isPending ? '1px solid #374151' : 'none',
      color: isPending ? '#6b7280' : '#fff',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: 10,
      fontWeight: 600,
      boxShadow: isActive ? '0 0 10px #22c55e50' : 'none'
    }}>
      {id}
    </div>
  );
};

// Status badge
const StatusBadge = ({ status }) => {
  const labels = {
    active: 'ACTIVE',
    paused: 'PAUSED',
    completed: 'COMPLETED',
    failed: 'FAILED'
  };
  
  return (
    <span style={{
      padding: '4px 10px',
      borderRadius: 4,
      background: statusColors[status] + '20',
      color: statusColors[status],
      fontSize: 10,
      fontWeight: 600,
      textTransform: 'uppercase'
    }}>
      {labels[status]}
    </span>
  );
};

// Task card within step column
const TaskCard = ({ task, onClick, isSelected }) => {
  const hasFailed = task.attempts?.some(a => a.grades?.required?.includes('F'));
  
  return (
    <div 
      onClick={onClick}
      style={{
        background: isSelected ? '#1e2432' : '#151921',
        borderRadius: 6,
        padding: 10,
        borderLeft: hasFailed ? '3px solid #f97316' : '3px solid transparent',
        cursor: 'pointer',
        border: isSelected ? '1px solid #8b5cf6' : '1px solid transparent',
        transition: 'all 0.15s ease'
      }}
    >
      <div style={{ 
        display: 'flex', 
        alignItems: 'center', 
        gap: 6, 
        marginBottom: task.attempts?.length > 0 ? 8 : 0,
        color: '#e2e8f0',
        fontSize: 12,
        fontWeight: 500
      }}>
        {task.status === 'completed' && <span style={{ color: '#22c55e' }}>✓</span>}
        {task.title}
      </div>
      
      {task.status === 'pending' ? null : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {task.attempts?.map((attempt, i) => (
            attempt.status === 'retrying' ? (
              <div key={i} style={{
                background: '#1e2432',
                borderRadius: 4,
                padding: '6px 10px',
                color: '#22c55e',
                fontSize: 11,
                display: 'flex',
                alignItems: 'center',
                gap: 6
              }}>
                <span style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: '#22c55e',
                  animation: 'pulse 1.5s infinite'
                }} />
                Building...
              </div>
            ) : (
              <GradeRow key={i} grades={attempt.grades} />
            )
          ))}
        </div>
      )}
    </div>
  );
};

// Step column in expanded view
const StepColumn = ({ step, onTaskClick, selectedTaskId }) => {
  const isActive = step.status === 'in_progress';
  const isPending = step.status === 'pending';
  
  return (
    <div style={{ flex: 1, minWidth: 180 }}>
      <div style={{ 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'space-between',
        marginBottom: 6
      }}>
        <div style={{ 
          display: 'flex', 
          alignItems: 'center', 
          gap: 6,
          color: isPending ? '#6b7280' : isActive ? '#22c55e' : '#e2e8f0',
          fontSize: 11,
          fontWeight: 600,
          textTransform: 'uppercase'
        }}>
          {isActive && <span style={{ 
            width: 6, 
            height: 6, 
            borderRadius: '50%', 
            background: '#22c55e',
            boxShadow: '0 0 8px #22c55e'
          }} />}
          {step.title}
        </div>
        <StepBadge id={step.id} status={step.status} />
      </div>
      
      <div style={{
        height: 2,
        background: isPending ? 'transparent' : '#8b5cf6',
        borderRadius: 1,
        marginBottom: 10,
        ...(isPending && { 
          backgroundImage: 'repeating-linear-gradient(90deg, #374151 0px, #374151 4px, transparent 4px, transparent 8px)',
          backgroundSize: '8px 2px'
        })
      }} />
      
      {isPending ? (
        <div style={{
          border: '1px dashed #374151',
          borderRadius: 6,
          padding: 20,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#4b5563',
          fontSize: 12,
          minHeight: 60,
          gap: 4
        }}>
          <span style={{ fontSize: 11, color: '#6b7280' }}>{step.tasks[0]?.title}</span>
          <span>Pending</span>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {step.tasks?.map(task => (
            <TaskCard 
              key={task.id} 
              task={task} 
              onClick={() => onTaskClick(task)}
              isSelected={selectedTaskId === task.id}
            />
          ))}
        </div>
      )}
    </div>
  );
};

// Expanded run card
const ExpandedRunCard = ({ run, onCollapse, onTaskClick, selectedTaskId }) => {
  return (
    <div style={{
      background: '#0f1218',
      border: run.status === 'active' ? '1px solid #22c55e30' : '1px solid #1e2432',
      borderRadius: 8,
      overflow: 'hidden'
    }}>
      {/* Header */}
      <div style={{ padding: 14, borderBottom: '1px solid #1e2432' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div 
              onClick={onCollapse}
              style={{
                width: 36,
                height: 36,
                borderRadius: 6,
                background: '#8b5cf620',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                position: 'relative',
                cursor: 'pointer'
              }}
            >
              <span style={{ fontSize: 16 }}>📦</span>
              <span style={{
                position: 'absolute',
                top: -2,
                right: -2,
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: statusColors[run.status],
                boxShadow: run.status === 'active' ? `0 0 8px ${statusColors[run.status]}` : 'none'
              }} />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ color: '#f8fafc', fontSize: 14, fontWeight: 600 }}>{run.name}</span>
                <StatusBadge status={run.status} />
              </div>
              <div style={{ color: '#64748b', fontSize: 11, marginTop: 2 }}>
                ID: #{run.id} • Routine: {run.routine_name} • Project: {run.project_name}
              </div>
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ color: '#94a3b8', fontSize: 11 }}>Started {run.started_at}</div>
            {run.current_action && (
              <div style={{ 
                display: 'flex', 
                alignItems: 'center', 
                gap: 6,
                background: '#1e2432',
                padding: '5px 10px',
                borderRadius: 6,
                marginTop: 4,
                color: '#22c55e',
                fontSize: 11
              }}>
                <span style={{
                  width: 5,
                  height: 5,
                  borderRadius: '50%',
                  background: '#22c55e',
                  animation: 'pulse 2s infinite'
                }} />
                {run.current_action}
              </div>
            )}
          </div>
        </div>
      </div>
      
      {/* Step Columns */}
      <div style={{ padding: 14 }}>
        <div style={{ display: 'flex', gap: 12 }}>
          {run.steps.map(step => (
            <StepColumn 
              key={step.id} 
              step={step} 
              onTaskClick={onTaskClick}
              selectedTaskId={selectedTaskId}
            />
          ))}
        </div>
      </div>
      
      {/* Footer */}
      <div style={{ 
        padding: '10px 14px', 
        borderTop: '1px solid #1e2432',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <button style={{
          background: 'transparent',
          border: 'none',
          color: '#94a3b8',
          fontSize: 12,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: 6
        }}>
          👁 View Logs
        </button>
        <button style={{
          background: 'transparent',
          border: '1px solid #ef4444',
          borderRadius: 6,
          color: '#ef4444',
          padding: '6px 14px',
          fontSize: 11,
          fontWeight: 600,
          cursor: 'pointer'
        }}>
          ⊘ ABORT RUN
        </button>
      </div>
    </div>
  );
};

// Collapsed run card
const CollapsedRunCard = ({ run, onExpand }) => {
  return (
    <div 
      onClick={onExpand}
      style={{
        background: '#151921',
        border: '1px solid #1e2432',
        borderRadius: 8,
        padding: 14,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        cursor: 'pointer',
        transition: 'border-color 0.2s',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ color: run.status === 'completed' ? '#22c55e' : run.status === 'paused' ? '#eab308' : '#64748b', fontSize: 16 }}>
          {run.status === 'completed' ? '✓' : run.status === 'paused' ? '⏸' : '●'}
        </span>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: '#f8fafc', fontSize: 13, fontWeight: 500 }}>{run.name}</span>
            {run.status === 'paused' && <StatusBadge status="paused" />}
          </div>
          <div style={{ color: '#64748b', fontSize: 11, marginTop: 2 }}>
            ID: #{run.id} • Routine: {run.routine_name} • Project: {run.project_name}
          </div>
        </div>
      </div>
      
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ display: 'flex', gap: 3 }}>
          {run.steps.map(step => (
            <StepBadge key={step.id} id={step.id} status={step.status} />
          ))}
        </div>
        {run.duration && (
          <div style={{ 
            display: 'flex', 
            alignItems: 'center', 
            gap: 4,
            color: '#94a3b8',
            fontSize: 11,
            background: '#1e2432',
            padding: '4px 8px',
            borderRadius: 4
          }}>
            ⏱ {run.duration}
          </div>
        )}
        {run.status === 'paused' && (
          <button 
            onClick={(e) => { e.stopPropagation(); }}
            style={{
              background: '#8b5cf6',
              border: 'none',
              borderRadius: 6,
              color: '#fff',
              padding: '6px 14px',
              fontSize: 11,
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 4
            }}
          >
            ▶ Resume
          </button>
        )}
      </div>
    </div>
  );
};

// Inspector panel for task details
const InspectorPanel = ({ task, run, onClose }) => {
  if (!task) return null;
  
  return (
    <div style={{
      width: 340,
      background: '#0f1218',
      borderLeft: '1px solid #1e2432',
      height: '100%',
      display: 'flex',
      flexDirection: 'column'
    }}>
      {/* Header */}
      <div style={{
        padding: '14px 16px',
        borderBottom: '1px solid #1e2432',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: '#94a3b8' }}>⊟</span>
          <span style={{ color: '#f8fafc', fontWeight: 600, fontSize: 14 }}>Inspector</span>
        </div>
        <button 
          onClick={onClose}
          style={{
            background: 'transparent',
            border: 'none',
            color: '#64748b',
            cursor: 'pointer',
            fontSize: 18
          }}
        >
          ×
        </button>
      </div>
      
      {/* Selected Task */}
      <div style={{ padding: 16 }}>
        <div style={{ color: '#64748b', fontSize: 10, fontWeight: 600, marginBottom: 8, textTransform: 'uppercase' }}>
          ☑ Selected Task
        </div>
        <div style={{
          background: '#151921',
          borderRadius: 6,
          padding: 12
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
            <span style={{ color: '#94a3b8', fontSize: 11 }}>{task.id}</span>
            <span style={{ color: '#64748b', fontSize: 10, background: '#1e2432', padding: '2px 6px', borderRadius: 3 }}>v2.0</span>
          </div>
          <div style={{ color: '#f8fafc', fontSize: 13, marginTop: 4 }}>{task.title}</div>
        </div>
      </div>
      
      {/* Attempt History */}
      <div style={{ padding: '0 16px 16px' }}>
        <div style={{ color: '#64748b', fontSize: 10, fontWeight: 600, marginBottom: 8, textTransform: 'uppercase' }}>
          ⏱ Attempt History
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {task.attempts?.map((attempt, i) => (
            <div key={i} style={{
              background: attempt.status === 'retrying' ? '#1e293b' : i === 0 && task.attempts.length > 1 ? '#1c1517' : '#151921',
              borderRadius: 6,
              padding: 12,
              borderLeft: i === 0 && task.attempts.length > 1 && !attempt.status ? '3px solid #ef4444' : '3px solid transparent'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ color: attempt.status === 'retrying' ? '#22c55e' : i === task.attempts.length - 1 && !attempt.status ? '#22c55e' : '#ef4444' }}>
                    {attempt.status === 'retrying' ? '⟳' : i === task.attempts.length - 1 && !attempt.status ? '⟳' : '⊘'}
                  </span>
                  <span style={{ color: '#e2e8f0', fontSize: 12, fontWeight: 500 }}>Attempt #{i + 1}</span>
                </div>
                <span style={{
                  fontSize: 10,
                  fontWeight: 600,
                  color: attempt.status === 'retrying' ? '#22c55e' : i === 0 && task.attempts.length > 1 ? '#ef4444' : '#22c55e'
                }}>
                  {attempt.status === 'retrying' ? 'RUNNING' : i === 0 && task.attempts.length > 1 ? 'FAILED' : 'PASSED'}
                </span>
              </div>
              <div style={{ color: '#94a3b8', fontSize: 11 }}>
                {attempt.status === 'retrying' ? 'Generating code based on updated prompts.' : 'Self-correction triggered: Missing context for JWT...'}
              </div>
            </div>
          ))}
        </div>
      </div>
      
      {/* Verifier Grades */}
      {task.attempts?.length > 0 && !task.attempts[task.attempts.length - 1].status && (
        <div style={{ padding: '0 16px 16px' }}>
          <div style={{ color: '#64748b', fontSize: 10, fontWeight: 600, marginBottom: 8, textTransform: 'uppercase' }}>
            ★ Verifier Grades (Latest)
          </div>
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: 8
          }}>
            {['SYNTAX', 'LOGIC', 'SECURITY', 'PERF'].map((category, i) => (
              <div key={category} style={{
                background: '#151921',
                borderRadius: 6,
                padding: 12,
                textAlign: 'center'
              }}>
                <div style={{ color: '#64748b', fontSize: 10, marginBottom: 6 }}>{category}</div>
                <div style={{ 
                  color: i < 2 ? (i === 0 ? '#22c55e' : '#3b82f6') : '#4b5563', 
                  fontSize: i < 2 ? 20 : 14,
                  fontWeight: 700
                }}>
                  {i === 0 ? 'A+' : i === 1 ? 'B-' : '-'}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      
      {/* Debug Button */}
      <div style={{ padding: '0 16px', marginTop: 'auto', paddingBottom: 16 }}>
        <button style={{
          width: '100%',
          background: '#1e2432',
          border: '1px solid #374151',
          borderRadius: 6,
          color: '#e2e8f0',
          padding: '10px 16px',
          fontSize: 12,
          fontWeight: 500,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 8
        }}>
          ⚙ Debug This Step
        </button>
      </div>
    </div>
  );
};

// Configure New Run Modal
const ConfigureNewRunModal = ({ routine, onClose, onStart }) => {
  const [selectedAgent, setSelectedAgent] = useState('openhands');
  const [featureName, setFeatureName] = useState('');
  const [targetBranch, setTargetBranch] = useState('main');
  const [project, setProject] = useState('');
  
  const agents = [
    { id: 'openhands', name: 'OpenHands', icon: '🖐', available: true },
    { id: 'claude-cli', name: 'Claude CLI', icon: '🟧', available: true },
    { id: 'external', name: 'External Agent', icon: '🟪', available: false }
  ];
  
  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0,0,0,0.8)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000
    }}>
      <div style={{
        background: '#0f1218',
        borderRadius: 12,
        width: 520,
        maxHeight: '90vh',
        overflow: 'auto',
        border: '1px solid #1e2432'
      }}>
        {/* Header */}
        <div style={{ padding: '20px 24px', borderBottom: '1px solid #1e2432' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
            <div>
              <h2 style={{ color: '#f8fafc', fontSize: 18, fontWeight: 600, margin: 0 }}>Configure New Agent Run</h2>
              <p style={{ color: '#64748b', fontSize: 13, margin: '4px 0 0' }}>Setup parameters for your next autonomous coding session.</p>
            </div>
            <button 
              onClick={onClose}
              style={{
                background: 'transparent',
                border: 'none',
                color: '#64748b',
                fontSize: 20,
                cursor: 'pointer'
              }}
            >
              ×
            </button>
          </div>
        </div>
        
        {/* Content */}
        <div style={{ padding: 24 }}>
          {/* Target Project */}
          <div style={{ marginBottom: 20 }}>
            <label style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
              📁 Target Project
            </label>
            <div style={{
              background: '#151921',
              border: '1px solid #252b38',
              borderRadius: 6,
              padding: '10px 14px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between'
            }}>
              <input 
                type="text"
                placeholder="Select repository or project..."
                value={project}
                onChange={(e) => setProject(e.target.value)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: '#94a3b8',
                  fontSize: 13,
                  outline: 'none',
                  width: '100%'
                }}
              />
              <span style={{ color: '#eab308' }}>📂</span>
            </div>
          </div>
          
          {/* Configuration */}
          <div style={{ marginBottom: 20 }}>
            <label style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
              ⚙ Configuration
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div>
                <div style={{ color: '#94a3b8', fontSize: 11, marginBottom: 6 }}>Feature Name</div>
                <input 
                  type="text"
                  placeholder="e.g. auth-refactor-v2"
                  value={featureName}
                  onChange={(e) => setFeatureName(e.target.value)}
                  style={{
                    width: '100%',
                    background: '#151921',
                    border: '1px solid #252b38',
                    borderRadius: 6,
                    padding: '10px 14px',
                    color: '#e2e8f0',
                    fontSize: 13,
                    outline: 'none',
                    boxSizing: 'border-box'
                  }}
                />
              </div>
              <div>
                <div style={{ color: '#94a3b8', fontSize: 11, marginBottom: 6 }}>Target Branch</div>
                <div style={{
                  background: '#151921',
                  border: '1px solid #252b38',
                  borderRadius: 6,
                  padding: '10px 14px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8
                }}>
                  <span style={{ color: '#22c55e' }}>⑂</span>
                  <input 
                    type="text"
                    value={targetBranch}
                    onChange={(e) => setTargetBranch(e.target.value)}
                    style={{
                      background: 'transparent',
                      border: 'none',
                      color: '#e2e8f0',
                      fontSize: 13,
                      outline: 'none',
                      width: '100%'
                    }}
                  />
                </div>
              </div>
            </div>
          </div>
          
          {/* Select Agent */}
          <div style={{ marginBottom: 24 }}>
            <label style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
              🤖 Select Agent
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
              {agents.map(agent => (
                <div 
                  key={agent.id}
                  onClick={() => agent.available && setSelectedAgent(agent.id)}
                  style={{
                    background: '#151921',
                    border: selectedAgent === agent.id ? '2px solid #8b5cf6' : '1px solid #252b38',
                    borderRadius: 8,
                    padding: 14,
                    cursor: agent.available ? 'pointer' : 'not-allowed',
                    opacity: agent.available ? 1 : 0.5,
                    position: 'relative'
                  }}
                >
                  {selectedAgent === agent.id && (
                    <div style={{
                      position: 'absolute',
                      top: 8,
                      right: 8,
                      width: 16,
                      height: 16,
                      borderRadius: '50%',
                      border: '2px solid #8b5cf6',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center'
                    }}>
                      <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#8b5cf6' }} />
                    </div>
                  )}
                  <div style={{
                    width: 36,
                    height: 36,
                    borderRadius: 8,
                    background: agent.id === 'openhands' ? '#3b82f620' : agent.id === 'claude-cli' ? '#f9731620' : '#8b5cf620',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    marginBottom: 10,
                    fontSize: 18
                  }}>
                    {agent.icon}
                  </div>
                  <div style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 500 }}>{agent.name}</div>
                  <div style={{ 
                    color: agent.available ? '#22c55e' : '#ef4444', 
                    fontSize: 11,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                    marginTop: 4
                  }}>
                    <span style={{
                      width: 6,
                      height: 6,
                      borderRadius: '50%',
                      background: agent.available ? '#22c55e' : '#ef4444'
                    }} />
                    {agent.available ? 'Available' : 'Not Found'}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
        
        {/* Footer */}
        <div style={{ 
          padding: '16px 24px', 
          borderTop: '1px solid #1e2432',
          display: 'flex',
          justifyContent: 'flex-end',
          gap: 12
        }}>
          <button 
            onClick={onClose}
            style={{
              background: 'transparent',
              border: '1px solid #374151',
              borderRadius: 6,
              color: '#94a3b8',
              padding: '10px 20px',
              fontSize: 13,
              fontWeight: 500,
              cursor: 'pointer'
            }}
          >
            Cancel
          </button>
          <button 
            onClick={onStart}
            style={{
              background: '#8b5cf6',
              border: 'none',
              borderRadius: 6,
              color: '#fff',
              padding: '10px 20px',
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 6
            }}
          >
            🚀 Create & Start
          </button>
        </div>
      </div>
    </div>
  );
};

// Routine Library View
const RoutineLibrary = ({ onSelectRoutine, onBack }) => {
  const localRoutines = mockRoutines.filter(r => r.source === 'local');
  const projectRoutines = mockRoutines.filter(r => r.source === 'project');
  
  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      {/* Sidebar */}
      <div style={{
        width: 220,
        background: '#0a0c10',
        borderRight: '1px solid #1e2432',
        padding: '16px 12px',
        display: 'flex',
        flexDirection: 'column'
      }}>
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <div style={{
              width: 28,
              height: 28,
              borderRadius: 6,
              background: 'linear-gradient(135deg, #8b5cf6, #06b6d4)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 14
            }}>
              ⊞
            </div>
            <span style={{ color: '#f8fafc', fontSize: 14, fontWeight: 600 }}>Orchestrator</span>
          </div>
          <div style={{ color: '#64748b', fontSize: 11, marginLeft: 36 }}>Mission Control</div>
        </div>
        
        <nav style={{ flex: 1 }}>
          {[
            { icon: '▣', label: 'Dashboard', active: false },
            { icon: '🤖', label: 'Agents', active: false },
            { icon: '📋', label: 'Routine Library', active: true },
            { icon: '⏱', label: 'History', active: false },
          ].map(item => (
            <div 
              key={item.label}
              onClick={item.label === 'Dashboard' ? onBack : undefined}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '10px 12px',
                borderRadius: 6,
                marginBottom: 4,
                background: item.active ? '#8b5cf620' : 'transparent',
                color: item.active ? '#f8fafc' : '#94a3b8',
                cursor: 'pointer'
              }}
            >
              <span>{item.icon}</span>
              <span style={{ fontSize: 13 }}>{item.label}</span>
            </div>
          ))}
        </nav>
        
        <div style={{ borderTop: '1px solid #1e2432', paddingTop: 12 }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '10px 12px',
            color: '#94a3b8',
            cursor: 'pointer'
          }}>
            <span>⚙</span>
            <span style={{ fontSize: 13 }}>Settings</span>
          </div>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '10px 12px'
          }}>
            <div style={{
              width: 28,
              height: 28,
              borderRadius: '50%',
              background: '#8b5cf6'
            }} />
            <div>
              <div style={{ color: '#f8fafc', fontSize: 12 }}>DevUser</div>
              <div style={{ color: '#64748b', fontSize: 10 }}>Pro Plan</div>
            </div>
          </div>
        </div>
      </div>
      
      {/* Main Content */}
      <div style={{ flex: 1, background: '#0f1218', padding: 24 }}>
        <div style={{ marginBottom: 8, color: '#64748b', fontSize: 12 }}>
          <span onClick={onBack} style={{ cursor: 'pointer' }}>Home</span> / Routine Library
        </div>
        
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: 24 }}>
          <div>
            <h1 style={{ color: '#f8fafc', fontSize: 24, fontWeight: 600, margin: 0 }}>Routine Library</h1>
            <p style={{ color: '#94a3b8', fontSize: 14, margin: '8px 0 0' }}>
              Browse and manage your automation workflow templates. Deploy trusted routines to your agents instantly.
            </p>
          </div>
          <button style={{
            background: '#8b5cf6',
            border: 'none',
            borderRadius: 6,
            color: '#fff',
            padding: '10px 16px',
            fontSize: 13,
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 6
          }}>
            + New Template
          </button>
        </div>
        
        {/* Filters */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
          <div style={{
            background: '#151921',
            border: '1px solid #252b38',
            borderRadius: 6,
            padding: '10px 14px',
            width: 320,
            color: '#64748b',
            fontSize: 13
          }}>
            🔍 Search templates or workflows (e.g. 'bug fix', 'refactor')
          </div>
          <div style={{ display: 'flex', gap: 4 }}>
            {['All', 'Local', 'Project', 'External'].map((filter, i) => (
              <button key={filter} style={{
                background: i === 0 ? '#8b5cf6' : 'transparent',
                border: i === 0 ? 'none' : '1px solid #374151',
                borderRadius: 6,
                color: i === 0 ? '#fff' : '#94a3b8',
                padding: '8px 14px',
                fontSize: 12,
                cursor: 'pointer'
              }}>
                {filter}
              </button>
            ))}
          </div>
        </div>
        
        {/* Local Routines */}
        <div style={{ marginBottom: 32 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ color: '#eab308' }}>📁</span>
              <span style={{ color: '#f8fafc', fontSize: 15, fontWeight: 600 }}>Local Routines</span>
            </div>
            <span style={{ color: '#64748b', fontSize: 11, fontFamily: 'monospace' }}>~/user/routines</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
            {localRoutines.map(routine => (
              <div key={routine.id} style={{
                background: '#151921',
                border: '1px solid #252b38',
                borderRadius: 8,
                padding: 16
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 18 }}>{routine.icon}</span>
                    <span style={{ color: '#f8fafc', fontSize: 15, fontWeight: 600 }}>{routine.name}</span>
                  </div>
                  <span style={{ 
                    background: '#8b5cf620', 
                    color: '#8b5cf6', 
                    padding: '2px 8px', 
                    borderRadius: 4, 
                    fontSize: 10,
                    fontWeight: 600
                  }}>
                    {routine.version}
                  </span>
                </div>
                <p style={{ color: '#94a3b8', fontSize: 12, margin: '0 0 16px', lineHeight: 1.5 }}>
                  {routine.description}
                </p>
                <div style={{ display: 'flex', gap: 12, marginBottom: 16, color: '#64748b', fontSize: 11 }}>
                  <span>≡ {routine.steps} Steps</span>
                  <span>📥 {routine.inputs} Inputs</span>
                </div>
                <button 
                  onClick={() => onSelectRoutine(routine)}
                  style={{
                    width: '100%',
                    background: '#1e2432',
                    border: '1px solid #374151',
                    borderRadius: 6,
                    color: '#e2e8f0',
                    padding: '10px',
                    fontSize: 12,
                    fontWeight: 500,
                    cursor: 'pointer'
                  }}
                >
                  Use Routine →
                </button>
              </div>
            ))}
            {/* Create New Card */}
            <div style={{
              background: 'transparent',
              border: '1px dashed #374151',
              borderRadius: 8,
              padding: 16,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer'
            }}>
              <div style={{
                width: 48,
                height: 48,
                borderRadius: '50%',
                border: '1px dashed #374151',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#64748b',
                fontSize: 24,
                marginBottom: 12
              }}>
                +
              </div>
              <span style={{ color: '#94a3b8', fontSize: 13 }}>Create Local Routine</span>
            </div>
          </div>
        </div>
        
        {/* Project Routines */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ color: '#8b5cf6' }}>🔧</span>
              <span style={{ color: '#f8fafc', fontSize: 15, fontWeight: 600 }}>Project Routines</span>
            </div>
            <span style={{ color: '#64748b', fontSize: 11, fontFamily: 'monospace' }}>./.orchestrator/workflows</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
            {projectRoutines.map(routine => (
              <div key={routine.id} style={{
                background: '#151921',
                border: '1px solid #252b38',
                borderRadius: 8,
                padding: 16
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 18 }}>{routine.icon}</span>
                    <span style={{ color: '#f8fafc', fontSize: 15, fontWeight: 600 }}>{routine.name}</span>
                  </div>
                  <span style={{ 
                    background: routine.version === 'beta' ? '#eab30820' : '#8b5cf620', 
                    color: routine.version === 'beta' ? '#eab308' : '#8b5cf6', 
                    padding: '2px 8px', 
                    borderRadius: 4, 
                    fontSize: 10,
                    fontWeight: 600
                  }}>
                    {routine.version}
                  </span>
                </div>
                <p style={{ color: '#94a3b8', fontSize: 12, margin: '0 0 16px', lineHeight: 1.5 }}>
                  {routine.description}
                </p>
                <div style={{ display: 'flex', gap: 12, marginBottom: 16, color: '#64748b', fontSize: 11 }}>
                  <span>≡ {routine.steps} Steps</span>
                  <span>📥 {routine.inputs} Inputs</span>
                </div>
                <button 
                  onClick={() => onSelectRoutine(routine)}
                  style={{
                    width: '100%',
                    background: '#1e2432',
                    border: '1px solid #374151',
                    borderRadius: 6,
                    color: '#e2e8f0',
                    padding: '10px',
                    fontSize: 12,
                    fontWeight: 500,
                    cursor: 'pointer'
                  }}
                >
                  Use Routine →
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

// Run Detail View
const RunDetailView = ({ run, onBack }) => {
  const [selectedTask, setSelectedTask] = useState(null);
  
  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: '#0a0c10' }}>
      {/* Main Content */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {/* Header */}
        <header style={{
          background: '#0f1218',
          borderBottom: '1px solid #1e2432',
          padding: '12px 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{
              width: 32,
              height: 32,
              borderRadius: 6,
              background: 'linear-gradient(135deg, #8b5cf6, #06b6d4)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 16
            }}>
              ⊞
            </div>
            <span style={{ fontSize: 16, fontWeight: 600, color: '#f8fafc' }}>Orchestrator</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <span style={{ cursor: 'pointer' }}>🔔</span>
            <span style={{ cursor: 'pointer' }}>⚙</span>
            <div style={{
              width: 32,
              height: 32,
              borderRadius: '50%',
              background: '#8b5cf6'
            }} />
          </div>
        </header>
        
        {/* Breadcrumb */}
        <div style={{ padding: '12px 24px', borderBottom: '1px solid #1e2432', background: '#0f1218' }}>
          <span 
            onClick={onBack}
            style={{ color: '#64748b', fontSize: 13, cursor: 'pointer' }}
          >
            ← Runs
          </span>
          <span style={{ color: '#374151', margin: '0 8px' }}>/</span>
          <span style={{ color: '#f8fafc', fontSize: 13 }}>{run.name.toLowerCase().replace(/[^a-z0-9]/g, '-')}</span>
        </div>
        
        {/* Run Header */}
        <div style={{ padding: '20px 24px', background: '#0f1218' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <h1 style={{ color: '#f8fafc', fontSize: 22, fontWeight: 600, margin: 0 }}>{run.name.toLowerCase().replace(/[^a-z0-9]/g, '-')}</h1>
                <StatusBadge status={run.status} />
              </div>
              <div style={{ color: '#64748b', fontSize: 12, marginTop: 6 }}>
                ID: #{run.id} • Started {run.started_at || '2 mins ago'}
              </div>
            </div>
            <button style={{
              background: '#1e2432',
              border: '1px solid #374151',
              borderRadius: 6,
              color: '#e2e8f0',
              padding: '10px 20px',
              fontSize: 13,
              fontWeight: 500,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 8
            }}>
              ⏸ Pause Run
            </button>
          </div>
          
          {/* Metrics */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginTop: 20 }}>
            <div style={{
              background: '#151921',
              borderRadius: 8,
              padding: 16
            }}>
              <div style={{ color: '#64748b', fontSize: 11, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                ⚡ TOKENS (READ/WRITE)
              </div>
              <div style={{ color: '#f8fafc', fontSize: 24, fontWeight: 600 }}>
                {run.tokens_read?.toLocaleString() || '14,204'}
                <span style={{ color: '#64748b', fontSize: 16, margin: '0 8px' }}>/</span>
                <span style={{ color: '#94a3b8' }}>{run.tokens_write?.toLocaleString() || '2,105'}</span>
              </div>
            </div>
            <div style={{
              background: '#151921',
              borderRadius: 8,
              padding: 16
            }}>
              <div style={{ color: '#64748b', fontSize: 11, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                ⏱ DURATION
              </div>
              <div style={{ color: '#f8fafc', fontSize: 24, fontWeight: 600 }}>
                {run.duration || '00:48'}<span style={{ color: '#64748b', fontSize: 14 }}>s</span>
              </div>
            </div>
            <div style={{
              background: '#151921',
              borderRadius: 8,
              padding: 16
            }}>
              <div style={{ color: '#64748b', fontSize: 11, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                $ EST. COST
              </div>
              <div style={{ color: '#f8fafc', fontSize: 24, fontWeight: 600 }}>
                ${run.cost?.toFixed(3) || '0.042'}
              </div>
            </div>
          </div>
        </div>
        
        {/* Execution Plan */}
        <div style={{ flex: 1, padding: 24, overflowY: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ color: '#8b5cf6' }}>⊞</span>
              <span style={{ color: '#f8fafc', fontSize: 15, fontWeight: 600 }}>Execution Plan</span>
            </div>
            <div style={{
              background: '#1e2432',
              borderRadius: 6,
              padding: '6px 12px',
              color: '#22c55e',
              fontSize: 11,
              display: 'flex',
              alignItems: 'center',
              gap: 6
            }}>
              Auto-scroll: ON
            </div>
          </div>
          
          <div style={{ display: 'flex', gap: 16 }}>
            {run.steps.map(step => (
              <StepColumn 
                key={step.id} 
                step={step}
                onTaskClick={(task) => setSelectedTask(task)}
                selectedTaskId={selectedTask?.id}
              />
            ))}
          </div>
        </div>
      </div>
      
      {/* Inspector Panel */}
      {selectedTask && (
        <InspectorPanel 
          task={selectedTask} 
          run={run}
          onClose={() => setSelectedTask(null)}
        />
      )}
    </div>
  );
};

// Main App
export default function OrchestratorDashboard() {
  const [view, setView] = useState('dashboard'); // 'dashboard', 'routines', 'run-detail'
  const [expandedRun, setExpandedRun] = useState('8392-A');
  const [selectedTask, setSelectedTask] = useState(null);
  const [showNewRunModal, setShowNewRunModal] = useState(false);
  const [selectedRoutine, setSelectedRoutine] = useState(null);
  const [detailRun, setDetailRun] = useState(null);
  
  // Handle task click - navigate to run detail
  const handleTaskClick = (run, task) => {
    setDetailRun(run);
    setView('run-detail');
  };
  
  // Handle routine selection
  const handleSelectRoutine = (routine) => {
    setSelectedRoutine(routine);
    setShowNewRunModal(true);
  };
  
  // Render based on current view
  if (view === 'routines') {
    return (
      <RoutineLibrary 
        onSelectRoutine={handleSelectRoutine}
        onBack={() => setView('dashboard')}
      />
    );
  }
  
  if (view === 'run-detail' && detailRun) {
    return (
      <RunDetailView 
        run={detailRun}
        onBack={() => {
          setView('dashboard');
          setDetailRun(null);
        }}
      />
    );
  }
  
  // Dashboard view
  return (
    <div style={{
      minHeight: '100vh',
      background: '#0a0c10',
      fontFamily: "'Inter', system-ui, sans-serif",
      color: '#f8fafc'
    }}>
      {/* Global styles */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
      
      {/* Header */}
      <header style={{
        background: '#0f1218',
        borderBottom: '1px solid #1e2432',
        padding: '12px 24px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 32,
            height: 32,
            borderRadius: 6,
            background: 'linear-gradient(135deg, #8b5cf6, #06b6d4)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 16
          }}>
            ⊞
          </div>
          <span style={{ fontSize: 16, fontWeight: 600 }}>Orchestrator</span>
        </div>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <span style={{ cursor: 'pointer' }}>🔔</span>
          <button 
            onClick={() => setShowNewRunModal(true)}
            style={{
              background: '#8b5cf6',
              border: 'none',
              borderRadius: 6,
              color: '#fff',
              padding: '10px 16px',
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 6
            }}
          >
            + New Run
          </button>
        </div>
      </header>
      
      {/* Filters */}
      <div style={{
        background: '#0f1218',
        padding: '12px 24px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '1px solid #1e2432'
      }}>
        <div style={{ display: 'flex', gap: 12 }}>
          {['Status: All', 'Project: Core-API', 'Sort: Recency'].map((filter, i) => (
            <button key={i} style={{
              background: '#151921',
              border: '1px solid #252b38',
              borderRadius: 6,
              color: '#94a3b8',
              padding: '8px 14px',
              fontSize: 13,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 6
            }}>
              {filter} <span style={{ fontSize: 10 }}>▼</span>
            </button>
          ))}
        </div>
        
        <div style={{
          background: '#151921',
          border: '1px solid #252b38',
          borderRadius: 6,
          padding: '8px 14px',
          fontSize: 13,
          color: '#94a3b8'
        }}>
          Running: <span style={{ color: '#22c55e', fontWeight: 600 }}>3</span> / Total: 128
        </div>
      </div>
      
      {/* Run List */}
      <main style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {mockRuns.map(run => (
          run.id === expandedRun ? (
            <ExpandedRunCard 
              key={run.id} 
              run={run}
              onCollapse={() => setExpandedRun(null)}
              onTaskClick={(task) => handleTaskClick(run, task)}
              selectedTaskId={selectedTask?.id}
            />
          ) : (
            <CollapsedRunCard 
              key={run.id} 
              run={run}
              onExpand={() => setExpandedRun(run.id)}
            />
          )
        ))}
      </main>
      
      {/* New Run Modal */}
      {showNewRunModal && (
        <ConfigureNewRunModal 
          routine={selectedRoutine}
          onClose={() => {
            setShowNewRunModal(false);
            setSelectedRoutine(null);
          }}
          onStart={() => {
            setShowNewRunModal(false);
            setSelectedRoutine(null);
            setView('dashboard');
          }}
        />
      )}
    </div>
  );
}
