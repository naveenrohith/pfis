import { useEffect, useState } from 'react';
import {
  Activity,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Bot,
  Check,
  ChevronDown,
  CircleAlert,
  CircleDollarSign,
  Database,
  Goal,
  House,
  LineChart,
  ListChecks,
  Moon,
  MoreHorizontal,
  Search,
  Settings2,
  Sparkles,
  Target,
  TrendingUp,
  WalletCards,
} from 'lucide-react';
import {
  ActionSurface,
  ChartFrame,
  FinancialHero,
  InsightSurface,
  LedgerRow,
  PageIntro,
} from '@/components/system';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Tabs } from '@/components/ui/Tabs';
import { cn } from '@/lib/utils';

type Screen = 'today' | 'activity' | 'review' | 'plan' | 'insights' | 'data';

const navigation: Array<{
  id: Exclude<Screen, 'review'>;
  label: string;
  icon: typeof House;
}> = [
  { id: 'today', label: 'Today', icon: House },
  { id: 'activity', label: 'Activity', icon: Activity },
  { id: 'plan', label: 'Plan', icon: Target },
  { id: 'insights', label: 'Insights', icon: LineChart },
  { id: 'data', label: 'Data & settings', icon: Database },
];

const transactions = [
  ['VB', 'Victory Bazar Groceries', 'Groceries · Credit card', '13 Jul', '−₹519'],
  ['SC', 'Sri Ganesh Tiffin Center', 'Dining · UPI', '10 Jul', '−₹330'],
  ['MP', 'Milk Packets', 'Groceries · UPI', '09 Jul', '−₹72'],
  ['PP', 'Petrol Pulsar', 'Fuel · Credit card', '09 Jul', '−₹500'],
  ['DA', 'Car loan adjustment', 'Commitment · UPI', '07 Jul', '−₹25,000'],
  ['DP', 'Drinkprime', 'Subscription · UPI', '05 Jul', '−₹429'],
];

function initialScreen(): Screen {
  const candidate = window.location.hash.replace('#', '') as Screen;
  return ['today', 'activity', 'review', 'plan', 'insights', 'data'].includes(candidate)
    ? candidate
    : 'today';
}

export function PrototypeApp() {
  const [screen, setScreen] = useState<Screen>(initialScreen);

  useEffect(() => {
    window.location.hash = screen;
  }, [screen]);

  const activeNavigation = screen === 'review' ? 'activity' : screen;

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="grid min-h-screen lg:grid-cols-[88px_minmax(0,1fr)]">
        <aside className="fixed inset-x-0 bottom-0 z-40 order-2 border-t border-border bg-card pb-[env(safe-area-inset-bottom)] lg:sticky lg:top-0 lg:order-1 lg:flex lg:h-screen lg:flex-col lg:border-r lg:border-t-0 lg:bg-secondary/55 lg:p-3">
          <div className="hidden h-14 place-items-center lg:grid">
            <div className="grid h-11 w-11 place-items-center rounded-lg bg-primary text-sm font-extrabold text-primary-foreground">
              P
            </div>
          </div>
          <nav
            aria-label="Prototype destinations"
            className="grid grid-cols-5 lg:mt-6 lg:flex lg:flex-1 lg:flex-col lg:gap-2"
          >
            {navigation.map((item) => {
              const Icon = item.icon;
              const active = activeNavigation === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  aria-label={item.label}
                  aria-current={active ? 'page' : undefined}
                  onClick={() => setScreen(item.id)}
                  className={cn(
                    'focus-ring group relative flex min-h-16 flex-col items-center justify-center gap-1 rounded-lg text-[10px] font-bold text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:min-h-14 lg:text-[9px]',
                    active && 'bg-primary/10 text-primary',
                  )}
                >
                  <Icon className="h-5 w-5" aria-hidden="true" />
                  <span
                    className={cn(
                      'text-foreground',
                      item.id === 'data' && 'leading-3',
                    )}
                  >
                    {item.label}
                  </span>
                  {active ? (
                    <span className="absolute left-0 hidden h-5 w-0.5 rounded-full bg-primary lg:block" />
                  ) : null}
                </button>
              );
            })}
          </nav>
        </aside>

        <div className="min-w-0 pb-20 lg:order-2 lg:pb-0">
          <header className="bg-background/92 sticky top-0 z-30 flex h-16 items-center justify-between border-b border-border/70 px-4 backdrop-blur sm:px-6 lg:h-[72px] lg:px-8">
            <button
              type="button"
              className="focus-ring flex min-h-11 items-center gap-2 rounded-lg px-2 text-sm font-extrabold hover:bg-muted"
            >
              July 2026 <ChevronDown className="h-4 w-4 text-muted-foreground" />
            </button>
            <div className="flex items-center gap-1.5">
              <Button variant="ghost" size="icon" aria-label="Search">
                <Search className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="icon" aria-label="Ask PFIS">
                <Sparkles className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Change theme"
                className="hidden sm:inline-flex"
              >
                <Moon className="h-4 w-4" />
              </Button>
              <button
                type="button"
                className="focus-ring ml-1 grid h-11 w-11 place-items-center rounded-full bg-accent text-xs font-extrabold text-accent-foreground"
              >
                NR
              </button>
            </div>
          </header>

          <main className="mx-auto w-full max-w-[1240px] px-4 py-8 sm:px-6 lg:px-10 lg:py-12">
            {screen === 'today' ? <TodayPrototype onReview={() => setScreen('review')} /> : null}
            {screen === 'activity' ? (
              <ActivityPrototype onReview={() => setScreen('review')} />
            ) : null}
            {screen === 'review' ? <ReviewPrototype onBack={() => setScreen('activity')} /> : null}
            {screen === 'plan' ? <PlanPrototype /> : null}
            {screen === 'insights' ? <InsightsPrototype /> : null}
            {screen === 'data' ? <DataPrototype /> : null}
          </main>
        </div>
      </div>
    </div>
  );
}

