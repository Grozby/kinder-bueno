<script setup lang="ts">
const model = defineModel<boolean>({ required: true })
defineProps<{ label: string }>()
</script>

<template>
  <button
    type="button"
    role="switch"
    class="toggle"
    :class="{ on: model }"
    :aria-checked="model"
    :aria-label="label"
    @click="model = !model"
  >
    <span class="knob" />
  </button>
</template>

<style scoped>
.toggle {
  flex: none;
  position: relative;
  width: 40px;
  height: 22px;
  border-radius: 999px;
  border: 0;
  background: var(--border-strong);
  cursor: pointer;
  transition: background-color 0.15s;
}
.toggle.on {
  background: var(--bern-red);
}
.toggle:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}
.knob {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.15s;
}
.on .knob {
  transform: translateX(18px);
}
</style>
