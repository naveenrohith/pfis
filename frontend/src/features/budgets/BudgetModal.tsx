import { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Dialog } from '@/components/ui/Dialog';
import { Button } from '@/components/ui/Button';
import { Input, Label, Select } from '@/components/ui/Input';
import { useToast } from '@/components/ui/Toast';
import { useAuth } from '@/features/auth/AuthContext';
import { api } from '@/lib/api';
import type { BudgetTracker, Category } from '@/lib/types';

interface BudgetModalProps {
  open: boolean;
  onClose: () => void;
  editing: BudgetTracker | null;
  categories: Category[];
  onSaved: () => void;
}

export function BudgetModal({ open, onClose, editing, categories, onSaved }: BudgetModalProps) {
  const { user } = useAuth();
  const { notify } = useToast();
  const [categoryId, setCategoryId] = useState('');
  const [limit, setLimit] = useState('');

  useEffect(() => {
    if (open) {
      setCategoryId(editing?.category_id ?? categories[0]?.id ?? '');
      setLimit(editing ? String(editing.limit) : '');
    }
  }, [open, editing, categories]);

  const mutation = useMutation({
    mutationFn: async () => {
      const amount = Number(limit);
      if (!Number.isFinite(amount) || amount <= 0) throw new Error('Enter a valid monthly limit.');
      if (editing) {
        await api.updateBudget(editing.id, amount);
      } else {
        if (!user) throw new Error('No active user.');
        if (!categoryId) throw new Error('Select a category.');
        await api.createBudget(user.id, categoryId, amount);
      }
    },
    onSuccess: () => {
      notify(editing ? 'Budget updated' : 'Budget created', 'success');
      onSaved();
    },
    onError: (err) => notify((err as Error).message, 'error'),
  });

  return (
    <Dialog open={open} onClose={onClose} title={editing ? 'Update budget' : 'Set budget'}>
      <form
        className="grid gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        <div className="grid gap-1.5">
          <Label htmlFor="budget-category">Category</Label>
          <Select
            id="budget-category"
            value={categoryId}
            disabled={!!editing}
            onChange={(e) => setCategoryId(e.target.value)}
          >
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.icon} {c.name}
              </option>
            ))}
          </Select>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="budget-limit">Monthly limit</Label>
          <Input
            id="budget-limit"
            type="number"
            min={1}
            step="any"
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            required
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
