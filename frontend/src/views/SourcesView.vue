<script setup lang="ts">
import { BadgeCheck, ExternalLink, LoaderCircle, Plus, TriangleAlert } from '@lucide/vue'
import { computed, onMounted, reactive, ref } from 'vue'

import type { Source } from '@/api'
import CrawlGraph from '@/components/CrawlGraph.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseOverlay from '@/components/ui/BaseOverlay.vue'
import BaseToggle from '@/components/ui/BaseToggle.vue'
import { useSourcesStore } from '@/stores/sources'
import { hostOf, timeAgo } from '@/utils/format'

const store = useSourcesStore()

const showForm = ref(false)
const submitting = ref(false)
const formError = ref<string | null>(null)
const form = reactive({ url: '', name: '', max_depth: 2, max_pages: 50, follow_outbound: false })
const DEPTHS = [1, 2, 3, 4]

const openId = ref<string | null>(null)
const openSource = computed(() => store.sources.find((s) => s.id === openId.value) ?? null)

const totals = computed(() =>
  store.sources.reduce(
    (t, s) => ({
      pages: t.pages + s.pages,
      entities: t.entities + s.entities,
      claims: t.claims + s.verified_claims,
    }),
    { pages: 0, entities: 0, claims: 0 },
  ),
)

const urlValid = computed(() => {
  try {
    return ['http:', 'https:'].includes(new URL(form.url).protocol)
  } catch {
    return false
  }
})

async function submit() {
  if (!urlValid.value) return
  submitting.value = true
  formError.value = null
  try {
    const s = await store.add({
      ...form,
      max_pages: Math.min(500, Math.max(5, form.max_pages || 50)),
      name: form.name || undefined,
    })
    showForm.value = false
    form.url = ''
    form.name = ''
    openId.value = s.id
  } catch (e) {
    formError.value = (e as Error).message
  } finally {
    submitting.value = false
  }
}

function progress(s: Source) {
  const done = s.discovered.filter((p) => p.status !== 'queued').length
  return s.discovered.length ? Math.round((done / s.discovered.length) * 100) : 0
}

onMounted(() => {
  if (!store.sources.length) store.load()
})
</script>

