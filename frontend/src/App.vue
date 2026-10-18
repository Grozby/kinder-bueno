<script setup lang="ts">
import { Database, LayoutGrid } from '@lucide/vue'
import { RouterLink, RouterView } from 'vue-router'

import { USE_MOCK } from '@/api'
import BernBear from '@/components/BernBear.vue'
import BernEater from '@/components/BernEater.vue'
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <RouterLink to="/" class="brand">
        <BernBear class="brand-logo" />
        <span class="brand-text">
          <strong>Bern Fit</strong>
          <span>Settlement scoring</span>
        </span>
      </RouterLink>

      <nav>
        <RouterLink to="/" title="Pipeline">
          <LayoutGrid :size="18" />
          <span>Pipeline</span>
        </RouterLink>
        <RouterLink to="/sources" title="Sources">
          <Database :size="18" />
          <span>Sources</span>
        </RouterLink>
      </nav>

      <span
        v-if="USE_MOCK"
        class="tag demo"
        title="Set VITE_USE_MOCK=false to use the real backend"
      >
        Demo data
      </span>
    </aside>

    <main>
      <RouterView />
    </main>
  </div>

  <BernEater />
</template>

<style scoped>
/* The app is exactly one viewport high; only areas inside a view scroll. */
.shell {
  display: grid;
  grid-template-columns: 232px 1fr;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 2rem;
  padding: 1.5rem 1rem;
  background: var(--surface);
  border-right: 1px solid var(--border);
  border-top: 4px solid var(--bern-red);
}
.brand {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0 0.5rem;
  text-decoration: none;
}
.brand-logo {
  flex: none;
  height: 56px;
  width: auto;
}
.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.15;
}
.brand-text strong {
  font-size: 19px;
}
.brand-text span {
  font-size: 13px;
  color: var(--text-muted);
}

nav {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
nav a {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.65rem 0.75rem;
  border-left: 3px solid transparent;
  border-radius: 0 var(--radius) var(--radius) 0;
  color: var(--text-muted);
  font-weight: 600;
  text-decoration: none;
}
nav a:hover {
  background: var(--surface-alt);
  color: var(--text);
}
nav a.router-link-exact-active {
  background: var(--bern-red-tint);
  border-left-color: var(--bern-red);
  color: var(--text);
}
.demo {
  margin-top: auto;
  align-self: flex-start;
}

main {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

@media (max-width: 900px) {
  .shell {
    grid-template-columns: 64px 1fr;
  }
  .sidebar {
    padding: 1rem 0.5rem;
    align-items: center;
  }
  .brand {
    padding: 0;
  }
  .brand-logo {
    height: 44px;
  }
  .brand-text,
  nav a span,
  .demo {
    display: none;
  }
  nav a {
    justify-content: center;
    padding: 0.65rem;
  }
}
</style>
