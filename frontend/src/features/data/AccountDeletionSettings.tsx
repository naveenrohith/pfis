import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Input, Label } from '@/components/ui/Input';
import { useToast } from '@/components/ui/Toast';
import { useAuth } from '@/features/auth/AuthContext';

export function AccountDeletionSettings() {
  const { user, deleteAccount } = useAuth();
  const { notify } = useToast();
  const [open, setOpen] = useState(false);
  const [confirmation, setConfirmation] = useState('');
  const expected = user ? `DELETE ${user.email}` : '';
  const deletion = useMutation({
    mutationFn: () => deleteAccount(confirmation),
    onSuccess: () => notify('Your PFIS account was deleted', 'success'),
    onError: (error) => notify((error as Error).message, 'error'),
  });

  function close() {
    if (deletion.isPending) return;
    setOpen(false);
    setConfirmation('');
    deletion.reset();
  }

  return (
    <>
      <Card className="border border-danger/30">
        <CardHeader className="border-b border-danger/20">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 rounded-lg bg-danger/10 p-2 text-danger">
              <Trash2 aria-hidden="true" className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <CardTitle className="text-pretty">Permanently delete your PFIS account</CardTitle>
              <CardDescription className="mt-1 max-w-2xl text-pretty">
                Remove your private financial workspace, source evidence, settings, login
                identities, sessions, and connector grants. This action cannot be undone.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-5 sm:pt-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
              Shared household annotations remain auditable to other members under a non-login
              “Deleted participant” label. PFIS transfers an owned shared household before closing
              your membership.
            </p>
            <Button
              variant="danger"
              className="w-full shrink-0 sm:w-auto"
              onClick={() => setOpen(true)}
            >
              Delete my account
            </Button>
          </div>
        </CardContent>
      </Card>

      <Dialog
        open={open}
        onClose={close}
        title="Delete your account permanently?"
        description="You must have signed in within the last 15 minutes. Sign in again first if PFIS asks you to reauthenticate."
      >
        <div className="space-y-4">
          <div className="rounded-lg bg-danger/10 p-4 text-sm leading-6 text-foreground">
            PFIS will ask Google to revoke Gmail access, end every PFIS session, and remove all
            private records. Cleared data cannot be restored from PFIS.
          </div>
          <div className="space-y-2">
            <Label htmlFor="account-deletion-confirmation">
              Type <span className="font-extrabold">{expected}</span> to continue
            </Label>
            <Input
              id="account-deletion-confirmation"
              name="account-deletion-confirmation"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              autoComplete="off"
              spellCheck={false}
              aria-describedby="account-deletion-help account-deletion-error"
            />
            <p id="account-deletion-help" className="text-xs text-muted-foreground">
              Capitalization and your full sign-in email must match exactly.
            </p>
          </div>
        </div>
        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button
            data-dialog-initial-focus
            variant="ghost"
            onClick={close}
            disabled={deletion.isPending}
          >
            Keep my account
          </Button>
          <Button
            variant="danger"
            onClick={() => deletion.mutate()}
            disabled={confirmation !== expected || deletion.isPending}
          >
            {deletion.isPending ? 'Deleting account…' : 'Permanently delete account'}
          </Button>
        </div>
        {deletion.isError ? (
          <p
            id="account-deletion-error"
            role="alert"
            className="mt-3 text-sm font-bold text-danger"
          >
            {deletion.error.message}
          </p>
        ) : null}
      </Dialog>
    </>
  );
}
