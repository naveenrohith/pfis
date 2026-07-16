import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { DashboardUiProvider, useDashboardUi } from './DashboardUiContext';

function Harness() {
  const { activeWorkspace, activeSection, commandOpen, scrollTo } = useDashboardUi();
  return (
    <>
      <p data-testid="workspace">{activeWorkspace}</p>
      <p data-testid="section">{activeSection}</p>
      <p data-testid="command-state">{commandOpen ? 'open' : 'closed'}</p>
      <button type="button" onClick={() => scrollTo('transactions')}>
        Open transactions
      </button>
      {activeWorkspace === 'activity' && <div id="transactions">Transactions target</div>}
    </>
  );
}

describe('DashboardUiProvider navigation', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '#overview');
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('activates the owning workspace before navigating to a section', async () => {
    render(
      <DashboardUiProvider>
        <Harness />
      </DashboardUiProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Open transactions' }));

    await waitFor(() => expect(screen.getByTestId('workspace')).toHaveTextContent('activity'));
    expect(screen.getByTestId('section')).toHaveTextContent('transactions');
    expect(window.location.hash).toBe('#transactions');
    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalled());
  });

  it('restores a compatible workspace from a legacy hash', () => {
    window.history.replaceState(null, '', '#pipeline');
    render(
      <DashboardUiProvider>
        <Harness />
      </DashboardUiProvider>,
    );

    expect(screen.getByTestId('workspace')).toHaveTextContent('data');
    expect(screen.getByTestId('section')).toHaveTextContent('pipeline');
  });

  it('opens and closes the command palette from the global keyboard shortcut', () => {
    render(
      <DashboardUiProvider>
        <Harness />
      </DashboardUiProvider>,
    );

    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
    expect(screen.getByTestId('command-state')).toHaveTextContent('open');
    fireEvent.keyDown(document, { key: 'K', metaKey: true });
    expect(screen.getByTestId('command-state')).toHaveTextContent('closed');
  });
});
