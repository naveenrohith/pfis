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
});
