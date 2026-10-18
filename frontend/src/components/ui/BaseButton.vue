<script setup lang="ts">
import { LoaderCircle } from '@lucide/vue'
import type { Component } from 'vue'

withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
    size?: 'sm' | 'md'
    icon?: Component
    loading?: boolean
    disabled?: boolean
    type?: 'button' | 'submit'
  }>(),
  { variant: 'secondary', size: 'md', type: 'button' },
)
</script>

<template>
  <button
    :type="type"
    class="btn"
    :class="[`btn-${variant}`, `btn-${size}`]"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
  >
    <LoaderCircle v-if="loading" class="spin" :size="size === 'sm' ? 14 : 16" />
    <component :is="icon" v-else-if="icon" :size="size === 'sm' ? 14 : 16" />
    <span v-if="$slots.default"><slot /></span>
  </button>
</template>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  border: 1px solid transparent;
  border-radius: var(--radius);
  font: inherit;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  transition:
    background-color 0.15s,
    border-color 0.15s,
    color 0.15s;
}
.btn:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn-md {
  height: 38px;
  padding: 0 1rem;
  font-size: 14px;
}
.btn-sm {
  height: 30px;
  padding: 0 0.7rem;
  font-size: 13px;
}

.btn-primary {
  background: var(--bern-red);
  color: #fff;
}
.btn-primary:hover:not(:disabled) {
  background: var(--bern-red-dark);
}
.btn-secondary {
  background: var(--surface);
  border-color: var(--border-strong);
  color: var(--text);
}
.btn-secondary:hover:not(:disabled) {
  border-color: var(--text);
}
.btn-ghost {
  background: transparent;
  color: var(--text-muted);
}
.btn-ghost:hover:not(:disabled) {
  background: var(--surface-alt);
  color: var(--text);
}
.btn-danger {
  background: var(--surface);
  border-color: var(--bern-red);
  color: var(--bern-red);
}
.btn-danger:hover:not(:disabled) {
  background: var(--bern-red);
  color: #fff;
}

.spin {
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
