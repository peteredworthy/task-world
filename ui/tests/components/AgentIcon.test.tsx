import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AgentIcon } from '../../src/components/AgentIcon';

describe('AgentIcon', () => {
  describe('icon types', () => {
    it('renders openhands icon', () => {
      const { container } = render(<AgentIcon icon="openhands" />);
      const svg = container.querySelector('svg');
      expect(svg).toBeInTheDocument();
      expect(svg).toHaveAttribute('stroke', 'currentColor');
      // Check for the hand path (characteristic of openhands icon)
      const path = svg?.querySelector('path');
      expect(path).toBeInTheDocument();
    });

    it('renders docker icon', () => {
      const { container } = render(<AgentIcon icon="docker" />);
      const svg = container.querySelector('svg');
      expect(svg).toBeInTheDocument();
      expect(svg).toHaveAttribute('fill', 'currentColor');
      // Docker icon has a specific path for the container shape
      const path = svg?.querySelector('path');
      expect(path).toBeInTheDocument();
    });

    it('renders cli icon', () => {
      const { container } = render(<AgentIcon icon="cli" />);
      const svg = container.querySelector('svg');
      expect(svg).toBeInTheDocument();
      expect(svg).toHaveAttribute('stroke', 'currentColor');
      // CLI icon has a terminal path
      const path = svg?.querySelector('path');
      expect(path).toBeInTheDocument();
    });

    it('renders external icon', () => {
      const { container } = render(<AgentIcon icon="external" />);
      const svg = container.querySelector('svg');
      expect(svg).toBeInTheDocument();
      expect(svg).toHaveAttribute('stroke', 'currentColor');
      // External/user icon has a person silhouette path
      const path = svg?.querySelector('path');
      expect(path).toBeInTheDocument();
    });

    it('renders none icon (slash through circle)', () => {
      const { container } = render(<AgentIcon icon="none" />);
      const svg = container.querySelector('svg');
      expect(svg).toBeInTheDocument();
      expect(svg).toHaveAttribute('stroke', 'currentColor');
      // None icon has a slash path
      const path = svg?.querySelector('path');
      expect(path).toBeInTheDocument();
    });

    it('renders default icon for unknown type', () => {
      const { container } = render(<AgentIcon icon="unknown-agent" />);
      const svg = container.querySelector('svg');
      expect(svg).toBeInTheDocument();
      expect(svg).toHaveAttribute('stroke', 'currentColor');
      // Default icon has a question mark path
      const path = svg?.querySelector('path');
      expect(path).toBeInTheDocument();
    });
  });

  describe('className prop', () => {
    it('applies default className when not provided', () => {
      const { container } = render(<AgentIcon icon="openhands" />);
      const svg = container.querySelector('svg');
      expect(svg).toHaveClass('h-4');
      expect(svg).toHaveClass('w-4');
      expect(svg).toHaveClass('shrink-0');
    });

    it('applies custom className when provided', () => {
      const { container } = render(<AgentIcon icon="openhands" className="h-6 w-6 text-blue-500" />);
      const svg = container.querySelector('svg');
      expect(svg).toHaveClass('h-6');
      expect(svg).toHaveClass('w-6');
      expect(svg).toHaveClass('text-blue-500');
      expect(svg).toHaveClass('shrink-0');
    });

    it('always includes shrink-0 in className', () => {
      const { container } = render(<AgentIcon icon="cli" className="h-8 w-8" />);
      const svg = container.querySelector('svg');
      expect(svg).toHaveClass('shrink-0');
    });
  });

  describe('accessibility', () => {
    it('includes aria-hidden attribute', () => {
      const { container } = render(<AgentIcon icon="openhands" />);
      const svg = container.querySelector('svg');
      expect(svg).toHaveAttribute('aria-hidden', 'true');
    });
  });
});
