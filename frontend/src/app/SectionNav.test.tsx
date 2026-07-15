import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { DashboardUiProvider, useDashboardUi } from './DashboardUiContext';
import { SectionNav } from './SectionNav';

function StateProbe() {
  const { activeWorkspace, quickAddOpen } = useDashboardUi();
  return (
    <>
      <span data-testid="workspace">{activeWorkspace}</span>
      <span data-testid="quick-add">{String(quickAddOpen)}</span>
    </>
  );
}

function renderNavigation() {
  Element.prototype.scrollIntoView = vi.fn();
  return render(
    <DashboardUiProvider>
      <SectionNav />
      <StateProbe />
    </DashboardUiProvider>,
  );
}

describe('responsive workspace navigation', () => {
  it('renders five direct mobile workspace destinations', () => {
    renderNavigation();
    const navigation = screen.getByRole('navigation', { name: 'Primary financial destinations' });
    expect(within(navigation).getAllByRole('button')).toHaveLength(5);
    fireEvent.click(within(navigation).getByRole('button', { name: /Plan/ }));
    expect(screen.getByTestId('workspace')).toHaveTextContent('plan');
    expect(window.location.hash).toBe('#analytics');
  });

  it('opens quick add from the mobile floating action', () => {
    renderNavigation();
    fireEvent.click(screen.getByRole('button', { name: 'Quick add activity' }));
    expect(screen.getByTestId('quick-add')).toHaveTextContent('true');
  });
});