function TodayPrototype({ onReview }: { onReview: () => void }) {
  return (
    <div className="space-y-10">
      <PageIntro
        eyebrow="Thursday · Financial brief"
        title={
          <>
            Good morning, Naveen. Your spending is{' '}
            <span className="text-coral">running ahead.</span>
          </>
        }
        description="You have spent ₹20,604 more than you earned this month. One recurring-cost review can improve the outlook without changing your daily routine."
      />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.55fr)_minmax(300px,.65fr)]">
        <FinancialHero className="min-h-[390px]">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm text-muted-foreground">Net cash flow</p>
              <p className="money-value mt-1 text-4xl text-foreground sm:text-5xl lg:text-6xl">
                −₹20,604
              </p>
              <p className="mt-2 text-sm text-muted-foreground">
                ₹7,800 better than this point last month
              </p>
            </div>
            <div className="text-right">
              <p className="text-xs text-muted-foreground">Financial health</p>
              <p className="money-value mt-1 text-3xl text-success">45</p>
            </div>
          </div>
          <HorizonChart />
        </FinancialHero>
        <ActionSurface
          icon={<Sparkles className="h-4 w-4" />}
          title="Review four recurring charges"
          description="₹20,585 repeats monthly. PFIS found commitments that may no longer be useful."
          actionLabel="Review commitments"
          onAction={onReview}
          secondary="Based on 6 recurring patterns"
        />
      </div>

      <section aria-labelledby="pulse-title">
        <div className="mb-5 flex items-end justify-between gap-4">
          <div>
            <p className="text-xs font-bold text-muted-foreground">Financial pulse</p>
            <h2 id="pulse-title" className="mt-1 text-2xl font-extrabold tracking-[-0.035em]">
              The three signals that matter now
            </h2>
          </div>
          <Button variant="link">
            View full outlook <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
        <div className="grid gap-5 border-y border-border/70 py-6 md:grid-cols-3 md:divide-x md:divide-border">
          <Pulse
            label="Spent this month"
            value="₹63,804"
            context="74% above last month"
            tone="danger"
          />
          <Pulse
            label="Projected month end"
            value="−₹88,662"
            context="At the current daily pace"
            tone="warning"
          />
          <Pulse
            label="Recurring burden"
            value="47.7%"
            context="Four items worth reviewing"
            tone="neutral"
          />
        </div>
      </section>

      <section className="grid gap-7 lg:grid-cols-[1fr_1fr]">
        <div>
          <p className="text-xs font-bold text-muted-foreground">What changed</p>
          <h2 className="mt-1 text-2xl font-extrabold tracking-[-0.035em]">
            Evidence behind today’s brief
          </h2>
        </div>
        <div className="space-y-6">
          <InsightSurface
            icon={<TrendingUp className="h-4 w-4" />}
            title="Spending rose 74% from last month"
            description="A ₹25,000 loan adjustment and higher recurring costs explain most of the increase."
            tone="attention"
          />
          <InsightSurface
            icon={<WalletCards className="h-4 w-4" />}
            title="UPI carries 90% of tracked spending"
            description="Thirteen payments account for ₹57,517 this month."
          />
        </div>
      </section>

      <TrustFooter />
    </div>
  );
}

