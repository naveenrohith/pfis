import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { DataConfidenceDimension } from '@/lib/types';
import { DataConfidenceLedger } from './DataConfidenceLedger';

const dimensions: DataConfidenceDimension[] = [
  {
    key: 'coverage',
    label: 'History coverage',
    score: 25,
    status: 'limited',
    summary: 'Comparisons have only a short observed history.',
    evidence: [{ label: 'Active periods', value: '1 of 4 needed' }],
    remediation_label: 'Import more history',
    remediation_target: 'inbox',
  },
  {
    key: 'parsing',
    label: 'Parsing quality',
    score: 94,
    status: 'strong',
    summary: 'Amounts and merchant labels are consistently resolved.',
    evidence: [{ label: 'Field confidence', value: '96%' }],
  },
];

describe('DataConfidenceLedger', () => {
  it('shows evidence and routes weak dimensions to their exact remediation', async () => {
    const onNavigate = vi.fn();
    render(<DataConfidenceLedger dimensions={dimensions} onNavigate={onNavigate} />);

    expect(screen.getByText('What PFIS can verify')).toBeInTheDocument();
    expect(screen.getByText('1 of 4 needed')).toBeInTheDocument();
    expect(screen.getByLabelText('History coverage score 25 out of 100')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /parsing/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /import more history/i }));
    expect(onNavigate).toHaveBeenCalledWith('inbox');
  });
});
