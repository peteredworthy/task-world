import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { PromptCopyBox } from '../../src/components/guidance/PromptCopyBox';

afterEach(cleanup);

describe('PromptCopyBox', () => {
  it('renders the label', () => {
    render(<PromptCopyBox label="System Prompt" content="hello world" />);
    expect(screen.getByText('System Prompt')).toBeInTheDocument();
  });

  it('renders the content', () => {
    render(<PromptCopyBox label="User Prompt" content="test content" />);
    expect(screen.getByText('test content')).toBeInTheDocument();
  });

  it('renders a copy button', () => {
    const { container } = render(<PromptCopyBox label="Prompt" content="data" />);
    const button = container.querySelector('button');
    expect(button).toBeInTheDocument();
    expect(button?.textContent).toContain('Copy');
  });
});
