<script setup lang="ts">
import { Archive, Database, LayoutGrid, UserRound } from '@lucide/vue'
import { onMounted } from 'vue'
import { RouterLink, RouterView, useRouter } from 'vue-router'

import { USE_MOCK } from '@/api'
import BernBear from '@/components/BernBear.vue'
import BernEater from '@/components/BernEater.vue'
import NamePrompt from '@/components/NamePrompt.vue'
import { askReviewerName, reviewerName } from '@/composables/reviewer'
import { useCasesStore } from '@/stores/cases'

const store = useCasesStore()
const router = useRouter()

// The panel lives on the board, so go there first when opened from another page
async function openDiscarded() {
  await router.push('/')
  store.showDiscarded = true
}

// Load the cases at start, so the discarded count is right on every page
onMounted(() => {
  if (!store.cases.length) store.load()
})
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

      <div class="sidebar-foot">
        <span
          v-if="USE_MOCK"
          class="tag demo"
          title="Set VITE_USE_MOCK=false to use the real backend"
        >
          Demo data
        </span>
        <button
          class="discarded"
          title="Discarded cases: restore a card from here"
          @click="openDiscarded"
        >
          <Archive :size="15" />
          <span>Discarded</span>
          <span class="count">{{ store.byStatus.rejected.length }}</span>
        </button>
        <button
          v-if="reviewerName"
          class="user"
          title="Your name, shown with your scores and notes. Click to change."
          @click="askReviewerName"
        >
          <UserRound :size="15" />
          <span>{{ reviewerName }}</span>
        </button>
      </div>
    </aside>

    <main>
      <RouterView />
    </main>
  </div>

  <BernEater />
  <NamePrompt />
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
.sidebar-foot {
  margin-top: auto;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}
.user {
  flex-basis: 100%;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
  padding: 0.4rem 0.5rem;
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 14px;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
}
.user span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user svg {
  flex: none;
  color: var(--text-muted);
}
.user:hover {
  background: var(--surface-alt);
}
.user:focus-visible {
  outline: 2px solid var(--focus);
}
.discarded {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.25rem 0.5rem;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text-muted);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.discarded:hover {
  border-color: var(--text);
  color: var(--text);
}
.discarded:focus-visible {
  outline: 2px solid var(--focus);
}
.discarded .count {
  min-width: 20px;
  padding: 0 0.3rem;
  border-radius: var(--radius);
  background: var(--text);
  color: #fff;
  text-align: center;
  font-size: 12px;
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
  .discarded > span:not(.count),
  .user span,
  .demo {
    display: none;
  }
  .sidebar-foot {
    justify-content: center;
  }
  nav a {
    justify-content: center;
    padding: 0.65rem;
  }
}
</style>
