import { lazy, Suspense, useEffect, useRef, useState, type ComponentType, type LazyExoticComponent } from 'react';
import { Header } from './Header';
import { SectionNav, type NavSection } from './SectionNav';
import { DashboardUiProvider } from './DashboardUiContext';
import { OverviewSection } from '@/features/overview/OverviewSection';

const TimelineSection = lazy(() => import('@/features/timeline/TimelineSection').then((module) => ({ default: module.TimelineSection })));
const InsightsSection = lazy(() => import('@/features/insights/InsightsSection').then((module) => ({ default: module.InsightsSection })));
const MerchantIntelligenceSection = lazy(() => import('@/features/merchants/MerchantIntelligenceSection').then((module) => ({ default: module.MerchantIntelligenceSection })));
const CategoryIntelligenceSection = lazy(() => import('@/features/categories/CategoryIntelligenceSection').then((module) => ({ default: module.CategoryIntelligenceSection })));
const RecommendationsSection = lazy(() => import('@/features/recommendations/RecommendationsSection').then((module) => ({ default: module.RecommendationsSection })));
const AnalyticsSection = lazy(() => import('@/features/analytics/AnalyticsSection').then((module) => ({ default: module.AnalyticsSection })));
const PipelineHealthSection = lazy(() => import('@/features/pipeline/PipelineHealthSection').then((module) => ({ default: module.PipelineHealthSection })));
const BudgetsSection = lazy(() => import('@/features/budgets/BudgetsSection').then((module) => ({ default: module.BudgetsSection })));
const ReviewSection = lazy(() => import('@/features/review/ReviewSection').then((module) => ({ default: module.ReviewSection })));
const TransactionsSection = lazy(() => import('@/features/transactions/TransactionsSection').then((module) => ({ default: module.TransactionsSection })));
const InboxSection = lazy(() => import('@/features/inbox/InboxSection').then((module) => ({ default: module.InboxSection })));

const SECTIONS: NavSection[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'timeline', label: 'Timeline' },
  { id: 'insights', label: 'Insights' },
  { id: 'merchants', label: 'Merchants' },
  { id: 'categories', label: 'Categories' },
  { id: 'recommendations', label: 'Recommendations' },
  { id: 'analytics', label: 'Analytics' },
  { id: 'pipeline', label: 'Pipeline Health' },
  { id: 'budgets', label: 'Budgets' },
  { id: 'review', label: 'Review' },
  { id: 'transactions', label: 'Transactions' },
  { id: 'inbox', label: 'Inbox / Connectors' },
];

function DeferredSection({
  id,
  component: Component,
}: {
  id: string;
  component: LazyExoticComponent<ComponentType>;
}) {
  const sectionRef = useRef<HTMLElement>(null);
  const [shouldLoad, setShouldLoad] = useState(() => window.location.hash === `#${id}`);

  useEffect(() => {
    const section = sectionRef.current;
    if (!section || shouldLoad) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShouldLoad(true);
          observer.disconnect();
        }
      },
      { rootMargin: '800px 0px' },
    );
    observer.observe(section);
    return () => observer.disconnect();
  }, [shouldLoad]);

  return (
    <section ref={sectionRef} id={id} className="scroll-mt-32">
      {shouldLoad ? (
        <Suspense fallback={<div className="h-32 animate-pulse rounded-xl bg-muted" aria-label={`Loading ${id}`} />}>
          <Component />
        </Suspense>
      ) : (
        <div className="h-32 rounded-xl bg-muted/40" aria-label={`${id} loads when nearby`} />
      )}
    </section>
  );
}

export function DashboardLayout() {
  return (
    <DashboardUiProvider>
      <div className="min-h-screen bg-background">
        <Header />
        <main className="w-full px-3 pb-20 pt-3 sm:px-5 lg:px-8 lg:pt-5 2xl:px-10">
          <SectionNav sections={SECTIONS} />
          <div className="grid gap-12">
            <section id="overview" className="scroll-mt-32">
              <OverviewSection />
            </section>
            <DeferredSection id="timeline" component={TimelineSection} />
            <DeferredSection id="insights" component={InsightsSection} />
            <DeferredSection id="merchants" component={MerchantIntelligenceSection} />
            <DeferredSection id="categories" component={CategoryIntelligenceSection} />
            <DeferredSection id="recommendations" component={RecommendationsSection} />
            <DeferredSection id="analytics" component={AnalyticsSection} />
            <DeferredSection id="pipeline" component={PipelineHealthSection} />
            <DeferredSection id="budgets" component={BudgetsSection} />
            <DeferredSection id="review" component={ReviewSection} />
            <DeferredSection id="transactions" component={TransactionsSection} />
            <DeferredSection id="inbox" component={InboxSection} />
          </div>
        </main>
      </div>
    </DashboardUiProvider>
  );
}
