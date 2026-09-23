import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { DashboardUiProvider, useDashboardUi } from './DashboardUiContext';

function Harness() {
  const { activeWorkspace, activeSection, commandOpen, scrollTo } = useDashboardUi();
  const [cardsReady, setCardsReady] = useState(false);
  return (
    <>
      <p data-testid="workspace">{activeWorkspace}</p>
      <p data-testid="section">{activeSection}</p>
      <p data-testid="command-state">{commandOpen ? 'open' : 'closed'}</p>
      <button type="button" onClick={() => scrollTo('transactions')}>
        Open transactions
      </button>
      <button
        type="button"
        onClick={() => {
          scrollTo('cards', 'push');
          window.setTimeout(() => setCardsReady(true), 30);
        }}
      >
        Open card accounts
      </button>
      {activeWorkspace === 'activity' && <div id="transactions">Transactions target</div>}
      {activeWorkspace === 'plan' && activeSection === 'cards' && cardsReady ? (
        <div id="cards">Cards target</div>
      ) : null}
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

  it('keeps user-opened detail navigation in browser history', () => {
    window.history.replaceState(null, '', '#obligations');
    const initialHistoryLength = window.history.length;
    render(
      <DashboardUiProvider>
        <Harness />
      </DashboardUiProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Open card accounts' }));

    expect(window.location.hash).toBe('#cards');
    expect(window.history.length).toBe(initialHistoryLength + 1);
  });

  it('waits for a lazy destination anchor before scrolling', async () => {
    window.history.replaceState(null, '', '#obligations');
    const scrolledTargets: string[] = [];
    Element.prototype.scrollIntoView = function () {
      scrolledTargets.push((this as HTMLElement).id);
    };
    render(
      <DashboardUiProvider>
        <Harness />
      </DashboardUiProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Open card accounts' }));

    await waitFor(() => expect(screen.getByText('Cards target')).toBeInTheDocument());
    await waitFor(() => expect(scrolledTargets).toContain('cards'));
  });

  it('restores the active Plan stage when browser Back changes the hash', async () => {
    window.history.pushState(null, '', '#obligations');
    window.history.pushState(null, '', '#cards');
    render(
      <DashboardUiProvider>
        <Harness />
      </DashboardUiProvider>,
    );

    window.history.back();

    await waitFor(() => {
      expect(window.location.hash).toBe('#obligations');
      expect(screen.getByTestId('workspace')).toHaveTextContent('plan');
      expect(screen.getByTestId('section')).toHaveTextContent('obligations');
    });
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
