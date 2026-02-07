import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WaitingIndicator } from '../../src/components/guidance/WaitingIndicator';

afterEach(cleanup);

describe('WaitingIndicator', () => {
  it('renders waiting text', () => {
    render(<WaitingIndicator startedAt={new Date().toISOString()} />);
    expect(screen.getByText('Waiting for agent to submit work...')).toBeInTheDocument();
  });

  it('renders cancel button when onCancel is provided', () => {
    const { container } = render(<WaitingIndicator startedAt={new Date().toISOString()} onCancel={() => {}} />);
    expect(within(container).getByText('Cancel')).toBeInTheDocument();
  });

  it('does not render cancel button when onCancel is omitted', () => {
    const { container } = render(<WaitingIndicator startedAt={new Date().toISOString()} />);
    expect(within(container).queryByText('Cancel')).not.toBeInTheDocument();
  });

  it('calls onCancel when cancel button is clicked', async () => {
    const onCancel = vi.fn();
    const { container } = render(<WaitingIndicator startedAt={new Date().toISOString()} onCancel={onCancel} />);
    await userEvent.click(within(container).getByText('Cancel'));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
