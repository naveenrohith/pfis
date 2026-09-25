import { describe, expect, it } from 'vitest';
import { queryKeys } from './queries';

describe('learnedMerchantRules query key', () => {
  it('keeps learned-rule caches scoped to the owning user', () => {
    expect(queryKeys.learnedMerchantRules('user-a')).toEqual(['learnedMerchantRules', 'user-a']);
    expect(queryKeys.learnedMerchantRules('user-b')).toEqual(['learnedMerchantRules', 'user-b']);
  });

  it('scopes Financial Horizon caches by user and horizon length', () => {
    expect(queryKeys.horizon('user-a')).toEqual(['horizon', 'user-a', 30]);
    expect(queryKeys.horizon('user-a', 90)).toEqual(['horizon', 'user-a', 90]);
    expect(queryKeys.horizon('user-b')).toEqual(['horizon', 'user-b', 30]);
  });
});
