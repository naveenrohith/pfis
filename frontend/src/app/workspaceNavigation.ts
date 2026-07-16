export type WorkspaceId = 'today' | 'activity' | 'plan' | 'insights' | 'data';

export type DashboardSectionId =
  | 'overview'
  | 'recommendations'
  | 'guidance'
  | 'timeline'
  | 'insights'
  | 'analytics'
  | 'budgets'
  | 'networth'
  | 'categories'
  | 'merchants'
  | 'review'
  | 'transactions'
  | 'inbox'
  | 'pipeline';

export interface WorkspaceSection {
  id: DashboardSectionId;
  label: string;
}

export interface WorkspaceDefinition {
  id: WorkspaceId;
  label: string;
  shortLabel: string;
  description: string;
  sections: WorkspaceSection[];
}

/**
 * PFIS v2 has five stable destinations. The section ids intentionally remain
 * unchanged so bookmarks and action targets from the API continue to work.
 */
export const WORKSPACES: WorkspaceDefinition[] = [
  {
    id: 'today',
    label: 'Today',
    shortLabel: 'Today',
    description: 'Your position, the reason it changed, and the next best action.',
    sections: [
      { id: 'overview', label: 'Brief' },
      { id: 'guidance', label: 'Coach' },
      { id: 'recommendations', label: 'Actions' },
    ],
  },
  {
    id: 'activity',
    label: 'Activity',
    shortLabel: 'Activity',
    description: 'Search, verify, and explain every movement of money.',
    sections: [
      { id: 'transactions', label: 'Transactions' },
      { id: 'review', label: 'Review' },
      { id: 'timeline', label: 'Timeline' },
    ],
  },
  {
    id: 'plan',
    label: 'Plan',
    shortLabel: 'Plan',
    description: 'Shape budgets, goals, accounts, and the month ahead.',
    sections: [
      { id: 'analytics', label: 'Outlook' },
      { id: 'networth', label: 'Position' },
      { id: 'budgets', label: 'Budgets' },
    ],
  },
  {
    id: 'insights',
    label: 'Insights',
    shortLabel: 'Insights',
    description: 'Understand the drivers, categories, merchants, and patterns.',
    sections: [
      { id: 'insights', label: 'Drivers' },
      { id: 'categories', label: 'Categories' },
      { id: 'merchants', label: 'Merchants' },
    ],
  },
  {
    id: 'data',
    label: 'Data & settings',
    shortLabel: 'Data',
    description: 'Connections, processing health, recovery, and preferences.',
    sections: [
      { id: 'inbox', label: 'Connections' },
      { id: 'pipeline', label: 'Diagnostics' },
    ],
  },
];

export const DEFAULT_WORKSPACE: WorkspaceId = 'today';

const sectionToWorkspace = new Map<DashboardSectionId, WorkspaceId>(
  WORKSPACES.flatMap((workspace) =>
    workspace.sections.map((section) => [section.id, workspace.id] as const),
  ),
);

const legacyWorkspaceAliases: Record<string, WorkspaceId> = {
  home: 'today',
  understand: 'insights',
  act: 'activity',
  system: 'data',
};

export function dashboardSection(sectionId: string): DashboardSectionId | null {
  return sectionToWorkspace.has(sectionId as DashboardSectionId)
    ? (sectionId as DashboardSectionId)
    : null;
}

export function workspaceForSection(sectionId: string): WorkspaceId | null {
  const section = dashboardSection(sectionId);
  return section ? (sectionToWorkspace.get(section) ?? null) : null;
}

export function dashboardWorkspace(workspaceId: string): WorkspaceId | null {
  if (WORKSPACES.some((workspace) => workspace.id === workspaceId)) {
    return workspaceId as WorkspaceId;
  }
  return legacyWorkspaceAliases[workspaceId] ?? null;
}

export function firstSectionForWorkspace(workspaceId: WorkspaceId): DashboardSectionId {
  return (
    WORKSPACES.find((workspace) => workspace.id === workspaceId)?.sections[0]?.id ?? 'overview'
  );
}

export function sectionFromHash(hash: string): DashboardSectionId | null {
  try {
    const target = decodeURIComponent(hash.replace(/^#/, ''));
    const section = dashboardSection(target);
    if (section) return section;
    const workspace = dashboardWorkspace(target);
    return workspace ? firstSectionForWorkspace(workspace) : null;
  } catch {
    return null;
  }
}
