import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import { invalidateFinancialChangeDomains } from './financialChangeQueries';

describe('invalidateFinancialChangeDomains', () => {
  it('invalidates mapped views only for the current user', async () => {
    const client = new QueryClient();
    client.setQueryData(['accounts', 'user-a'], { value: 'a' });
    client.setQueryData(['netWorth', 'user-a'], { value: 'a' });
    client.setQueryData(['transactions', 'user-a', 9, 2026], { value: 'a' });
    client.setQueryData(['accounts', 'user-b'], { value: 'b' });

    await invalidateFinancialChangeDomains(client, 'user-a', ['accounts']);

    expect(client.getQueryState(['accounts', 'user-a'])?.isInvalidated).toBe(true);
    expect(client.getQueryState(['netWorth', 'user-a'])?.isInvalidated).toBe(true);
    expect(client.getQueryState(['transactions', 'user-a', 9, 2026])?.isInvalidated).toBe(false);
    expect(client.getQueryState(['accounts', 'user-b'])?.isInvalidated).toBe(false);
    client.clear();
  });

  it('fails closed by invalidating all views for an unknown future domain', async () => {
    const client = new QueryClient();
    client.setQueryData(['accounts', 'user-a'], { value: 'a' });
    client.setQueryData(['transactions', 'user-a', 9, 2026], { value: 'a' });
    client.setQueryData(['accounts', 'user-b'], { value: 'b' });

    await invalidateFinancialChangeDomains(client, 'user-a', ['new_financial_domain']);

    expect(client.getQueryState(['accounts', 'user-a'])?.isInvalidated).toBe(true);
    expect(client.getQueryState(['transactions', 'user-a', 9, 2026])?.isInvalidated).toBe(true);
    expect(client.getQueryState(['accounts', 'user-b'])?.isInvalidated).toBe(false);
    client.clear();
  });

  it('refreshes learned merchant rules after activity or source-data changes', async () => {
    const client = new QueryClient();
    client.setQueryData(['learnedMerchantRules', 'user-a'], [{ merchant: 'Cafe' }]);
    client.setQueryData(['learnedMerchantRules', 'user-b'], [{ merchant: 'Cafe' }]);

    await invalidateFinancialChangeDomains(client, 'user-a', ['activity']);

    expect(client.getQueryState(['learnedMerchantRules', 'user-a'])?.isInvalidated).toBe(true);
    expect(client.getQueryState(['learnedMerchantRules', 'user-b'])?.isInvalidated).toBe(false);
    client.getQueryCache().clear();

    client.setQueryData(['learnedMerchantRules', 'user-a'], [{ merchant: 'Cafe' }]);
    await invalidateFinancialChangeDomains(client, 'user-a', ['data']);
    expect(client.getQueryState(['learnedMerchantRules', 'user-a'])?.isInvalidated).toBe(true);
    client.clear();
  });

  it('refreshes subscription review after activity changes', async () => {
    const client = new QueryClient();
    client.setQueryData(['subscriptionReview', 'user-a'], { items: [] });
    client.setQueryData(['subscriptionReview', 'user-b'], { items: [] });

    await invalidateFinancialChangeDomains(client, 'user-a', ['activity']);

    expect(client.getQueryState(['subscriptionReview', 'user-a'])?.isInvalidated).toBe(true);
    expect(client.getQueryState(['subscriptionReview', 'user-b'])?.isInvalidated).toBe(false);
    client.clear();
  });

  it('refreshes cash pocket balance after activity or account changes', async () => {
    const client = new QueryClient();
    for (const domain of ['activity', 'accounts', 'statements']) {
      client.setQueryData(['cashPocketBalance', 'user-a', 'cash-1'], { balance: 1200 });
      client.setQueryData(['cashPocketBalance', 'user-b', 'cash-1'], { balance: 500 });

      await invalidateFinancialChangeDomains(client, 'user-a', [domain]);

      expect(client.getQueryState(['cashPocketBalance', 'user-a', 'cash-1'])?.isInvalidated).toBe(
        true,
      );
      expect(client.getQueryState(['cashPocketBalance', 'user-b', 'cash-1'])?.isInvalidated).toBe(
        false,
      );
      client.getQueryCache().clear();
    }
    client.clear();
  });

  it('invalidates Financial Horizon after today, planning, or card changes', async () => {
    const client = new QueryClient();
    for (const domain of ['today', 'planning', 'cards']) {
      client.setQueryData(['horizon', 'user-a', 30], { value: domain });
      client.setQueryData(['horizon', 'user-b', 30], { value: 'other-user' });

      await invalidateFinancialChangeDomains(client, 'user-a', [domain]);

      expect(client.getQueryState(['horizon', 'user-a', 30])?.isInvalidated).toBe(true);
      expect(client.getQueryState(['horizon', 'user-b', 30])?.isInvalidated).toBe(false);
      client.getQueryCache().clear();
    }
    client.clear();
  });

  it('refreshes the monthly snapshot for domains that change the Insights brief', async () => {
    const client = new QueryClient();
    for (const domain of ['activity', 'today', 'insights', 'cards', 'planning', 'statements', 'data']) {
      client.setQueryData(['monthlySnapshot', 'user-a', 9, 2026], { value: domain });
      client.setQueryData(['monthlySnapshot', 'user-b', 9, 2026], { value: 'other-user' });

      await invalidateFinancialChangeDomains(client, 'user-a', [domain]);

      expect(client.getQueryState(['monthlySnapshot', 'user-a', 9, 2026])?.isInvalidated).toBe(
        true,
      );
      expect(client.getQueryState(['monthlySnapshot', 'user-b', 9, 2026])?.isInvalidated).toBe(
        false,
      );
      client.getQueryCache().clear();
    }
    client.clear();
  });
});
