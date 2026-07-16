import { useEffect, useState } from 'react';
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { CalendarClock, GripVertical, RotateCcw, SlidersHorizontal } from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Dialog } from '@/components/ui/Dialog';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Input';
import { useToast } from '@/components/ui/Toast';
import { useAuth } from '@/features/auth/AuthContext';
import { queryKeys, useDashboardPreferences } from '@/features/workspace/queries';
import { api } from '@/lib/api';
import type { DashboardWidget, GuidancePeriod } from '@/lib/types';
import { useTheme } from '@/components/theme/ThemeProvider';

const LABELS: Record<string, string> = {
  income: 'Income',
  spent: 'Spent',
  savings: 'Savings',
  'net-cash-flow': 'Net cash flow',
  attention: 'Attention queue',
  'next-action': 'Next best action',
};

export function CustomizeDashboardDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { user } = useAuth();
  const preferences = useDashboardPreferences();
  const [widgets, setWidgets] = useState<DashboardWidget[]>([]);
  const [density, setDensity] = useState<'comfortable' | 'compact'>('comfortable');
  const [themePreference, setThemePreference] = useState<'system' | 'light' | 'dark'>('system');
  const [briefingCadence, setBriefingCadence] = useState<GuidancePeriod>('daily');
  const { setTheme } = useTheme();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  useEffect(() => {
    if (preferences.data) {
      setWidgets(preferences.data.widgets);
      setDensity(preferences.data.density);
      setThemePreference(preferences.data.theme);
      setBriefingCadence(preferences.data.briefing_cadence);
    }
  }, [preferences.data]);

  const save = useMutation({
    mutationFn: () => {
      if (!user) throw new Error('Sign in to customize your dashboard');
      return api.updateDashboardPreferences(user.id, {
        layout_version: 1,
        widgets,
        density,
        theme: themePreference,
        briefing_cadence: briefingCadence,
      });
    },
    onSuccess: (data) => {
      if (user) queryClient.setQueryData(queryKeys.dashboardPreferences(user.id), data);
      setTheme(
        data.theme === 'system'
          ? window.matchMedia('(prefers-color-scheme: dark)').matches
            ? 'dark'
            : 'light'
          : data.theme,
      );
      notify('Dashboard preferences saved', 'success');
      onClose();
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });

  const reset = useMutation({
    mutationFn: () => {
      if (!user) throw new Error('Sign in to reset your dashboard');
      return api.resetDashboardPreferences(user.id);
    },
    onSuccess: (data) => {
      if (user) queryClient.setQueryData(queryKeys.dashboardPreferences(user.id), data);
      setWidgets(data.widgets);
      setDensity(data.density);
      setThemePreference(data.theme);
      setBriefingCadence(data.briefing_cadence);
      setTheme(
        data.theme === 'system'
          ? window.matchMedia('(prefers-color-scheme: dark)').matches
            ? 'dark'
            : 'light'
          : data.theme,
      );
      notify('Dashboard reset', 'success');
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    setWidgets((items) => {
      const oldIndex = items.findIndex((item) => item.id === active.id);
      const newIndex = items.findIndex((item) => item.id === over.id);
      return arrayMove(items, oldIndex, newIndex);
    });
  }

  return (
    <Dialog open={open} onClose={onClose} title="Customize Home" className="max-w-xl">
      <div className="grid gap-4">
        <div className="flex items-start gap-3 rounded-xl border border-primary/15 bg-primary/5 p-3">
          <SlidersHorizontal className="mt-0.5 h-4 w-4 text-primary" />
          <p className="text-sm text-muted-foreground">
            Drag with a pointer or focus a handle and use the keyboard to reorder. Preferences
            follow your account across devices.
          </p>
        </div>
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext
            items={widgets.map((widget) => widget.id)}
            strategy={verticalListSortingStrategy}
          >
            <div className="grid gap-2">
              {widgets.map((widget) => (
                <SortableWidget
                  key={widget.id}
                  widget={widget}
                  onChange={(next) =>
                    setWidgets((items) => items.map((item) => (item.id === next.id ? next : item)))
                  }
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
        <label className="grid gap-1.5">
          <span className="text-xs font-bold uppercase tracking-wide text-muted-foreground">
            Density
          </span>
          <Select
            value={density}
            onChange={(event) => setDensity(event.target.value as typeof density)}
          >
            <option value="comfortable">Comfortable</option>
            <option value="compact">Compact</option>
          </Select>
        </label>
        <div className="grid gap-3 rounded-xl bg-muted/45 p-4 sm:grid-cols-[auto_1fr]">
          <CalendarClock className="mt-0.5 h-4 w-4 text-primary" aria-hidden="true" />
          <label className="grid gap-1.5">
            <span className="text-xs font-bold uppercase tracking-wide text-muted-foreground">
              Financial briefing rhythm
            </span>
            <Select
              value={briefingCadence}
              onChange={(event) => setBriefingCadence(event.target.value as GuidancePeriod)}
            >
              <option value="daily">Daily pulse</option>
              <option value="weekly">Weekly perspective</option>
              <option value="monthly">Monthly review</option>
            </Select>
            <span className="text-xs leading-5 text-muted-foreground">
              Changes how PFIS frames your deterministic in-app brief. It does not send external
              notifications or share activity data.
            </span>
          </label>
        </div>
        <label className="grid gap-1.5">
          <span className="text-xs font-bold uppercase tracking-wide text-muted-foreground">
            Theme
          </span>
          <Select
            value={themePreference}
            onChange={(event) => setThemePreference(event.target.value as typeof themePreference)}
          >
            <option value="system">System</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </Select>
        </label>
        <div className="flex flex-wrap justify-between gap-2">
          <Button variant="ghost" onClick={() => reset.mutate()} disabled={reset.isPending}>
            <RotateCcw className="h-4 w-4" /> Reset defaults
          </Button>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={() => save.mutate()} disabled={save.isPending}>
              {save.isPending ? 'Saving…' : 'Save layout'}
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  );
}

function SortableWidget({
  widget,
  onChange,
}: {
  widget: DashboardWidget;
  onChange: (widget: DashboardWidget) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: widget.id,
  });
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`flex items-center gap-3 rounded-xl border border-border bg-card p-3 ${isDragging ? 'z-10 shadow-xl' : ''}`}
    >
      <button
        type="button"
        className="cursor-grab rounded-lg p-1 text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={`Reorder ${LABELS[widget.id] ?? widget.id}`}
        {...attributes}
        {...listeners}
      >
        <GripVertical className="h-4 w-4" />
      </button>
      <label className="flex min-w-0 flex-1 items-center gap-2 text-sm font-semibold">
        <input
          type="checkbox"
          checked={widget.visible}
          onChange={(event) => onChange({ ...widget, visible: event.target.checked })}
          className="h-4 w-4 accent-[hsl(var(--primary))]"
        />
        <span className="truncate">{LABELS[widget.id] ?? widget.id}</span>
      </label>
      <Select
        className="h-8 w-28"
        value={widget.size}
        onChange={(event) =>
          onChange({ ...widget, size: event.target.value as DashboardWidget['size'] })
        }
        aria-label={`Size for ${LABELS[widget.id] ?? widget.id}`}
      >
        <option value="small">Small</option>
        <option value="medium">Medium</option>
        <option value="large">Large</option>
      </Select>
    </div>
  );
}
