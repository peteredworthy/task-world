import { describe, it, expect } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { ChecklistTable } from '../../src/components/detail/ChecklistTable';
import type { ChecklistItemSchema } from '../../src/types';

function makeItem(overrides: Partial<ChecklistItemSchema> & { req_id: string }): ChecklistItemSchema {
  return {
    desc: 'Default requirement',
    priority: 'expected',
    status: 'open',
    note: null,
    grade: null,
    grade_reason: null,
    ...overrides,
  };
}

describe('ChecklistTable', () => {
  it('renders "No checklist items" when items array is empty', () => {
    cleanup();
    render(<ChecklistTable items={[]} />);
    expect(screen.getByText('No checklist items')).toBeInTheDocument();
  });

  it('does not render a table when items array is empty', () => {
    cleanup();
    render(<ChecklistTable items={[]} />);
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('renders a table when items are provided', () => {
    cleanup();
    const items = [makeItem({ req_id: 'R1', desc: 'First requirement' })];
    render(<ChecklistTable items={items} />);
    expect(screen.getByRole('table')).toBeInTheDocument();
  });

  it('renders a row for each item', () => {
    cleanup();
    const items = [
      makeItem({ req_id: 'R1', desc: 'First requirement' }),
      makeItem({ req_id: 'R2', desc: 'Second requirement' }),
      makeItem({ req_id: 'R3', desc: 'Third requirement' }),
    ];
    render(<ChecklistTable items={items} />);
    expect(screen.getByText('First requirement')).toBeInTheDocument();
    expect(screen.getByText('Second requirement')).toBeInTheDocument();
    expect(screen.getByText('Third requirement')).toBeInTheDocument();
  });

  it('renders requirement text in each row', () => {
    cleanup();
    const items = [makeItem({ req_id: 'R1', desc: 'Must handle edge cases' })];
    render(<ChecklistTable items={items} />);
    expect(screen.getByText('Must handle edge cases')).toBeInTheDocument();
  });

  it('renders priority badge for each item', () => {
    cleanup();
    const items = [
      makeItem({ req_id: 'R1', desc: 'Critical item', priority: 'critical' }),
      makeItem({ req_id: 'R2', desc: 'Nice item', priority: 'nice' }),
    ];
    render(<ChecklistTable items={items} />);
    expect(screen.getByText('critical')).toBeInTheDocument();
    expect(screen.getByText('nice')).toBeInTheDocument();
  });

  it('renders grade badge when grade is present', () => {
    cleanup();
    const items = [makeItem({ req_id: 'R1', desc: 'Graded item', grade: 'A' })];
    render(<ChecklistTable items={items} />);
    expect(screen.getByText('A')).toBeInTheDocument();
  });

  it('renders a dash when grade is absent', () => {
    cleanup();
    const items = [makeItem({ req_id: 'R1', desc: 'No grade item', grade: null })];
    render(<ChecklistTable items={items} />);
    expect(screen.getByText('-')).toBeInTheDocument();
  });

  it('shows grade_reason in a tooltip element when present', () => {
    cleanup();
    const items = [
      makeItem({ req_id: 'R1', desc: 'Graded item', grade: 'B', grade_reason: 'Missing edge case handling' }),
    ];
    render(<ChecklistTable items={items} />);
    const gradeWrapper = screen.getByTitle('Missing edge case handling');
    expect(gradeWrapper).toBeInTheDocument();
    expect(screen.getByText('Missing edge case handling')).toBeInTheDocument();
  });

  it('does not show tooltip element when grade_reason is absent', () => {
    cleanup();
    const items = [makeItem({ req_id: 'R1', desc: 'No reason', grade: 'A', grade_reason: null })];
    render(<ChecklistTable items={items} />);
    expect(screen.getByText('A')).toBeInTheDocument();
    const gradeContainer = screen.getByText('A').parentElement;
    expect(gradeContainer).not.toHaveAttribute('title');
  });

  it('renders status icon as SVG for each item', () => {
    cleanup();
    const items = [
      makeItem({ req_id: 'R1', desc: 'Done item', status: 'done' }),
      makeItem({ req_id: 'R2', desc: 'Blocked item', status: 'blocked' }),
      makeItem({ req_id: 'R3', desc: 'Open item', status: 'open' }),
    ];
    const { container } = render(<ChecklistTable items={items} />);
    const svgs = container.querySelectorAll('svg');
    expect(svgs.length).toBe(3);
  });

  it('renders note text when present', () => {
    cleanup();
    const items = [makeItem({ req_id: 'R1', desc: 'With note', note: 'Some important note' })];
    render(<ChecklistTable items={items} />);
    expect(screen.getByText('Some important note')).toBeInTheDocument();
  });
});
