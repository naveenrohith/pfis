import { Header } from './Header';
import { SectionNav, type NavSection } from './SectionNav';
import { DashboardUiProvider } from './DashboardUiContext';
import { OverviewSection } from '@/features/overview/OverviewSection';
import { InboxSection } from '@/features/inbox/InboxSection';
import { InsightsSection } from '@/features/insights/InsightsSection';
import { BudgetsSection } from '@/features/budgets/BudgetsSection';
import { ReviewSection } from '@/features/review/ReviewSection';
import { TransactionsSection } from '@/features/transactions/TransactionsSection';

const SECTIONS: NavSection[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'inbox', label: 'Inbox' },
  { id: 'insights', label: 'Insights' },
  { id: 'budgets', label: 'Budgets' },
  { id: 'review', label: 'Review' },
  { id: 'transactions', label: 'Transactions' },
];

export function DashboardLayout() {
  return (
    <DashboardUiProvider>
      <div className="min-h-screen bg-background">
        <Header />
        <main className="mx-auto max-w-7xl px-4 pb-20 pt-4 sm:px-6">
          <SectionNav sections={SECTIONS} />
          <div className="grid gap-10">
            <section id="overview" className="scroll-mt-28">
              <OverviewSection />
            </section>
            <section id="inbox" className="scroll-mt-28">
              <InboxSection />
            </section>
            <section id="insights" className="scroll-mt-28">
              <InsightsSection />
            </section>
            <section id="budgets" className="scroll-mt-28">
              <BudgetsSection />
            </section>
            <section id="review" className="scroll-mt-28">
              <ReviewSection />
            </section>
            <section id="transactions" className="scroll-mt-28">
              <TransactionsSection />
            </section>
          </div>
        </main>
      </div>
    </DashboardUiProvider>
  );
}
