<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { getDocument, GlobalWorkerOptions, type PDFDocumentLoadingTask, type PDFDocumentProxy } from 'pdfjs-dist'
import 'pdfjs-dist/web/pdf_viewer.css'
import { getApiBaseUrl } from '@/utils/api-base'
import { knowledgePdfRangeOptions } from '@/utils/pdfRangePreview'
import { refreshAccessTokenShared } from '@/utils/authRefresh'
import { createPdfRenderQueue, pdfScrollWindow } from '@/utils/pdfScrollWindow'
import PdfScrollPage from './PdfScrollPage.vue'

const props = defineProps<{ knowledgeId: string; active: boolean; fileName: string }>()
GlobalWorkerOptions.workerSrc = import.meta.env.BASE_URL + 'pdfjs/pdf.worker.min.js'
const scroll = ref<HTMLElement | null>(null)
const pdf = shallowRef<PDFDocumentProxy>()
const pageNumber = ref(1)
const pageCount = ref(0)
const pageInput = ref(1)
const zoom = ref(1)
const fitWidth = ref(800)
const busy = ref(true)
const error = ref('')
const receivedKB = ref(0)
const wanted = ref(new Set([1]))
const ratios = ref<Record<number, number>>({})
const failures = ref<Record<number, string>>({})
const retries = ref<Record<number, number>>({})
const firstRatio = ref(1.414)
const elements = new Map<number, HTMLElement>()
const visiblePages = new Set<number>()
let enqueue = createPdfRenderQueue()
let loadingTask: PDFDocumentLoadingTask | undefined
let generation = 0
let stallTimer: ReturnType<typeof setTimeout> | undefined
let resizeTimer: ReturnType<typeof setTimeout> | undefined
let resizeObserver: ResizeObserver | undefined
let intersection: IntersectionObserver | undefined
let scrollFrame = 0

