import { AlertTriangle, Sparkles } from 'lucide-react';
import { Skeleton } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { Badge } from '@/components/ui/Badge';
import { RecommendationCard } from '@/components/cards/RecommendationCard';
import { WorkspaceEmptyState } from '@/components/cards/WorkspaceEmptyState';
import { useWorkspaceSnapshot } from '@/features/workspace/queries';
import { useDashboardUi } from '@/app/DashboardUiContext';

/** Recommendation Center — deterministic, actionable suggestions. */
export function RecommendationsSection() {
  const workspace = useWorkspaceSnapshot();
  const { scrollTo } = useDashboardUi();

  const recommendations = workspace.data?.recommendations ?? [];

  return (
    <div>
      <SectionTitle
        eyebrow="Recommendations"
        title="What needs your attention"
        description="Budget risks, recurring charges, anomalies, and cleanup — ranked for action."
        action={
          recommendations.length > 0 ? (
            <Badge variant="warning">{recommendations.length} to review</Badge>
          ) : undefined
        }
      />

      {workspace.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : workspace.isError ? (
        <WorkspaceEmptyState
          icon={<AlertTriangle />}
          title="Couldn't load recommendations"
          description="We'll retry automatically. Check your connection if this persists."
        />
      ) : recommendations.length === 0 ? (
        <WorkspaceEmptyState
          icon={<Sparkles />}
          title="You're all caught up"
          description="No budget risks, anomalies, or cleanup items right now."
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {recommendations.map((rec, i) => (
            <RecommendationCard
              key={`${rec.type}-${i}`}
              title={rec.title}
              description={rec.description}
              severity={rec.severity}
              actionLabel={rec.action_label}
              onAction={() => scrollTo(rec.target)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
