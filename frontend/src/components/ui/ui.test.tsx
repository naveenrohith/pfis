import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Badge } from '@/components/ui/Badge';
import { Button, ButtonLink } from '@/components/ui/Button';

describe('UI primitives', () => {
  it('renders a button with its label', () => {
    render(<Button>Sync inbox</Button>);
    expect(screen.getByRole('button', { name: 'Sync inbox' })).toBeInTheDocument();
  });

  it('renders navigation actions as links', () => {
    render(<ButtonLink href="/api/auth/gmail/connect">Reconnect Gmail</ButtonLink>);
    expect(screen.getByRole('link', { name: 'Reconnect Gmail' })).toHaveAttribute(
      'href',
      '/api/auth/gmail/connect',
    );
  });

  it('renders a badge', () => {
    render(<Badge variant="success">Processed</Badge>);
    expect(screen.getByText('Processed')).toBeInTheDocument();
  });
});