<template>
  <div class="sources-page">
    <section class="intro">
      <div>
        <h1>Validated sources</h1>
        <p class="lead">
          Scores and pitches are built only from these public websites. Adding a page makes the
          crawler explore it and the pages it links to.
        </p>
      </div>
      <BaseButton variant="primary" :icon="Plus" @click="showForm = true">Add source</BaseButton>
    </section>

    <dl class="kpis toolbar">
      <div>
        <dt>Sources</dt>
        <dd>{{ store.sources.length }}</dd>
      </div>
      <div>
        <dt>Pages</dt>
        <dd>{{ totals.pages }}</dd>
      </div>
      <div>
        <dt>Entities</dt>
        <dd>{{ totals.entities }}</dd>
      </div>
      <div>
        <dt>Verified facts</dt>
        <dd>{{ totals.claims }}</dd>
      </div>
    </dl>

    <BaseOverlay
      :open="showForm"
      side="center"
      width="720px"
      title="Add a source"
      @close="showForm = false"
    >
      <form class="add" @submit.prevent="submit">
        <p class="add-intro muted">
          The crawler starts at this page and follows its links up to the chosen depth. Only facts
          that can be verified against the page text are kept.
        </p>

        <label class="field wide">
          <span class="field-label">Start page URL</span>
          <input
            v-model.trim="form.url"
            class="input"
            type="url"
            placeholder="https://www.example.unibe.ch/index_eng.html"
            required
          />
          <small v-if="form.url && !urlValid" class="score-bad">Enter a full http(s) URL.</small>
        </label>
        <label class="field wide">
          <span class="field-label">Name <span class="muted">(optional)</span></span>
          <input
            v-model.trim="form.name"
            class="input"
            type="text"
            placeholder="e.g. Institute of Example Research"
          />
        </label>

        <div class="field">
          <span class="field-label">Link depth</span>
          <div class="segmented" role="radiogroup" aria-label="Link depth">
            <button
              v-for="d in DEPTHS"
              :key="d"
              type="button"
              role="radio"
              :aria-checked="form.max_depth === d"
              :class="{ on: form.max_depth === d }"
              @click="form.max_depth = d"
            >
              {{ d }}
            </button>
          </div>
        </div>
        <label class="field">
          <span class="field-label">Max pages</span>
          <input
            v-model.number="form.max_pages"
            class="input"
            type="number"
            min="5"
            max="500"
            step="5"
          />
        </label>
        <div class="field toggle">
          <BaseToggle v-model="form.follow_outbound" label="Follow outbound links" />
          <span>
            <span class="field-label">Follow outbound links</span>
            <small class="muted">Also explore pages on other websites this page links to.</small>
          </span>
        </div>

        <div class="submit">
          <small v-if="formError" class="score-bad">{{ formError }}</small>
          <BaseButton @click="showForm = false">Cancel</BaseButton>
          <BaseButton type="submit" variant="primary" :loading="submitting" :disabled="!urlValid">
            Start crawl
          </BaseButton>
        </div>
      </form>
    </BaseOverlay>

    <p v-if="store.error" class="load-error">
      <TriangleAlert :size="16" /> The sources could not be loaded: {{ store.error }}
    </p>

    <section class="grid">
      <article
        v-for="s in store.sources"
        :key="s.id"
        class="source"
        tabindex="0"
        @click="openId = s.id"
        @keydown.enter="openId = s.id"
      >
        <div class="thumb">
          <CrawlGraph :pages="s.discovered" compact />
        </div>
        <div class="info">
          <span v-if="s.status === 'crawling'" class="tag tag-mid">
            <LoaderCircle class="spin" :size="12" /> Crawling
          </span>
          <span v-else-if="s.status === 'failed'" class="tag tag-bad">Failed</span>
          <span v-else-if="s.validated" class="tag tag-good"
            ><BadgeCheck :size="13" /> Validated</span
          >
          <span v-else class="tag">Not validated</span>

          <h3>{{ s.name }}</h3>
          <a :href="s.root_url" target="_blank" rel="noopener" class="host" @click.stop>
            {{ hostOf(s.root_url) }} <ExternalLink :size="12" />
          </a>
          <dl>
            <div>
              <dt>Pages</dt>
              <dd>{{ s.pages }}</dd>
            </div>
            <div>
              <dt>Entities</dt>
              <dd>{{ s.entities }}</dd>
            </div>
            <div>
              <dt>Verified facts</dt>
              <dd>{{ s.verified_claims }}</dd>
            </div>
          </dl>
          <div
            v-if="s.status === 'crawling'"
            class="progress"
            :aria-valuenow="progress(s)"
            role="progressbar"
          >
            <span :style="{ width: `${progress(s)}%` }" />
          </div>
          <p v-else-if="s.last_crawled_at" class="when">
            Last crawled {{ timeAgo(s.last_crawled_at) }}
          </p>
        </div>
      </article>

      <div v-if="store.loading && !store.sources.length" class="source loading">
        <LoaderCircle class="spin" :size="20" />
      </div>
    </section>

    <BaseOverlay
      :open="openSource !== null"
      side="center"
      width="1000px"
      :title="openSource?.name"
      @close="openId = null"
    >
      <div v-if="openSource" class="detail">
        <div>
          <CrawlGraph :pages="openSource.discovered" />
          <ul class="legend">
            <li><span class="lg root" /> Start page</li>
            <li><span class="lg crawled" /> Crawled</li>
            <li><span class="lg queued" /> Queued</li>
            <li><span class="lg skipped" /> Skipped</li>
            <li><span class="lg failed" /> Failed</li>
          </ul>
        </div>
        <div class="pages">
          <h3 class="section-label">Pages ({{ openSource.discovered.length }})</h3>
          <ul>
            <li v-for="p in openSource.discovered" :key="p.url" :class="`p-${p.status}`">
              <span class="depth" :title="`Depth ${p.depth}`">{{ p.depth }}</span>
              <a :href="p.url" target="_blank" rel="noopener">{{ p.url }}</a>
            </li>
          </ul>
        </div>
      </div>
    </BaseOverlay>
  </div>
</template>

<style scoped>
/* Fills <main> exactly; only the list of sources scrolls. */
.sources-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.5rem clamp(1rem, 2.5vw, 2rem);
}
.intro {
  flex: none;
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 2rem;
  flex-wrap: wrap;
}
h1 {
  font-size: clamp(28px, 3vw, 36px);
}
.lead {
  max-width: 62ch;
  margin-top: 0.5rem;
  font-size: 17px;
  color: var(--text-muted);
}

