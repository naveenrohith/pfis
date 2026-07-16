import { EmptyState } from '@/components/ui/Skeleton';

export interface WorkspaceEmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  className?: string;
}

/** Consistent empty-state used by workspace surfaces (timeline, recommendations, search). */
export function WorkspaceEmptyState({
  icon,
  title,
  description,
  className,
}: WorkspaceEmptyStateProps) {
  return <EmptyState icon={icon} title={title} description={description} className={className} />;
}
