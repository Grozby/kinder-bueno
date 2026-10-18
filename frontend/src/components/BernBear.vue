<script setup lang="ts">
// The Canton Bern logo (crown, shield, bend, bear) redrawn as monochrome SVG in currentColor.
// The bear's lower jaw is its own group, so it can open (`open`) and chew (`chomping`).
import { useId } from 'vue'

defineProps<{ open?: boolean; chomping?: boolean }>()
const clipId = `bern-shield-${useId()}`

const SHIELD = 'M14 72 H106 V150 C106 178 86 196 60 204 C34 196 14 178 14 150 Z'
</script>

<template>
  <svg
    class="bern-logo"
    :class="{ open, chomping }"
    viewBox="0 0 120 210"
    role="img"
    aria-label="Canton Bern logo"
  >
    <defs>
      <clipPath :id="clipId">
        <path :d="SHIELD" />
      </clipPath>
    </defs>

    <!-- crown -->
    <g fill="#fff" stroke="currentColor" stroke-width="3.5" stroke-linejoin="round">
      <path
        d="M16 56 L16 46 Q16 38 23 39 Q29 41 26 47 Q34 52 38 44 Q42 34 48 40 Q52 44 56 38 L60 26
           L64 38 Q68 44 72 40 Q78 34 82 44 Q86 52 94 47 Q91 41 97 39 Q104 38 104 46 L104 56 Z"
      />
      <rect x="16" y="56" width="88" height="8" />
    </g>

    <!-- shield with bend -->
    <path :d="SHIELD" fill="#fff" />
    <g :clip-path="`url(#${clipId})`">
      <rect
        x="-90"
        y="-15"
        width="180"
        height="30"
        transform="translate(60 128) rotate(35)"
        fill="#fff"
        stroke="currentColor"
        stroke-width="3"
      />

      <!-- bear walking up the bend, facing left -->
      <g transform="translate(60 126) rotate(35) scale(0.95)" fill="currentColor">
        <ellipse cx="4" cy="0" rx="28" ry="15" />
        <ellipse cx="-16" cy="-6" rx="14" ry="13" />
        <circle cx="-30" cy="-14" r="10" />
        <circle cx="-26" cy="-24" r="4.5" />
        <!-- upper snout, rounded towards the nose; the fangs sit behind the closed jaw -->
        <path d="M-35 -22 C-41 -22.5 -47 -21 -50.5 -17.5 Q-53 -14 -50 -11.8 L-35 -11 Z" />
        <circle cx="-50.5" cy="-17" r="2" />
        <path
          d="M-48.5 -12 L-47.6 -8.6 L-46.4 -12 Z M-42 -11.6 L-41.2 -9 L-40.2 -11.5 Z"
          fill="#fff"
        />
        <circle cx="32" cy="-6" r="4" />
        <g stroke="currentColor" stroke-width="8" stroke-linecap="round" fill="none">
          <path d="M-20 4 L-35 9" />
          <path d="M-10 10 L-12 25" />
          <path d="M18 8 L14 25" />
          <path d="M28 6 L35 22" />
        </g>
        <g stroke="currentColor" stroke-width="1.6" stroke-linecap="round" fill="none">
          <path d="M-38 8 l-4 -2 M-38 10 l-4 2 M-36 12 l-2 4" />
          <path
            d="M-14 28 l-4 1 M-12 29 l-1 4 M12 28 l-4 1 M14 29 l-1 4 M36 25 l-2 4 M38 23 l3 3"
          />
        </g>
        <circle cx="-33" cy="-17" r="1.7" fill="#fff" />
        <g transform="translate(-36 -8)">
          <g class="jaw">
            <path d="M2 -3 C-4 -3.2 -10 -2.4 -13 -0.6 Q-15.5 1.6 -13 3.4 C-9 5.2 -3 5.6 2 4.2 Z" />
            <path d="M0 -2 Q-6 -3.6 -11 -1.2 Q-7 0.6 0 0 Z" fill="var(--bern-red)" />
            <path class="fang" d="M-11 -1.4 L-10.2 -4.4 L-9.2 -1.6 Z" fill="#fff" />
          </g>
        </g>
      </g>
    </g>
    <path :d="SHIELD" fill="none" stroke="currentColor" stroke-width="3.5" />
  </svg>
</template>

<style scoped>
.bern-logo {
  display: block;
  color: var(--bern-black);
  overflow: visible;
}
.jaw {
  transform-origin: 0 0;
  transition: transform 0.22s cubic-bezier(0.3, 1.4, 0.5, 1);
}
.open .jaw {
  transform: rotate(-38deg);
}
/* The lower fang would poke over the upper snout while the mouth is shut */
.fang {
  opacity: 0;
  transition: opacity 0.1s;
}
.open .fang,
.chomping .fang {
  opacity: 1;
}
.chomping .jaw {
  animation: chomp 0.18s cubic-bezier(0.4, 0, 0.6, 1) 3;
}
@keyframes chomp {
  50% {
    transform: rotate(-22deg);
  }
}
</style>
