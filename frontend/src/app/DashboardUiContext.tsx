import { createContext, useContext, useMemo, useState } from 'react';

export interface CategoryDrill {
  categoryId: string;
  label: string;
}

interface DashboardUiContextValue {
  categoryDrill: CategoryDrill | null;
  setCategoryDrill: (drill: CategoryDrill | null) => void;
  explorerSearch: string;
  setExplorerSearch: (value: string) => void;
  focusedReviewId: string | null;
  focusReview: (id: string | null) => void;
  scrollTo: (id: string) => void;
}

const DashboardUiContext = createContext<DashboardUiContextValue | null>(null);

export function DashboardUiProvider({ children }: { children: React.ReactNode }) {
  const [categoryDrill, setCategoryDrill] = useState<CategoryDrill | null>(null);
  const [explorerSearch, setExplorerSearch] = useState('');
  const [focusedReviewId, setFocusedReviewId] = useState<string | null>(null);

  const value = useMemo<DashboardUiContextValue>(
    () => ({
      categoryDrill,
      setCategoryDrill,
      explorerSearch,
      setExplorerSearch,
      focusedReviewId,
      focusReview: (id) => {
        setFocusedReviewId(id);
        if (id) {
          document.getElementById('review')?.scrollIntoView({ behavior: 'smooth' });
        }
      },
      scrollTo: (id) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' }),
    }),
    [categoryDrill, explorerSearch, focusedReviewId],
  );

  return <DashboardUiContext.Provider value={value}>{children}</DashboardUiContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useDashboardUi(): DashboardUiContextValue {
  const ctx = useContext(DashboardUiContext);
  if (!ctx) throw new Error('useDashboardUi must be used within DashboardUiProvider');
  return ctx;
}
