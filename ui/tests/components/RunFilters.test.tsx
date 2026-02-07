import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RunFilters } from '../../src/components/dashboard/RunFilters';

afterEach(cleanup);

describe('RunFilters', () => {
  const defaultProps = {
    statusFilter: '',
    onStatusChange: vi.fn(),
    projectFilter: '',
    onProjectChange: vi.fn(),
    recencyFilter: '',
    onRecencyChange: vi.fn(),
  };

  it('renders all status options', () => {
    const { container } = render(<RunFilters {...defaultProps} />);
    const selects = container.querySelectorAll('select');
    const statusSelect = selects[0];
    const options = within(statusSelect as HTMLElement).getAllByRole('option');
    const labels = options.map(o => o.textContent);
    expect(labels).toContain('All statuses');
    expect(labels).toContain('Draft');
    expect(labels).toContain('Queued');
    expect(labels).toContain('Active');
    expect(labels).toContain('Paused');
    expect(labels).toContain('Completed');
    expect(labels).toContain('Failed');
  });

  it('renders all recency options', () => {
    const { container } = render(<RunFilters {...defaultProps} />);
    const selects = container.querySelectorAll('select');
    const recencySelect = selects[1];
    const options = within(recencySelect as HTMLElement).getAllByRole('option');
    const labels = options.map(o => o.textContent);
    expect(labels).toContain('All time');
    expect(labels).toContain('Last hour');
    expect(labels).toContain('Last 4 hours');
    expect(labels).toContain('Last 24 hours');
    expect(labels).toContain('Last week');
  });

  it('calls onStatusChange when status is selected', async () => {
    const onStatusChange = vi.fn();
    render(<RunFilters {...defaultProps} onStatusChange={onStatusChange} />);
    const selects = screen.getAllByRole('combobox');
    await userEvent.selectOptions(selects[0], 'active');
    expect(onStatusChange).toHaveBeenCalledWith('active');
  });

  it('calls onRecencyChange when recency is selected', async () => {
    const onRecencyChange = vi.fn();
    render(<RunFilters {...defaultProps} onRecencyChange={onRecencyChange} />);
    const selects = screen.getAllByRole('combobox');
    await userEvent.selectOptions(selects[1], '1h');
    expect(onRecencyChange).toHaveBeenCalledWith('1h');
  });

  it('calls onProjectChange when text is typed', async () => {
    const onProjectChange = vi.fn();
    render(<RunFilters {...defaultProps} onProjectChange={onProjectChange} />);
    const input = screen.getByPlaceholderText('Filter by project...');
    await userEvent.type(input, 'x');
    expect(onProjectChange).toHaveBeenCalledWith('x');
  });
});
