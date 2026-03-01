import { Component } from 'react';
import type { ReactNode, ErrorInfo } from 'react';

interface Props {
  children: ReactNode;
  /** Optional label shown in the error message, e.g. "File List". */
  label?: string;
  /** Optional callback invoked when user presses Retry. */
  onRetry?: () => void;
}

interface State {
  hasError: boolean;
  errorMessage: string;
}

/**
 * Panel-level error boundary.
 * Catches render errors inside a review panel and shows a compact
 * error message with a Retry button that resets the boundary.
 */
export class PanelErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, errorMessage: '' };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, errorMessage: error.message || 'Unknown error' };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('PanelErrorBoundary caught:', error, info);
  }

  handleRetry = () => {
    this.props.onRetry?.();
    this.setState({ hasError: false, errorMessage: '' });
  };

  render() {
    if (this.state.hasError) {
      const subject = this.props.label ? `${this.props.label}` : 'This panel';
      return (
        <div className="rounded-md border border-status-failed/30 bg-status-failed/8 p-4">
          <p className="text-xs font-semibold text-status-failed">
            {subject} failed to load
          </p>
          <p className="mt-1 text-xs text-text-muted truncate" title={this.state.errorMessage}>
            {this.state.errorMessage}
          </p>
          <button
            type="button"
            onClick={this.handleRetry}
            className="mt-2 rounded border border-status-failed/40 px-2 py-1 text-xs text-status-failed hover:bg-status-failed/10 transition-colors"
          >
            Retry
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
