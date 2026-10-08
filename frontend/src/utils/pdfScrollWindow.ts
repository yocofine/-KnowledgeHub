/** Keep the visible pages and one neighbouring page warm, not the whole PDF. */
export function pdfScrollWindow(visible: number[], total: number): number[] {
  if (total < 1) return []
  const pages = [...new Set(visible.filter(n => Number.isInteger(n) && n >= 1 && n <= total))].sort((a, b) => a - b).slice(0, 3)
  if (!pages.length) pages.push(1)
  const result = new Set<number>()
  for (const page of pages) {
    for (const n of [page - 1, page, page + 1]) if (n >= 1 && n <= total) result.add(n)
  }
  return [...result].sort((a, b) => a - b)
}

/** Rendering stays serial even when a wheel movement exposes several pages. */
export function createPdfRenderQueue() {
  const pending: Array<{ job: () => Promise<unknown>; priority: number; order: number; resolve: (value: unknown) => void; reject: (reason: unknown) => void }> = []
  let running = false
  let order = 0
  async function drain() {
    if (running) return
    running = true
    try {
      while (pending.length) {
        pending.sort((a, b) => a.priority - b.priority || a.order - b.order)
        const item = pending.shift()!
        try { item.resolve(await item.job()) } catch (reason) { item.reject(reason) }
      }
    } finally { running = false }
  }
  return <T>(job: () => Promise<T>, priority = 0): Promise<T> => {
    const result = new Promise<T>((resolve, reject) => {
      pending.push({ job, priority, order: order++, resolve: value => resolve(value as T), reject })
    })
    // Batch the current mount before choosing visible pages over neighbours.
    queueMicrotask(() => { void drain() })
    return result
  }
}