.kpis {
  flex: none;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 2rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--border);
}
.kpis div {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
}
.kpis dt {
  font-size: 14px;
  color: var(--text-muted);
}
.kpis dd {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.load-error {
  flex: none;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background: var(--bad-tint);
  color: var(--bad);
  border-radius: var(--radius);
}

.add {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1.25rem 1.5rem;
}
.add-intro {
  grid-column: 1 / -1;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.field.wide {
  grid-column: 1 / -1;
}
.field-label {
  font-size: 14px;
  font-weight: 600;
}
.field.toggle {
  flex-direction: row;
  align-items: center;
  gap: 0.75rem;
  padding-top: 1.6rem;
}
.field.toggle small {
  display: block;
  font-size: 13px;
}
.segmented {
  display: flex;
  height: 40px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  overflow: hidden;
}
.segmented button {
  flex: 1;
  border: 0;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
.segmented button + button {
  border-left: 1px solid var(--border-strong);
}
.segmented button:hover:not(.on) {
  background: var(--surface-alt);
}
.segmented button.on {
  background: var(--text);
  color: #fff;
}
.segmented button:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: -2px;
}
.submit {
  grid-column: 1 / -1;
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
}

.grid {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  align-content: start;
  gap: 1.25rem;
  padding: 2px 4px 1rem 2px;
}
.source {
  display: flex;
  gap: 1.25rem;
  padding: 1.25rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  cursor: pointer;
  transition: border-color 0.15s;
}
.source:hover {
  border-color: var(--border-strong);
}
.source:focus-visible {
  outline: 2px solid var(--focus);
}
.source.loading {
  min-height: 160px;
  justify-content: center;
  align-items: center;
  color: var(--text-muted);
}
.thumb {
  flex: none;
  width: 116px;
  aspect-ratio: 1;
  padding: 4px;
  background: var(--surface-alt);
  border-radius: var(--radius);
}
.info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.3rem;
}
.info h3 {
  font-size: 17px;
}
.host {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 14px;
  color: var(--bern-red);
  text-decoration: none;
}
.host:hover {
  text-decoration: underline;
}
dl {
  display: flex;
  gap: 1.5rem;
  margin-top: 0.5rem;
}
dt {
  font-size: 12px;
  color: var(--text-muted);
}
dd {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.progress {
  align-self: stretch;
  height: 4px;
  margin-top: 0.5rem;
  background: var(--surface-alt);
  border-radius: 2px;
  overflow: hidden;
}
.progress span {
  display: block;
  height: 100%;
  background: var(--bern-red);
  transition: width 0.5s;
}
.when {
  margin-top: 0.4rem;
  font-size: 13px;
  color: var(--text-faint);
}

.detail {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) minmax(280px, 1fr);
  gap: 2rem;
}
.legend {
  list-style: none;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 1rem;
  margin-top: 0.5rem;
  font-size: 13px;
  color: var(--text-muted);
}
.lg {
  display: inline-block;
  width: 10px;
  height: 10px;
  margin-right: 0.3rem;
  border-radius: 50%;
}
.lg.root {
  background: var(--bern-red);
}
.lg.crawled {
  background: var(--text);
}
.lg.queued {
  background: var(--text-faint);
}
.lg.skipped {
  background: var(--border-strong);
}
.lg.failed {
  border: 2px solid var(--bad);
}
.pages h3 {
  margin-bottom: 0.75rem;
}
.pages ul {
  list-style: none;
  padding: 0;
  max-height: 440px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-family: var(--mono);
  font-size: 12.5px;
}
.pages li {
  display: flex;
  gap: 0.75rem;
  padding: 0.4rem 0.75rem;
}
.pages li + li {
  border-top: 1px solid var(--border);
}
.pages a {
  color: var(--text);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pages a:hover {
  color: var(--bern-red);
  text-decoration: underline;
}
.depth {
  flex: none;
  width: 1rem;
  color: var(--text-faint);
}
.p-skipped a,
.p-queued a {
  color: var(--text-faint);
}
.p-failed a {
  color: var(--bad);
}

@media (max-width: 1100px) {
  .lead {
    display: none;
  }
}
@media (max-width: 760px) {
  .kpis {
    gap: 0.5rem 1rem;
  }
  .add {
    grid-template-columns: 1fr;
  }
  .field.toggle {
    padding-top: 0;
  }
  .grid {
    grid-template-columns: 1fr;
  }
  .detail {
    grid-template-columns: 1fr;
  }
}
</style>