function ActivityPrototype({ onReview }: { onReview: () => void }) {
  const [view, setView] = useState('transactions');
  const [selected, setSelected] = useState(0);
  return (
    <div className="space-y-8">
      <PageIntro
        eyebrow="Activity"
        title="Follow every movement of money."
        description="Search, verify, and explain transactions without losing their source context."
        action={
          <Button onClick={onReview}>
            <ListChecks className="h-4 w-4" /> Review 3 items
          </Button>
        }
      />
      <Tabs
        ariaLabel="Activity view"
        value={view}
        onValueChange={setView}
        options={[
          { value: 'transactions', label: 'Transactions' },
          { value: 'timeline', label: 'Timeline' },
          { value: 'recurring', label: 'Recurring' },
        ]}
      />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <section className="min-w-0 rounded-xl bg-card p-4 sm:p-5">
          <div className="mb-3 flex gap-2">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-10"
                aria-label="Search transactions"
                placeholder="Search merchant, category, amount…"
              />
            </div>
            <Button variant="outline" size="icon" aria-label="More filters">
              <Settings2 className="h-4 w-4" />
            </Button>
          </div>
          <div aria-label="Transactions">
            {transactions.map((row, index) => (
              <LedgerRow
                key={row[1]}
                leading={row[0]}
                title={row[1]}
                subtitle={row[2]}
                meta={row[3]}
                amount={
                  <span className={row[4].startsWith('−') ? 'text-danger' : 'text-success'}>
                    {row[4]}
                  </span>
                }
                selected={selected === index}
                onSelect={() => setSelected(index)}
              />
            ))}
          </div>
          <div className="flex items-center justify-between px-2 pt-4 text-xs text-muted-foreground">
            <span>22 transactions</span>
            <Button variant="link" size="sm">
              View all activity
            </Button>
          </div>
        </section>
        <aside className="hidden min-h-[520px] rounded-xl bg-secondary/55 p-6 lg:block">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-bold text-muted-foreground">Selected transaction</p>
              <h2 className="mt-1 text-xl font-extrabold tracking-[-0.03em]">
                {transactions[selected][1]}
              </h2>
            </div>
            <Button variant="ghost" size="icon" aria-label="More transaction actions">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </div>
          <p className="money-value mt-8 text-4xl text-danger">{transactions[selected][4]}</p>
          <dl className="mt-8 space-y-4 text-sm">
            <Detail label="Date" value={transactions[selected][3] + ', 2026'} />
            <Detail label="Category" value={transactions[selected][2].split(' · ')[0]} />
            <Detail label="Method" value={transactions[selected][2].split(' · ')[1]} />
            <Detail label="Status" value="Ready" />
          </dl>
          <div className="mt-8 border-t border-border pt-5">
            <p className="text-xs font-bold text-muted-foreground">Source evidence</p>
            <p className="mt-2 text-sm leading-6">
              Matched from a bank notification and normalized with 96% confidence.
            </p>
            <Button variant="link" className="mt-3">
              Explain classification <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        </aside>
      </div>
    </div>
  );
}

