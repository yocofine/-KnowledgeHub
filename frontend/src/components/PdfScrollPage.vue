<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { TextLayer, type PDFDocumentProxy, type PDFPageProxy, type RenderTask } from 'pdfjs-dist'

const props = defineProps<{ pdf: PDFDocumentProxy; page: number; width: number; zoom: number; priority: number; enqueue: <T>(job: () => Promise<T>, priority?: number) => Promise<T> }>()
const emit = defineEmits<{ size: [height: number]; ready: []; failure: [message: string] }>()
const canvas = ref<HTMLCanvasElement | null>(null)
const text = ref<HTMLDivElement | null>(null)
const ready = ref(false)
const error = ref('')
const height = ref(0)
const scale = ref(1)
let disposed = false
let render: RenderTask | undefined
let layer: TextLayer | undefined
let pdfPage: PDFPageProxy | undefined
let timer: ReturnType<typeof setTimeout> | undefined

onMounted(() => {
  void props.enqueue(async () => {
    if (disposed) return
    try {
      timer = setTimeout(() => {
        if (disposed) return
        error.value = '此页读取暂时没有响应，请重试。'
        emit('failure', error.value)
      }, 90000)
      const page = await props.pdf.getPage(props.page)
      pdfPage = page
      if (disposed) { page.cleanup(); return }
      const original = page.getViewport({ scale: 1 })
      const viewport = page.getViewport({ scale: props.width / original.width * props.zoom })
      height.value = viewport.height
      scale.value = viewport.scale * page.userUnit
      emit('size', viewport.height)
      await nextTick()
      if (disposed || !canvas.value || !text.value) return
      const ratio = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(4_000_000 / (viewport.width * viewport.height)))
      canvas.value.width = Math.ceil(viewport.width * ratio)
      canvas.value.height = Math.ceil(viewport.height * ratio)
      render = page.render({ canvas: canvas.value, viewport, transform: [ratio, 0, 0, ratio, 0, 0] })
      await render.promise
      if (disposed) return
      ready.value = true
      error.value = ''
      emit('ready')
      if (timer) clearTimeout(timer)
      const content = await page.getTextContent()
      if (disposed || !text.value) return
      layer = new TextLayer({ textContentSource: content, container: text.value, viewport })
      await layer.render()
    } catch (reason: any) {
      if (!disposed && reason?.name !== 'RenderingCancelledException') {
        error.value = reason?.message || '此页加载失败，请重试。'
        emit('failure', error.value)
      }
    } finally {
      if (timer) clearTimeout(timer)
      if (disposed) pdfPage?.cleanup()
    }
  }, props.priority)
})
onBeforeUnmount(() => {
  disposed = true
  if (timer) clearTimeout(timer)
  render?.cancel()
  layer?.cancel()
  if (canvas.value) { canvas.value.width = 0; canvas.value.height = 0 }
  pdfPage?.cleanup()
})
</script>

<template>
  <div class="scroll-pdf-paper" :style="{ height: `${height}px`, '--total-scale-factor': scale }">
    <p v-if="!ready" class="page-message" :role="error ? 'alert' : 'status'">{{ error || `正在加载第 ${page} 页…` }}</p>
    <canvas ref="canvas" :style="{ visibility: ready ? 'visible' : 'hidden' }" :aria-label="`第 ${page} 页`" />
    <div ref="text" class="textLayer" />
  </div>
</template>

<style scoped>
.scroll-pdf-paper { --scale-round-x: 1px; --scale-round-y: 1px; position: relative; width: 100%; min-height: 80px; background: white; }
canvas { display: block; width: 100%; height: 100%; }
.page-message { position: absolute; inset: 20px 0 auto; margin: 0; text-align: center; color: var(--td-text-color-secondary); }
</style>
