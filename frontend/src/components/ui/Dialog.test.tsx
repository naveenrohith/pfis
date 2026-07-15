import { useState } from 'react';
import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Button } from './Button';
import { Dialog } from './Dialog';

function DialogHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>Open budget</Button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Set budget">
        <label htmlFor="limit">Monthly limit</label>
        <input id="limit" />
        <Button>Save budget</Button>
      </Dialog>
    </>
  );
}

describe('Dialog accessibility', () => {
  beforeEach(() => {
    document.body.style.cssText = '';
    document.documentElement.style.cssText = '';
    document.documentElement.removeAttribute('data-base-ui-scroll-locked');
  });

  it('labels the dialog, focuses its first form control, and locks page scroll', async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    await user.click(screen.getByRole('button', { name: 'Open budget' }));

    const dialog = screen.getByRole('dialog', { name: 'Set budget' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    await waitFor(() => expect(screen.getByLabelText('Monthly limit')).toHaveFocus());
    expect(document.body.style.overflow).toBe('hidden');
  });

  it('wraps keyboard focus inside the dialog', async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    await user.click(screen.getByRole('button', { name: 'Open budget' }));

    const close = screen.getByRole('button', { name: 'Close dialog' });
    const save = screen.getByRole('button', { name: 'Save budget' });
    save.focus();
    await user.tab();
    await waitFor(() => expect(close).toHaveFocus());

    await user.tab({ shift: true });
    await waitFor(() => expect(save).toHaveFocus());
  });

  it('closes on Escape and restores focus to the trigger', async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    const trigger = screen.getByRole('button', { name: 'Open budget' });
    trigger.focus();
    await user.click(trigger);
    await user.keyboard('{Escape}');

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
      expect(document.body.style.overflow).toBe('');
    });
  });
});
