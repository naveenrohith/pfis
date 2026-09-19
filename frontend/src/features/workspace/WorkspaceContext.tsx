import { createContext, useContext, useMemo, useState } from 'react';
import { useAuth } from '@/features/auth/AuthContext';
import { dateInputValueInTimezone } from '@/lib/format';

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
  const { user } = useAuth();
  const financialDate = dateInputValueInTimezone(user?.timezone ?? 'Asia/Kolkata');
  const [financialYear, financialMonth] = financialDate.split('-').map(Number);
  const [month, setMonth] = useState(financialMonth);
  const [year, setYear] = useState(financialYear);

  const value = useMemo<WorkspaceContextValue>(() => {
    const curMonth = financialMonth;
    const curYear = financialYear;
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
  }, [financialMonth, financialYear, month, year]);

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error('useWorkspace must be used within WorkspaceProvider');
  return ctx;
}
