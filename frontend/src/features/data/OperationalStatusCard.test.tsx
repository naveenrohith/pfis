import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OperationalStatusCard } from './OperationalStatusCard';

const mocks = vi.hoisted(() => ({ health: vi.fn() }));

vi.mock('@/features/workspace/queries', () => ({
  useOperationalHealth: mocks.health,
}));

describe('OperationalStatusCard', () => {
  beforeEach(() => {
    mocks.health.mockReturnValue({
      isLoading: false,
      isError: false,
      data: {
        status: 'needs_repair',
        status_reasons: ['ledger_currency_needs_repair'],
        data_warnings: [],
      },
    });
  });

  it('explains deployment-wide ledger currency repair without promising an unsupported action', () => {
    const onNavigate = vi.fn();
    render(<OperationalStatusCard onNavigate={onNavigate} />);

    const serviceChecks = screen.getByRole('region', { name: 'Service checks' });
    expect(serviceChecks).toHaveTextContent(
      "PFIS found stored records whose currency does not match their owner's ledger currency.",
    );
    expect(serviceChecks).toHaveTextContent(
      'This deployment requires operator repair; self-service repair is not available.',
    );
    expect(serviceChecks.querySelector('button')).not.toBeInTheDocument();
    expect(onNavigate).not.toHaveBeenCalled();
  });
});
