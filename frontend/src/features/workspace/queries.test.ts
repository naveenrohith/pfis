import { describe, expect, it } from 'vitest';
import { queryKeys } from './queries';

describe('learnedMerchantRules query key', () => {
  it('keeps learned-rule caches scoped to the owning user', () => {
    expect(queryKeys.learnedMerchantRules('user-a')).toEqual(['learnedMerchantRules', 'user-a']);
    expect(queryKeys.learnedMerchantRules('user-b')).toEqual(['learnedMerchantRules', 'user-b']);
  });
});