function clearTimer() { if (stallTimer) clearTimeout(stallTimer); stallTimer = undefined }
function armTimer(scope: number) {
  clearTimer()
  stallTimer = setTimeout(() => {
    if (scope !== generation || !busy.value) return
    error.value = '文件读取暂时没有响应，请重试。'
    busy.value = false
    void loadingTask?.destroy().catch(() => {})
  }, 90000)
}
function dispose() {
  generation++
  clearTimer()
  intersection?.disconnect()
  intersection = undefined
  visiblePages.clear()
  if (scrollFrame) cancelAnimationFrame(scrollFrame)
  scrollFrame = 0
  void loadingTask?.destroy().catch(() => {})
  loadingTask = undefined
  pdf.value = undefined
  enqueue = createPdfRenderQueue()
}
function pageElement(page: number, value: unknown) {
  const previous = elements.get(page)
  if (previous === value) return
  if (previous) intersection?.unobserve(previous)
  if (value instanceof HTMLElement) {
    elements.set(page, value)
    intersection?.observe(value)
  } else elements.delete(page)
}
function updateWindow() {
  if (!scroll.value || !pdf.value) return
  const pages = [...visiblePages].sort((a, b) => a - b)
  if (!pages.length) return
  const center = scroll.value.getBoundingClientRect().top + scroll.value.clientHeight * .3
  const current = pages.find(page => (elements.get(page)?.getBoundingClientRect().bottom || 0) > center) || pages[pages.length - 1]
  if (pageNumber.value !== current) pageNumber.value = pageInput.value = current
  const next = pdfScrollWindow(pages, pageCount.value)
  if (next.length !== wanted.value.size || next.some(page => !wanted.value.has(page))) wanted.value = new Set(next)
}
function onScroll() {
  if (scrollFrame) return
  scrollFrame = requestAnimationFrame(() => { scrollFrame = 0; updateWindow() })
}
function observePages() {
  intersection?.disconnect()
  visiblePages.clear()
  intersection = new IntersectionObserver(entries => {
    for (const entry of entries) {
      const page = Number((entry.target as HTMLElement).dataset.page)
      if (entry.isIntersecting) visiblePages.add(page)
      else visiblePages.delete(page)
    }
    updateWindow()
  }, { root: scroll.value, threshold: 0 })
  for (const element of elements.values()) intersection.observe(element)
}
function pageReady(page: number) {
  busy.value = false
  clearTimer()
  delete failures.value[page]
  if (page === 1 && pageCount.value > 1 && pageNumber.value === 1) wanted.value = new Set([...wanted.value, 2])
}
function pageFailure(page: number, message: string) {
  busy.value = false
  clearTimer()
  failures.value[page] = message
}
async function load(refreshed = false) {
  dispose()
  const scope = generation
  if (!props.active) return
  pageNumber.value = pageInput.value = 1
  pageCount.value = 0
  zoom.value = 1
  busy.value = true
  error.value = ''
  receivedKB.value = 0
  ratios.value = {}
  failures.value = {}
  retries.value = {}
  wanted.value = new Set([1])
  if (scroll.value) scroll.value.scrollTop = 0
  const assets = import.meta.env.BASE_URL + 'pdfjs/'
  try {
    const options = knowledgePdfRangeOptions(props.knowledgeId, getApiBaseUrl(),
      localStorage.getItem('weknora_token') || '', localStorage.getItem('weknora_selected_tenant_id') || '')
    const task = getDocument({ ...options, cMapUrl: assets + 'cmaps/', cMapPacked: true,
      standardFontDataUrl: assets + 'standard_fonts/', wasmUrl: assets + 'wasm/', iccUrl: assets + 'iccs/' })
    loadingTask = task
    task.onProgress = ({ loaded }: { loaded: number }) => {
      if (scope !== generation) return
      receivedKB.value = Math.round(loaded / 1024)
      if (busy.value) armTimer(scope)
    }
    armTimer(scope)
    const document = await task.promise
    const first = await document.getPage(1)
    if (scope !== generation) return
    const viewport = first.getViewport({ scale: 1 })
    firstRatio.value = viewport.height / viewport.width
    fitWidth.value = Math.min(1000, Math.max(200, (scroll.value?.clientWidth || 832) - 32))
    pageCount.value = document.numPages
    pdf.value = document
    await nextTick()
    if (scope === generation && props.active) observePages()
  } catch (reason: any) {
    if (scope === generation && props.active && reason?.status === 401 && !refreshed) {
      try {
        await refreshAccessTokenShared()
        if (scope === generation && props.active) await load(true)
        return
      } catch { /* Existing auth flow handles failed refresh. */ }
    }
    if (scope === generation && props.active) {
      error.value = reason?.name === 'PasswordException' ? '此 PDF 已加密，请下载后输入密码打开。'
        : reason?.status === 401 ? '登录已过期，请重新登录后预览。'
        : reason?.status === 403 ? '你没有权限预览此文件。'
        : reason?.message || 'PDF 加载失败，请重试。'
      busy.value = false
      clearTimer()
    }
  }
}
function goToPage(value: number) {
  if (!pdf.value) return
  const target = Math.min(pageCount.value, Math.max(1, Math.round(Number(value) || 1)))
  pageNumber.value = pageInput.value = target
  wanted.value = new Set(pdfScrollWindow([target], pageCount.value))
  scrollToCurrentPage()
}
function scrollToCurrentPage() {
  const element = elements.get(pageNumber.value)
  if (element && scroll.value) scroll.value.scrollTo({ top: Math.max(0, element.offsetTop - 16), behavior: 'instant' })
}
function changeZoom(value: number) {
  zoom.value = Math.min(2, Math.max(.5, value))
  void nextTick(() => { scrollToCurrentPage(); updateWindow() })
}
watch(() => [props.knowledgeId, props.active], () => { void load() }, { immediate: true })
onMounted(() => {
  resizeObserver = new ResizeObserver(() => {
    if (resizeTimer) clearTimeout(resizeTimer)
    resizeTimer = setTimeout(() => {
      const width = scroll.value?.clientWidth || 0
      if (!width) return
      const next = Math.min(1000, Math.max(200, width - 32))
      if (next === fitWidth.value) return
      fitWidth.value = next
      void nextTick(updateWindow)
    }, 150)
  })
  if (scroll.value) resizeObserver.observe(scroll.value)
})
onBeforeUnmount(() => { dispose(); resizeObserver?.disconnect(); if (resizeTimer) clearTimeout(resizeTimer) })
</script>

