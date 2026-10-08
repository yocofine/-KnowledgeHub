<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { renderEduContent } from '@/utils/eduContent'

const props = defineProps<{ content: string; compact?: boolean }>()
const html = computed(() => renderEduContent(props.content))
const contentId = useId()
const body = ref<HTMLElement | null>(null)
const expanded = ref(false)
const overflowing = ref(false)
const previewHeight = computed(() => props.compact ? 84 : 128)
let observer: ResizeObserver | undefined

function measure() {
  overflowing.value = (body.value?.scrollHeight || 0) > previewHeight.value + 1
}

watch(() => props.content, async () => {
  expanded.value = false
  await nextTick()
  measure()
})

onMounted(() => {
  observer = new ResizeObserver(measure)
  if (body.value) observer.observe(body.value)
  measure()
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <div class="card-content">
    <div :id="contentId" class="content-window" :class="{ expanded }"
      :style="{ '--preview-height': `${previewHeight}px` }">
      <div ref="body" class="content-body" v-html="html" />
    </div>
    <button v-if="overflowing" type="button" class="content-toggle"
      :aria-expanded="expanded" :aria-controls="contentId" @click="expanded = !expanded">
      {{ expanded ? '收起全文' : '展开全文' }}
    </button>
  </div>
</template>

<style scoped>
.content-window { max-height: var(--preview-height); overflow: hidden; }
.content-window.expanded { max-height: none; }
.content-body { display: flow-root; font-size: 14px; line-height: 1.6; overflow-wrap: anywhere; }
.content-body :deep(p) { margin: 0 0 8px; }
.content-body :deep(ul), .content-body :deep(ol) { padding-left: 20px; margin: 8px 0; }
.content-body :deep(img) { max-width: 100%; height: auto; }
.content-body :deep(pre), .content-body :deep(table) { max-width: 100%; overflow: auto; }
.content-body :deep(table) { display: block; }
.content-toggle { margin-top: 8px; padding: 4px 0; border: 0; background: transparent; color: var(--td-brand-color); font: inherit; font-size: 13px; cursor: pointer; }
.content-toggle:hover { text-decoration: underline; }
.content-toggle:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: 3px; border-radius: 2px; }
</style>
