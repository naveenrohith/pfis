import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
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
  scrollTo: (id: string, historyMode?: 'push' | 'replace') => void;
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
  const initialParams = new URLSearchParams(window.location.search);
  const initialCategory = initialParams.get('category');
  const [activeWorkspace, setActiveWorkspace] = useState<WorkspaceId>(
    workspaceForSection(initialSection) ?? DEFAULT_WORKSPACE,
  );
  const [activeSection, setActiveSection] = useState(initialSection);
  const [pendingSection, setPendingSection] = useState<DashboardSectionId | null>(initialSection);
  const [categoryDrill, setCategoryDrill] = useState<CategoryDrill | null>(
    initialCategory ? { categoryId: initialCategory, label: initialCategory } : null,
  );
  const [explorerSearch, setExplorerSearch] = useState(initialParams.get('q') ?? '');
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

  const scrollTo = useCallback((id: string, historyMode: 'push' | 'replace' = 'replace') => {
    const section = dashboardSection(id);
    if (!section) return;
    const workspace = workspaceForSection(section);
    if (!workspace) return;

    setActiveWorkspace(workspace);
    setActiveSection(section);
    setPendingSection(section);
    if (window.location.hash !== `#${section}`) {
      const url = new URL(window.location.href);
      url.hash = section;
      const nextLocation = `${url.pathname}${url.search}${url.hash}`;
      if (historyMode === 'push') {
        window.history.pushState(window.history.state, '', nextLocation);
      } else {
        window.history.replaceState(window.history.state, '', nextLocation);
      }
    }
  }, []);

  const openWorkspace = useCallback(
    (workspace: WorkspaceId) => scrollTo(firstSectionForWorkspace(workspace)),
    [scrollTo],
  );

  useEffect(() => {
    if (!pendingSection) return;
    let frame = 0;
    let timeout: number | undefined;
    let observer: MutationObserver | undefined;

    const scrollWhenReady = () => {
      const target = document.getElementById(pendingSection);
      if (!target) return false;

      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      observer?.disconnect();
      if (timeout !== undefined) window.clearTimeout(timeout);
      setPendingSection(null);
      return true;
    };

    frame = window.requestAnimationFrame(() => {
      if (scrollWhenReady()) return;

      observer = new MutationObserver(() => {
        if (scrollWhenReady()) observer?.disconnect();
      });
      observer.observe(document.body, { childList: true, subtree: true });
      if (scrollWhenReady()) return;

      timeout = window.setTimeout(() => {
        observer?.disconnect();
        setPendingSection(null);
      }, 15_000);
    });

    return () => {
      window.cancelAnimationFrame(frame);
      observer?.disconnect();
      if (timeout !== undefined) window.clearTimeout(timeout);
    };
  }, [activeWorkspace, pendingSection]);

  useEffect(() => {
    const onLocationChange = () => {
      const section = sectionFromHash(window.location.hash);
      if (section) scrollTo(section);
    };
    window.addEventListener('hashchange', onLocationChange);
    window.addEventListener('popstate', onLocationChange);
    return () => {
      window.removeEventListener('hashchange', onLocationChange);
      window.removeEventListener('popstate', onLocationChange);
    };
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