<template>
  <div class="pdf-range-preview">
    <div class="pdf-controls" role="group" aria-label="PDF 翻页和缩放">
      <button type="button" :disabled="!pdf || pageNumber <= 1" @click="goToPage(pageNumber - 1)">上一页</button>
      <form @submit.prevent="goToPage(pageInput)"><label>第 <input v-model.number="pageInput" type="number" min="1" :max="pageCount || 1" :disabled="!pdf" aria-label="页码" /> / {{ pageCount || '—' }} 页</label></form>
      <button type="button" :disabled="!pdf || pageNumber >= pageCount" @click="goToPage(pageNumber + 1)">下一页</button>
      <button type="button" :disabled="!pdf || zoom <= .5" aria-label="缩小" @click="changeZoom(zoom - .25)">−</button>
      <span>{{ Math.round(zoom * 100) }}%</span>
      <button type="button" :disabled="!pdf || zoom >= 2" aria-label="放大" @click="changeZoom(zoom + .25)">+</button>
      <button type="button" :disabled="!pdf" @click="changeZoom(1)">适合宽度</button>
    </div>
    <p v-if="busy" class="pdf-message" role="status">正在优先加载首页… <span v-if="receivedKB">已读取 {{ receivedKB }} KB</span></p>
    <div v-if="error" class="pdf-message" role="alert"><p>{{ error }}</p><button type="button" @click="load()">重试</button></div>
    <div ref="scroll" class="pdf-scroll" tabindex="0" :aria-label="fileName + ' PDF 连续阅读'" @scroll.passive="onScroll">
      <div v-for="page in pageCount" :key="page" :ref="value => pageElement(page, value)" :data-page="page"
        class="pdf-page-slot" :style="{ width: fitWidth * zoom + 'px', height: (ratios[page] || firstRatio) * fitWidth * zoom + 'px' }">
        <template v-if="pdf && wanted.has(page)">
          <PdfScrollPage :key="page + ':' + fitWidth + ':' + zoom + ':' + (retries[page] || 0)"
            :pdf="pdf" :page="page" :width="fitWidth" :zoom="zoom" :enqueue="enqueue" :priority="page === pageNumber ? 0 : 1"
            @size="height => ratios[page] = height / (fitWidth * zoom)" @ready="pageReady(page)" @failure="message => pageFailure(page, message)" />
          <button v-if="failures[page]" class="page-retry" type="button" @click="retries[page] = (retries[page] || 0) + 1; delete failures[page]">重试此页</button>
        </template>
        <p v-else class="page-placeholder">第 {{ page }} 页 · 滚动到此处加载</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pdf-range-preview { display: flex; flex-direction: column; height: 100%; min-height: 400px; min-width: 0; }
.pdf-controls { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 8px; padding: 8px; border-bottom: 1px solid var(--td-component-border); }
.pdf-controls form { margin: 0; } .pdf-controls input { width: 52px; }
button, input { min-height: 32px; padding: 4px 8px; border: 1px solid var(--td-component-border); border-radius: 4px; font: inherit; font-size: 13px; background: var(--td-bg-color-container); color: var(--td-text-color-primary); box-sizing: border-box; }
button { cursor: pointer; } button:hover:not(:disabled) { border-color: var(--td-brand-color); } button:disabled { cursor: not-allowed; opacity: .5; }
button:focus-visible, input:focus-visible, .pdf-scroll:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: -2px; }
.pdf-message { padding: 12px; text-align: center; margin: 0; color: var(--td-text-color-secondary); } .pdf-message span { margin-left: 8px; }
.pdf-scroll { position: relative; flex: 1; min-height: 0; overflow: auto; padding: 16px; background: var(--td-bg-color-secondarycontainer); }
.pdf-page-slot { position: relative; margin: 0 auto 16px; background: white; overflow-anchor: auto; }
.page-placeholder { margin: 0; padding: 24px; text-align: center; color: var(--td-text-color-secondary); }
.page-retry { position: absolute; top: 56px; left: 16px; }
</style>
