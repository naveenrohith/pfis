import { Header } from './Header';
import { SectionNav, type NavSection } from './SectionNav';
import { DashboardUiProvider } from './DashboardUiContext';
import { OverviewSection } from '@/features/overview/OverviewSection';
import { TimelineSection } from '@/features/timeline/TimelineSection';
import { RecommendationsSection } from '@/features/recommendations/RecommendationsSection';
import { InboxSection } from '@/features/inbox/InboxSection';
import { InsightsSection } from '@/features/insights/InsightsSection';
import { BudgetsSection } from '@/features/budgets/BudgetsSection';
import { ReviewSection } from '@/features/review/ReviewSection';
import { TransactionsSection } from '@/features/transactions/TransactionsSection';
import { MerchantIntelligenceSection } from '@/features/merchants/MerchantIntelligenceSection';
import { CategoryIntelligenceSection } from '@/features/categories/CategoryIntelligenceSection';
import { AnalyticsSection } from '@/features/analytics/AnalyticsSection';
import { PipelineHealthSection } from '@/features/pipeline/PipelineHealthSection';

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

export function DashboardLayout() {
  return (
    <DashboardUiProvider>
      <div className="min-h-screen bg-background">
        <Header />
        <main className="mx-auto max-w-7xl px-4 pb-20 pt-3 sm:px-6 lg:pt-5">
          <SectionNav sections={SECTIONS} />
          <div className="grid gap-12">
            <section id="overview" className="scroll-mt-32">
              <OverviewSection />
            </section>
            <section id="timeline" className="scroll-mt-32">
              <TimelineSection />
            </section>
            <section id="insights" className="scroll-mt-32">
              <InsightsSection />
            </section>
            <section id="merchants" className="scroll-mt-32">
              <MerchantIntelligenceSection />
            </section>
            <section id="categories" className="scroll-mt-32">
              <CategoryIntelligenceSection />
            </section>
            <section id="recommendations" className="scroll-mt-32">
              <RecommendationsSection />
            </section>
            <section id="analytics" className="scroll-mt-32">
              <AnalyticsSection />
            </section>
            <section id="pipeline" className="scroll-mt-32">
              <PipelineHealthSection />
            </section>
            <section id="budgets" className="scroll-mt-32">
              <BudgetsSection />
            </section>
            <section id="review" className="scroll-mt-32">
              <ReviewSection />
            </section>
            <section id="transactions" className="scroll-mt-32">
              <TransactionsSection />
            </section>
            <section id="inbox" className="scroll-mt-32">
              <InboxSection />
            </section>
          </div>
        </main>
      </div>
    </DashboardUiProvider>
  );
}
