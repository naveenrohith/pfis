import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';

describe('UI primitives', () => {
  it('renders a button with its label', () => {
    render(<Button>Sync inbox</Button>);
    expect(screen.getByRole('button', { name: 'Sync inbox' })).toBeInTheDocument();
  });

  it('renders a badge', () => {
    render(<Badge variant="success">Processed</Badge>);
    expect(screen.getByText('Processed')).toBeInTheDocument();
  });
});
