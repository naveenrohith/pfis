<script>
  import { api } from '../lib/api.js';

  export let userId;
  export let month;
  export let year;

  // Svelte auto-escapes interpolated values, preserving the XSS safety the
  // legacy dashboard achieved manually via escapeHtml().
  let loading = true;
  let error = null;
  let summary = null;

  function formatCurrency(value) {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0,
    }).format(value ?? 0);
  }

  async function load() {
    loading = true;
    error = null;
    try {
      summary = await api.transactionSummary(userId, month, year);
    } catch (err) {
      error = err.message;
    } finally {
      loading = false;
    }
  }

  load();
</script>

<section aria-live="polite">
  <h2>Overview — {year}-{String(month).padStart(2, '0')}</h2>

  {#if loading}
    <p>Loading…</p>
  {:else if error}
    <p role="alert" class="error">{error}</p>
  {:else if summary}
    <div class="metrics">
      <article>
        <span class="label">Total spend</span>
        <span class="value">{formatCurrency(summary.total_spend)}</span>
      </article>
      <article>
        <span class="label">Total income</span>
        <span class="value">{formatCurrency(summary.total_income)}</span>
      </article>
      <article>
        <span class="label">Transactions</span>
        <span class="value">{summary.transaction_count ?? 0}</span>
      </article>
    </div>
  {/if}
</section>

<style>
  .metrics {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1rem;
  }
  article {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    padding: 1rem;
    border: 1px solid #e2e8f0;
    border-radius: 0.5rem;
  }
  .label {
    color: #64748b;
    font-size: 0.85rem;
  }
  .value {
    font-size: 1.5rem;
    font-weight: 600;
  }
  .error {
    color: #b91c1c;
  }
</style>
