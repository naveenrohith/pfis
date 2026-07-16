import { createContext, useContext, useMemo, useState } from 'react';

interface WorkspaceContextValue {
  month: number;
  year: number;
  isCurrentMonth: boolean;
  goPrev: () => void;
  goNext: () => void;
  goToday: () => void;
  setMonthYear: (month: number, year: number) => void;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());

  const value = useMemo<WorkspaceContextValue>(() => {
    const today = new Date();
    const curMonth = today.getMonth() + 1;
    const curYear = today.getFullYear();
    const isCurrentMonth = month === curMonth && year === curYear;

    return {
      month,
      year,
      isCurrentMonth,
      goPrev: () => {
        if (month === 1) {
          setMonth(12);
          setYear((y) => y - 1);
        } else {
          setMonth((m) => m - 1);
        }
      },
      goNext: () => {
        if (isCurrentMonth) return;
        if (month === 12) {
          setMonth(1);
          setYear((y) => y + 1);
        } else {
          setMonth((m) => m + 1);
        }
      },
      goToday: () => {
        setMonth(curMonth);
        setYear(curYear);
      },
      setMonthYear: (m, y) => {
        setMonth(m);
        setYear(y);
      },
    };
  }, [month, year]);

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error('useWorkspace must be used within WorkspaceProvider');
  return ctx;
}
