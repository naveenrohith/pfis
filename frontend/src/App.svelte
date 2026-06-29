<script>
  import Overview from './views/Overview.svelte';
  import { loadSession } from './lib/session.js';

  const session = loadSession();
  const now = new Date();
  const month = now.getMonth() + 1;
  const year = now.getFullYear();
  // Fall back to a demo user id when no session is present so the shell renders
  // during migration. Real auth is wired in the legacy dashboard and will be
  // ported alongside the remaining views.
  const userId = session?.user?.id ?? 'demo-user';
</script>

<header class="app-header">
  <h1>PFIS</h1>
  <p>Personal Finance Intelligence</p>
</header>

<main>
  <Overview {userId} {month} {year} />
</main>

<style>
  .app-header {
    padding: 1.5rem;
    border-bottom: 1px solid #e2e8f0;
  }
  .app-header h1 {
    margin: 0;
    font-size: 1.5rem;
  }
  .app-header p {
    margin: 0.25rem 0 0;
    color: #64748b;
  }
  main {
    padding: 1.5rem;
  }
</style>
