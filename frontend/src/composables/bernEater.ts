// Bridge between cards and the single <BernEater> overlay mounted in App.vue.
type EatFn = (el: HTMLElement) => Promise<void>

// Where the bear's mouth sits in <BernBear>, as a fraction of the logo's width and height
export const BEAR_MOUTH = { x: 32 / 120, y: 97 / 210 }

let eater: EatFn | null = null

export function registerBernEater(fn: EatFn | null) {
  eater = fn
}

// Animates the bear eating `el`. Resolves when the animation is over (at once if no overlay).
export function feedTheBear(el: HTMLElement): Promise<void> {
  return eater ? eater(el) : Promise.resolve()
}