function ReviewPrototype({ onBack }: { onBack: () => void }) {
  const [selected, setSelected] = useState(0);
  const queue = [
    ['VB', 'Victory Bazar Groceries', 'Merchant and category need confirmation', '−₹519'],
    ['MP', 'Milk Packets', 'Category confidence is 80%', '−₹72'],
    ['DP', 'Drinkprime', 'Possible recurring commitment', '−₹429'],
  ];
  return (
    <div className="space-y-8">
      <PageIntro
        eyebrow="Activity · Review"
        title="Resolve uncertainty, one item at a time."
        description="PFIS keeps the source, proposed interpretation, and correction controls in one focused flow."
        action={
          <Button variant="ghost" onClick={onBack}>
            Back to activity
          </Button>
        }
      />
      <div className="grid gap-5 lg:grid-cols-[360px_minmax(0,1fr)]">
        <section className="min-w-0 rounded-xl bg-secondary/50 p-4">
          <div className="flex items-center justify-between px-2 pb-3">
            <p className="text-sm font-extrabold">Review queue</p>
            <Badge variant="warning">3 remaining</Badge>
          </div>
          {queue.map((item, index) => (
            <LedgerRow
              key={item[1]}
              leading={item[0]}
              title={item[1]}
              subtitle={item[2]}
              amount={<span className="text-danger">{item[3]}</span>}
              selected={selected === index}
              onSelect={() => setSelected(index)}
            />
          ))}
        </section>
        <section className="rounded-xl bg-card p-5 sm:p-8">
          <div className="flex flex-col justify-between gap-4 border-b border-border/70 pb-6 sm:flex-row sm:items-start">
            <div>
              <p className="text-xs font-bold text-muted-foreground">Item {selected + 1} of 3</p>
              <h2 className="mt-1 text-2xl font-extrabold tracking-[-0.035em]">
                {queue[selected][1]}
              </h2>
              <p className="money-value mt-3 text-4xl text-danger">{queue[selected][3]}</p>
            </div>
            <Badge variant="warning">Needs confirmation</Badge>
          </div>
          <div className="grid gap-8 py-7 md:grid-cols-2">
            <div>
              <p className="text-xs font-bold text-muted-foreground">PFIS proposes</p>
              <div className="mt-3 space-y-3">
                <Proposal label="Merchant" value={queue[selected][1]} />
                <Proposal label="Category" value={selected === 2 ? 'Subscriptions' : 'Groceries'} />
                <Proposal label="Payment method" value="Credit card" />
              </div>
            </div>
            <div>
              <p className="text-xs font-bold text-muted-foreground">Why this needs review</p>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">
                The source description is abbreviated and resembles multiple known merchants.
                Confirming this improves future classification.
              </p>
              <button
                type="button"
                className="focus-ring mt-4 w-full rounded-lg bg-muted/65 p-4 text-left"
              >
                <span className="block text-xs font-bold text-muted-foreground">
                  Source excerpt
                </span>
                <span className="mt-1 block text-sm">HDFC Bank · card ending 4B49 · 13 Jul</span>
              </button>
            </div>
          </div>
          <div className="flex flex-col-reverse gap-3 border-t border-border/70 pt-6 sm:flex-row sm:justify-between">
            <Button variant="ghost">Skip for now</Button>
            <div className="flex gap-2">
              <Button variant="outline">Correct details</Button>
              <Button onClick={() => setSelected((selected + 1) % queue.length)}>
                <Check className="h-4 w-4" /> Confirm
              </Button>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

function PlanPrototype() {
  return (
    <div className="space-y-10">
      <PageIntro
        eyebrow="Plan"
        title="Shape the rest of the month."
        description="See the likely outcome, then adjust the commitment or goal that can change it."
        action={
          <Button>
            <Goal className="h-4 w-4" /> Create goal
          </Button>
        }
      />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(300px,.7fr)]">
        <FinancialHero>
          <div className="flex flex-col justify-between gap-6 sm:flex-row">
            <div>
              <p className="text-sm text-muted-foreground">Projected month-end cash flow</p>
              <p className="money-value mt-2 text-5xl text-danger">−₹88,662</p>
              <p className="mt-2 text-sm text-muted-foreground">
                Expected range −₹75,000 to −₹1,02,000
              </p>
            </div>
            <Badge variant="warning" className="self-start">
              Needs adjustment
            </Badge>
          </div>
          <HorizonChart compact />
        </FinancialHero>
        <ActionSurface
          eyebrow="Best planning move"
          icon={<Target className="h-4 w-4" />}
          title="Reduce recurring commitments by ₹3,500"
          description="That would protect 8% of monthly income and improve the projected shortfall."
          actionLabel="Explore commitments"
          onAction={() => {}}
        />
      </div>
      <section className="grid gap-7 lg:grid-cols-2">
        <div>
          <div className="mb-5 flex items-end justify-between">
            <div>
              <p className="text-xs font-bold text-muted-foreground">Goals</p>
              <h2 className="mt-1 text-2xl font-extrabold tracking-[-0.035em]">
                Progress toward outcomes
              </h2>
            </div>
            <Button variant="link">Manage</Button>
          </div>
          <div className="space-y-4">
            <GoalProgress
              title="Emergency buffer"
              value="₹18,000 of ₹50,000"
              progress={36}
              tone="primary"
            />
            <GoalProgress
              title="Reduce dining"
              value="₹1,800 remaining"
              progress={72}
              tone="warning"
            />
          </div>
        </div>
        <div>
          <div className="mb-5">
            <p className="text-xs font-bold text-muted-foreground">Position</p>
            <h2 className="mt-1 text-2xl font-extrabold tracking-[-0.035em]">
              Accounts and net worth
            </h2>
          </div>
          <div className="rounded-xl bg-card p-5">
            <div className="flex items-end justify-between border-b border-border/70 pb-5">
              <div>
                <p className="text-xs text-muted-foreground">Net worth</p>
                <p className="money-value mt-1 text-3xl">₹4,32,000</p>
              </div>
              <span className="text-sm font-bold text-success">+2.4%</span>
            </div>
            <LedgerRow leading="SB" title="Savings account" subtitle="Asset" amount="₹2,40,000" />
            <LedgerRow leading="MF" title="Mutual funds" subtitle="Investment" amount="₹2,92,000" />
            <LedgerRow
              leading="CL"
              title="Car loan"
              subtitle="Liability"
              amount={<span className="text-danger">−₹1,00,000</span>}
            />
          </div>
        </div>
      </section>
    </div>
  );
}

function InsightsPrototype() {
  return (
    <div className="space-y-10">
      <PageIntro
        eyebrow="Insights"
        title={
          <>
            One adjustment explains{' '}
            <span className="text-coral">39% of this month’s spending.</span>
          </>
        }
        description="PFIS separates structural commitments from everyday behavior so the right change is obvious."
      />
      <div className="grid gap-7 lg:grid-cols-[minmax(0,1.15fr)_minmax(320px,.85fr)]">
        <section className="rounded-xl bg-card p-5 sm:p-7">
          <ChartFrame
            title="Drivers of the monthly increase"
            description="Contribution compared with last month"
            summary="A car loan adjustment contributed 39 percent of spending, recurring commitments 32 percent, groceries 8 percent, and other activity 21 percent."
            dataTable={<SimpleDataTable />}
          >
            <DriverBars />
          </ChartFrame>
        </section>
        <section className="space-y-7">
          <InsightSurface
            icon={<CircleDollarSign className="h-4 w-4" />}
            eyebrow="Largest driver"
            title="Car loan adjustment added ₹25,000"
            description="This appears to be a one-time adjustment rather than a change in routine spending."
            tone="attention"
          />
          <InsightSurface
            icon={<ArrowDownRight className="h-4 w-4" />}
            eyebrow="Positive counter-signal"
            title="Dining fell ₹1,250 week over week"
            description="Three fewer transactions account for the improvement."
            tone="positive"
          />
          <InsightSurface
            icon={<Bot className="h-4 w-4" />}
            eyebrow="PFIS interpretation"
            title="Recurring costs are the actionable pressure"
            description="Unlike the loan adjustment, these costs continue into next month."
            tone="intelligence"
          />
        </section>
      </div>
      <section>
        <div className="mb-5">
          <p className="text-xs font-bold text-muted-foreground">Patterns</p>
          <h2 className="mt-1 text-2xl font-extrabold tracking-[-0.035em]">Where to look next</h2>
        </div>
        <div className="grid gap-5 md:grid-cols-3">
          <Pattern
            title="Recurring commitments"
            value="₹20,585"
            change="47.7% of income"
            icon={<WalletCards className="h-5 w-5" />}
          />
          <Pattern
            title="Top merchant"
            value="₹25,000"
            change="Car loan adjustment"
            icon={<ArrowUpRight className="h-5 w-5" />}
          />
          <Pattern
            title="Largest category"
            value="₹45,880"
            change="Other · needs cleanup"
            icon={<CircleAlert className="h-5 w-5" />}
          />
        </div>
      </section>
      <TrustFooter />
    </div>
  );
}

function DataPrototype() {
  return (
    <div className="space-y-10">
      <PageIntro
        eyebrow="Data & settings"
        title="Keep PFIS accurate and connected."
        description="Source health, account setup, import recovery, and preferences live here—away from the daily financial story."
        action={
          <Button variant="outline">
            <Settings2 className="h-4 w-4" /> Preferences
          </Button>
        }
      />
      <section className="rounded-xl bg-card p-5 sm:p-7">
        <div className="flex flex-col justify-between gap-4 border-b border-border/70 pb-5 sm:flex-row sm:items-center">
          <div>
            <p className="text-xs font-bold text-muted-foreground">Connections</p>
            <h2 className="mt-1 text-2xl font-extrabold tracking-[-0.035em]">
              Your financial data is current
            </h2>
          </div>
          <Badge variant="success" className="self-start">
            <Check className="h-3.5 w-3.5" /> All sources healthy
          </Badge>
        </div>
        <div className="divide-y divide-border/70">
          <SourceRow
            name="Gmail financial inbox"
            detail="346 messages processed · checked 6 min ago"
            status="Live"
          />
          <SourceRow
            name="Manual accounts"
            detail="3 accounts · balances through 15 Jul"
            status="Current"
          />
          <SourceRow
            name="Classification pipeline"
            detail="2 items need review · no blocked imports"
            status="Attention"
          />
        </div>
      </section>
      <div className="grid gap-7 lg:grid-cols-2">
        <section>
          <div className="mb-5">
            <p className="text-xs font-bold text-muted-foreground">Accounts</p>
            <h2 className="mt-1 text-2xl font-extrabold tracking-[-0.035em]">
              Balances and ownership
            </h2>
          </div>
          <div className="rounded-xl bg-secondary/45 p-4">
            <LedgerRow
              leading="SB"
              title="Savings account"
              subtitle="Manual · ending 1441"
              amount="₹2,40,000"
            />
            <LedgerRow
              leading="MF"
              title="Mutual funds"
              subtitle="Manual investment"
              amount="₹2,92,000"
            />
            <LedgerRow
              leading="CL"
              title="Car loan"
              subtitle="Manual liability"
              amount={<span className="text-danger">−₹1,00,000</span>}
            />
            <Button variant="link" className="ml-2 mt-3">
              Add financial account <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        </section>
        <section>
          <div className="mb-5">
            <p className="text-xs font-bold text-muted-foreground">Processing</p>
            <h2 className="mt-1 text-2xl font-extrabold tracking-[-0.035em]">
              Import and classification health
            </h2>
          </div>
          <div className="rounded-xl bg-card p-5">
            <div className="grid grid-cols-2 gap-5">
              <DataMetric label="Processed" value="346" />
              <DataMetric label="Waiting" value="0" />
              <DataMetric label="Needs review" value="2" />
              <DataMetric label="Avg confidence" value="93%" />
            </div>
            <div className="mt-6 border-t border-border/70 pt-5">
              <p className="text-sm font-extrabold">No blocked imports</p>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                Technical diagnostics remain available when a source cannot recover automatically.
              </p>
              <Button variant="link" className="mt-2">
                Open diagnostics <ArrowRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

function HorizonChart({ compact = false }: { compact?: boolean }) {
  return (
    <svg
      className={cn('mt-8 w-full overflow-visible text-primary', compact ? 'h-36' : 'h-52')}
      viewBox="0 0 720 200"
      role="img"
      aria-label="Cash flow trend rises and falls through the month, with a spending spike on 7 July"
    >
      <path
        d="M12 148 C80 135 104 62 165 82 S240 154 302 120 S381 48 444 71 S530 146 596 119 S662 92 708 103"
        fill="none"
        stroke="currentColor"
        strokeOpacity=".16"
        strokeWidth="15"
        strokeLinecap="round"
      />
      <path
        d="M12 148 C80 135 104 62 165 82 S240 154 302 120 S381 48 444 71 S530 146 596 119 S662 92 708 103"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <circle cx="444" cy="71" r="6" className="fill-coral" />
      <line
        x1="444"
        y1="71"
        x2="444"
        y2="24"
        stroke="currentColor"
        strokeOpacity=".32"
        strokeDasharray="3 4"
      />
      <text x="456" y="27" fill="currentColor" fontSize="11">
        ₹25k spending spike
      </text>
      <text x="12" y="192" fill="currentColor" opacity=".55" fontSize="11">
        1 Jul
      </text>
      <text x="670" y="192" fill="currentColor" opacity=".55" fontSize="11">
        15 Jul
      </text>
    </svg>
  );
}

function Pulse({
  label,
  value,
  context,
  tone,
}: {
  label: string;
  value: string;
  context: string;
  tone: 'danger' | 'warning' | 'neutral';
}) {
  return (
    <div className="px-0 md:px-6 md:first:pl-0">
      <p className="text-xs font-bold text-muted-foreground">{label}</p>
      <p
        className={cn(
          'money-value mt-2 text-3xl',
          tone === 'danger' && 'text-danger',
          tone === 'warning' && 'text-warning',
        )}
      >
        {value}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">{context}</p>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right font-bold">{value}</dd>
    </div>
  );
}
function Proposal({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-secondary/55 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-sm font-extrabold">{value}</p>
    </div>
  );
}

function GoalProgress({
  title,
  value,
  progress,
  tone,
}: {
  title: string;
  value: string;
  progress: number;
  tone: 'primary' | 'warning';
}) {
  return (
    <div className="rounded-xl bg-card p-5">
      <div className="flex justify-between gap-3">
        <div>
          <p className="font-extrabold">{title}</p>
          <p className="mt-1 text-xs text-muted-foreground">{value}</p>
        </div>
        <span className="money-value text-sm">{progress}%</span>
      </div>
      <div className="mt-4 h-2 overflow-hidden rounded-full bg-muted">
        <div
          className={cn('h-full rounded-full', tone === 'primary' ? 'bg-primary' : 'bg-warning')}
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}

function DriverBars() {
  const rows = [
    ['Car loan adjustment', 39, '₹25,000'],
    ['Recurring commitments', 32, '₹20,585'],
    ['Groceries', 8, '₹5,115'],
    ['Other activity', 21, '₹13,104'],
  ];
  return (
    <div className="space-y-5 py-3">
      {rows.map(([label, value, amount]) => (
        <div key={String(label)}>
          <div className="mb-2 flex justify-between gap-3 text-sm">
            <span className="font-bold">{label}</span>
            <span className="money-value">{amount}</span>
          </div>
          <div className="h-3 overflow-hidden rounded-full bg-muted">
            <div
              className={cn(
                'h-full rounded-full',
                Number(value) > 35 ? 'bg-coral' : Number(value) > 25 ? 'bg-warning' : 'bg-primary',
              )}
              style={{ width: `${value}%` }}
            />
          </div>
          <p className="mt-1 text-right text-xs text-muted-foreground">{value}%</p>
        </div>
      ))}
    </div>
  );
}

function SimpleDataTable() {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-muted-foreground">
          <th className="py-2">Driver</th>
          <th className="py-2 text-right">Contribution</th>
        </tr>
      </thead>
      <tbody>
        {[
          ['Car loan adjustment', '39%'],
          ['Recurring commitments', '32%'],
          ['Groceries', '8%'],
          ['Other activity', '21%'],
        ].map((row) => (
          <tr key={row[0]} className="border-t border-border">
            <td className="py-2">{row[0]}</td>
            <td className="py-2 text-right font-bold">{row[1]}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Pattern({
  title,
  value,
  change,
  icon,
}: {
  title: string;
  value: string;
  change: string;
  icon: React.ReactNode;
}) {
  return (
    <article className="border-t-2 border-border pt-5">
      <div className="flex items-center justify-between">
        <span className="grid h-10 w-10 place-items-center rounded-lg bg-muted">{icon}</span>
        <ArrowRight className="h-4 w-4 text-muted-foreground" />
      </div>
      <p className="mt-5 text-sm font-bold text-muted-foreground">{title}</p>
      <p className="money-value mt-1 text-2xl">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{change}</p>
    </article>
  );
}

function SourceRow({ name, detail, status }: { name: string; detail: string; status: string }) {
  return (
    <div className="flex flex-col gap-3 py-5 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="font-extrabold">{name}</p>
        <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
      </div>
      <Badge variant={status === 'Attention' ? 'warning' : 'success'} className="self-start">
        {status}
      </Badge>
    </div>
  );
}
function DataMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-bold text-muted-foreground">{label}</p>
      <p className="money-value mt-1 text-2xl">{value}</p>
    </div>
  );
}
function TrustFooter() {
  return (
    <footer className="flex flex-col justify-between gap-3 border-t border-border/70 pt-5 text-xs text-muted-foreground sm:flex-row">
      <p>Based on activity through 15 July · 22 transactions · Synced 6 min ago</p>
      <button type="button" className="focus-ring rounded text-left font-bold text-primary">
        See how PFIS reached this →
      </button>
    </footer>
  );
}
