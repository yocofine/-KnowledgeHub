import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'
import ts from 'typescript'
import { runInNewContext } from 'node:vm'
import { createPdfRenderQueue, pdfScrollWindow } from './pdfScrollWindow'

test('first page preloads its neighbour, scrolling forward and back shifts the window', () => {
  assert.deepEqual(pdfScrollWindow([1], 100), [1, 2])
  assert.deepEqual(pdfScrollWindow([2], 100), [1, 2, 3])
  assert.deepEqual(pdfScrollWindow([8, 9], 100), [7, 8, 9, 10])
  assert.deepEqual(pdfScrollWindow([2], 100), [1, 2, 3])
  assert.deepEqual(pdfScrollWindow([100], 100), [99, 100])
})
test('invalid pages and large PDFs never request the full document window', () => {
  assert.deepEqual(pdfScrollWindow([0, -1, NaN, 1.5, 1001], 1000), [1, 2])
  assert.deepEqual(pdfScrollWindow([1], 1), [1])
  assert.deepEqual(pdfScrollWindow([1], 0), [])
  assert.ok(pdfScrollWindow(Array.from({ length: 1000 }, (_, n) => n + 1), 1000).length <= 5)
})
test('multiple pages render serially and one failed page does not block the queue', async () => {
  const enqueue = createPdfRenderQueue()
  let active = 0
  let maximum = 0
  const order: number[] = []
  const job = (page: number) => async () => {
    maximum = Math.max(maximum, ++active)
    await Promise.resolve()
    order.push(page)
    active--
    if (page === 2) throw new Error('failed page')
    return page
  }
  const results = await Promise.allSettled([enqueue(job(1)), enqueue(job(2)), enqueue(job(3))])
  assert.equal(maximum, 1)
  assert.deepEqual(order, [1, 2, 3])
  assert.deepEqual(results.map(result => result.status), ['fulfilled', 'rejected', 'fulfilled'])
})
test('scrolling uses observed page slots, preserves position and releases distant canvases', () => {
  const viewer = readFileSync(new URL('../components/PdfRangePreview.vue', import.meta.url), 'utf8')
  const page = readFileSync(new URL('../components/PdfScrollPage.vue', import.meta.url), 'utf8')
  assert.match(viewer, /v-for="page in pageCount"/)
  assert.match(viewer, /new IntersectionObserver/)
  assert.match(viewer, /@scroll.passive="onScroll"/)
  assert.match(viewer, /pdf && wanted.has\(page\)/)
  assert.match(viewer, /if \(previous === value\) return/)
  assert.doesNotMatch(page, /scrollTop|scrollIntoView/)
  assert.match(page, /canvas.value.width = 0/)
  assert.match(page, /pdfPage\?\.cleanup\(\)/)
  for (const source of [viewer, page]) {
    const { descriptor, errors } = parse(source)
    assert.deepEqual(errors, [])
    const script = compileScript(descriptor, { id: 'scroll-test' })
    assert.deepEqual(compileTemplate({ source: descriptor.template!.content, filename: 'Pdf.vue', id: 'scroll-test', compilerOptions: { bindingMetadata: script.bindings } }).errors, [])
  }
})
test('a visible page takes priority over a neighbouring prefetch', async () => {
  const enqueue = createPdfRenderQueue()
  const order: number[] = []
  await Promise.all([
    enqueue(async () => { order.push(99) }, 1),
    enqueue(async () => { order.push(100) }, 0),
    enqueue(async () => { order.push(101) }, 1),
  ])
  assert.deepEqual(order, [100, 99, 101])
})
test('actual scroll visibility updates current page and does not loop on unchanged observations', () => {
  const source = readFileSync(new URL('../components/PdfRangePreview.vue', import.meta.url), 'utf8')
  const script = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)![1]!
  const ast = ts.createSourceFile('Pdf.ts', script, ts.ScriptTarget.Latest, true)
  const update = ast.statements.find(statement => ts.isFunctionDeclaration(statement) && statement.name?.text === 'updateWindow')!
  const compiled = ts.transpileModule(update.getText(ast), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  const visiblePages = new Set([1])
  const wanted = { value: new Set([1, 2]) }
  const pageNumber = { value: 1 }
  const pageInput = { value: 1 }
  const bottoms = new Map([[1, 800], [2, 900], [8, 500], [9, 1200]])
  const elements = new Map([...bottoms].map(([number]) => [number, { getBoundingClientRect: () => ({ bottom: bottoms.get(number)! }) }]))
  const updateWindow = runInNewContext(compiled + '\nupdateWindow', {
    scroll: { value: { clientHeight: 600, getBoundingClientRect: () => ({ top: 0 }) } },
    pdf: { value: {} }, pageCount: { value: 100 }, pageNumber, pageInput, visiblePages, wanted, elements, pdfScrollWindow,
  }) as () => void
  const initial = wanted.value
  updateWindow()
  assert.equal(wanted.value, initial)
  visiblePages.add(2)
  bottoms.set(1, 100)
  updateWindow()
  assert.equal(pageNumber.value, 2)
  assert.deepEqual([...wanted.value], [1, 2, 3])
  visiblePages.clear(); visiblePages.add(8); visiblePages.add(9)
  updateWindow()
  assert.equal(pageNumber.value, 8)
  assert.deepEqual([...wanted.value], [7, 8, 9, 10])
  visiblePages.clear(); visiblePages.add(1); bottoms.set(1, 800)
  updateWindow()
  assert.equal(pageNumber.value, 1)
  assert.deepEqual([...wanted.value], [1, 2])
})
