import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import {
  DEFAULT_WORKSPACE,
  dashboardSection,
  firstSectionForWorkspace,
  sectionFromHash,
  workspaceForSection,
  type DashboardSectionId,
  type WorkspaceId,
} from './workspaceNavigation';

export interface CategoryDrill {
  categoryId: string;
  label: string;
}

interface DashboardUiContextValue {
  activeWorkspace: WorkspaceId;
  activeSection: DashboardSectionId;
  openWorkspace: (workspace: WorkspaceId) => void;
  categoryDrill: CategoryDrill | null;
  setCategoryDrill: (drill: CategoryDrill | null) => void;
  explorerSearch: string;
  setExplorerSearch: (value: string) => void;
  focusedReviewId: string | null;
  focusReview: (id: string | null) => void;
  scrollTo: (id: string) => void;
  quickAddOpen: boolean;
  setQuickAddOpen: (open: boolean) => void;
  commandOpen: boolean;
  setCommandOpen: (open: boolean) => void;
  customizeOpen: boolean;
  setCustomizeOpen: (open: boolean) => void;
}

const DashboardUiContext = createContext<DashboardUiContextValue | null>(null);

export function DashboardUiProvider({ children }: { children: React.ReactNode }) {
  const initialSection = sectionFromHash(window.location.hash) ?? 'overview';
  const [activeWorkspace, setActiveWorkspace] = useState<WorkspaceId>(
    workspaceForSection(initialSection) ?? DEFAULT_WORKSPACE,
  );
  const [activeSection, setActiveSection] = useState(initialSection);
  const [pendingSection, setPendingSection] = useState<DashboardSectionId | null>(initialSection);
  const [categoryDrill, setCategoryDrill] = useState<CategoryDrill | null>(null);
  const [explorerSearch, setExplorerSearch] = useState('');
  const [focusedReviewId, setFocusedReviewId] = useState<string | null>(null);
  const [quickAddOpen, setQuickAddOpen] = useState(false);
  const [commandOpen, setCommandOpenState] = useState(false);
  const commandScrollPosition = useRef(0);
  const [customizeOpen, setCustomizeOpen] = useState(false);

  const setCommandOpen = useCallback((open: boolean) => {
    if (open) commandScrollPosition.current = window.scrollY;
    setCommandOpenState(open);

    const restoreScrollPosition = () =>
      window.scrollTo({ top: commandScrollPosition.current, behavior: 'instant' });
    window.requestAnimationFrame(() => {
      restoreScrollPosition();
      window.requestAnimationFrame(restoreScrollPosition);
    });
  }, []);

  const scrollTo = useCallback((id: string) => {
    const section = dashboardSection(id);
    if (!section) return;
    const workspace = workspaceForSection(section);
    if (!workspace) return;

    setActiveWorkspace(workspace);
    setActiveSection(section);
    setPendingSection(section);
    if (window.location.hash !== `#${section}`) {
      window.history.replaceState(null, '', `#${section}`);
    }
  }, []);

  const openWorkspace = useCallback(
    (workspace: WorkspaceId) => scrollTo(firstSectionForWorkspace(workspace)),
    [scrollTo],
  );

  useEffect(() => {
    if (!pendingSection) return;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById(pendingSection)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      setPendingSection(null);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeWorkspace, pendingSection]);

  useEffect(() => {
    const onHashChange = () => {
      const section = sectionFromHash(window.location.hash);
      if (section) scrollTo(section);
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, [scrollTo]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setCommandOpen(!commandOpen);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [commandOpen, setCommandOpen]);

  const value = useMemo<DashboardUiContextValue>(
    () => ({
      activeWorkspace,
      activeSection,
      openWorkspace,
      categoryDrill,
      setCategoryDrill,
      explorerSearch,
      setExplorerSearch,
      focusedReviewId,
      focusReview: (id) => {
        setFocusedReviewId(id);
        if (id) scrollTo('review');
      },
      scrollTo,
      quickAddOpen,
      setQuickAddOpen,
      commandOpen,
      setCommandOpen,
      customizeOpen,
      setCustomizeOpen,
    }),
    [
      activeSection,
      activeWorkspace,
      categoryDrill,
      explorerSearch,
      focusedReviewId,
      openWorkspace,
      quickAddOpen,
      commandOpen,
      customizeOpen,
      setCommandOpen,
      scrollTo,
    ],
  );

  return <DashboardUiContext.Provider value={value}>{children}</DashboardUiContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useDashboardUi(): DashboardUiContextValue {
  const ctx = useContext(DashboardUiContext);
  if (!ctx) throw new Error('useDashboardUi must be used within DashboardUiProvider');
  return ctx;
}
