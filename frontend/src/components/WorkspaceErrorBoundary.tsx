import { Component, type ErrorInfo, type ReactNode } from 'react';
import { RefreshCcw, TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/Button';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class WorkspaceErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('PFIS workspace render failed', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <section
        role="alert"
        className="mx-auto my-12 max-w-2xl rounded-2xl border border-danger/25 bg-card p-6 sm:p-8"
      >
        <span className="grid h-11 w-11 place-items-center rounded-xl bg-danger/10 text-danger">
          <TriangleAlert className="h-5 w-5" aria-hidden="true" />
        </span>
        <h1 className="mt-5 text-2xl font-extrabold tracking-[-0.035em]">
          This workspace could not finish loading.
        </h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Your financial data was not changed. Retry the current application version; if the issue
          continues, the error remains visible instead of leaving a blank page.
        </p>
        <Button className="mt-5" onClick={() => window.location.reload()}>
          <RefreshCcw className="h-4 w-4" /> Reload workspace
        </Button>
        <details className="mt-5 text-xs text-muted-foreground">
          <summary className="focus-ring cursor-pointer rounded py-2 font-bold">
            Technical detail
          </summary>
          <p className="mt-1 break-words">{this.state.error.message}</p>
        </details>
      </section>
    );
  }
}
