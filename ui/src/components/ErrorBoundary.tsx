import { Component } from 'react';
import type { ReactNode, ErrorInfo } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  crashCount: number;
  firstCrashTime: number;
  showFullError: boolean;
}

const CRASH_WINDOW_MS = 30_000;
const MAX_RAPID_CRASHES = 5;
const AUTO_RETRY_MS = 3_000;

export class ErrorBoundary extends Component<Props, State> {
  private retryTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, crashCount: 0, firstCrashTime: 0, showFullError: false };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    void error;
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info);

    const now = Date.now();
    const outsideWindow = now - this.state.firstCrashTime > CRASH_WINDOW_MS;
    const newCount = outsideWindow ? 1 : this.state.crashCount + 1;
    const firstTime = outsideWindow ? now : this.state.firstCrashTime;

    if (newCount >= MAX_RAPID_CRASHES) {
      this.setState({ crashCount: newCount, firstCrashTime: firstTime, showFullError: true });
      return;
    }

    this.setState({ crashCount: newCount, firstCrashTime: firstTime, showFullError: false });

    this.retryTimer = setTimeout(() => {
      this.setState({ hasError: false });
    }, AUTO_RETRY_MS);
  }

  componentWillUnmount() {
    if (this.retryTimer) clearTimeout(this.retryTimer);
  }

  render() {
    if (this.state.hasError) {
      if (this.state.showFullError) {
        return (
          <div className="min-h-screen flex items-center justify-center bg-bg-primary">
            <div className="text-center">
              <h1 className="text-2xl font-bold text-text-primary mb-2">Something went wrong</h1>
              <p className="text-text-muted mb-4">The application crashed repeatedly. Please reload to try again.</p>
              <button
                onClick={() => window.location.reload()}
                className="px-4 py-2 text-sm font-medium text-white bg-accent-purple rounded-md hover:bg-accent-purple/80 transition-colors"
              >
                Reload
              </button>
            </div>
          </div>
        );
      }

      return (
        <div className="min-h-screen flex items-center justify-center bg-bg-primary">
          <div className="flex items-center gap-3 px-4 py-3 rounded-lg bg-status-paused/10 border border-status-paused/30">
            <span className="inline-block h-2 w-2 rounded-full bg-status-paused animate-pulse" />
            <span className="text-sm text-status-paused font-medium">Connection issue — retrying...</span>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
