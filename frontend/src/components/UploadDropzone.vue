<script setup lang="ts">
import { LoaderCircle, Upload } from '@lucide/vue'
import { ref, useTemplateRef } from 'vue'

const props = defineProps<{ busy?: boolean }>()
const emit = defineEmits<{ files: [files: File[]]; invalid: [names: string[]] }>()

const over = ref(false)
const input = useTemplateRef<HTMLInputElement>('input')

function isPdf(f: File) {
  return f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf')
}

function take(list: FileList | null | undefined) {
  const files = [...(list ?? [])]
  const pdfs = files.filter(isPdf)
  const rejected = files.filter((f) => !isPdf(f)).map((f) => f.name)
  if (rejected.length) emit('invalid', rejected)
  if (pdfs.length) emit('files', pdfs)
}

function onDrop(e: DragEvent) {
  over.value = false
  take(e.dataTransfer?.files)
}

function onDragOver(e: DragEvent) {
  // Only react to files, not to cards being dragged around the board
  if (!e.dataTransfer?.types.includes('Files')) return
  e.preventDefault()
  over.value = true
}

function onPick(e: Event) {
  take((e.target as HTMLInputElement).files)
  ;(e.target as HTMLInputElement).value = ''
}
</script>

<template>
  <div
    class="dropzone"
    :class="{ over }"
    role="button"
    tabindex="0"
    @click="input?.click()"
    @keydown.enter="input?.click()"
    @dragover="onDragOver"
    @dragleave="over = false"
    @drop.prevent="onDrop"
  >
    <input ref="input" type="file" accept="application/pdf,.pdf" multiple hidden @change="onPick" />
    <LoaderCircle v-if="props.busy" class="icon spin" :size="22" />
    <Upload v-else class="icon" :size="22" />
    <div>
      <strong>{{ props.busy ? 'Uploading…' : 'Upload business model (PDF)' }}</strong>
      <p>Drag and drop or click to choose a file. The analysis starts on upload.</p>
    </div>
  </div>
</template>

<style scoped>
.dropzone {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.25rem;
  border: 1.5px dashed var(--border-strong);
  border-radius: var(--radius-lg);
  background: var(--surface);
  cursor: pointer;
  transition:
    border-color 0.15s,
    background-color 0.15s;
}
.dropzone:hover {
  border-color: var(--text);
}
.dropzone:focus-visible {
  outline: 2px solid var(--focus);
}
.dropzone.over {
  border-style: solid;
  border-color: var(--bern-red);
  background: var(--bern-red-tint);
}
.icon {
  flex: none;
  color: var(--bern-red);
}
strong {
  font-size: 17px;
}
p {
  font-size: 15px;
  color: var(--text-muted);
}
</style>
