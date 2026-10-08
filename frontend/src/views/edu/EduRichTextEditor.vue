<script setup lang="ts">
import { onMounted, ref, useId, watch } from 'vue'
import { renderEduContent, sanitizeEduEditorHTML } from '@/utils/eduContent'
import { escapeHTML } from '@/utils/security'

const props = withDefaults(defineProps<{ modelValue: string; disabled?: boolean; maxlength?: number }>(), {
  disabled: false, maxlength: 300000,
})
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const editor = ref<HTMLDivElement | null>(null)
const hintId = useId()
const error = ref('')
const color = ref('#000000')
const active = ref<Record<string, boolean>>({})
let selection: Range | null = null
let emitted: string | undefined
let lastValidHTML = ''
let composing = false
const tools = [
  { command: 'bold', label: '加粗', text: 'B' },
  { command: 'italic', label: '倾斜', text: 'I' },
  { command: 'underline', label: '下划线', text: 'U' },
  { command: 'strikeThrough', label: '删除线', text: 'S' },
  { command: 'insertUnorderedList', label: '无序列表', text: '• 列表' },
  { command: 'insertOrderedList', label: '有序列表', text: '1. 列表' },
  { command: 'removeFormat', label: '清除格式', text: '清除格式' },
  { command: 'undo', label: '撤销', text: '撤销' },
  { command: 'redo', label: '重做', text: '重做' },
]

function rememberSelection() {
  const current = window.getSelection()
  if (current?.rangeCount && editor.value?.contains(current.getRangeAt(0).commonAncestorContainer)) {
    selection = current.getRangeAt(0).cloneRange()
    active.value = Object.fromEntries(tools.slice(0, 6).map(tool => [tool.command, document.queryCommandState(tool.command)]))
  }
}

function restoreSelection() {
  const element = editor.value
  if (!element) return
  element.focus()
  const current = window.getSelection()
  const range = selection && element.contains(selection.commonAncestorContainer) ? selection : document.createRange()
  if (range !== selection) { range.selectNodeContents(element); range.collapse(false) }
  current?.removeAllRanges()
  current?.addRange(range)
}

function syncContent() {
  if (!editor.value || composing) return
  const html = sanitizeEduEditorHTML(editor.value.innerHTML)
  if (html.length > props.maxlength) {
    error.value = `正文过长，请缩短至 ${props.maxlength} 个字符以内。`
    editor.value.innerHTML = lastValidHTML
    selection = null
    return
  }
  error.value = ''
  lastValidHTML = html
  // An empty paragraph/BR should still fail the required-content validation.
  emitted = editor.value.textContent?.replace(/\u00a0/g, ' ').trim() || editor.value.querySelector('img,table') ? html : ''
  emit('update:modelValue', emitted)
  rememberSelection()
}

function format(command: string, value?: string) {
  if (props.disabled) return
  restoreSelection()
  document.execCommand('styleWithCSS', false, 'true')
  document.execCommand(command, false, value)
  syncContent()
}

function paste(event: ClipboardEvent) {
  event.preventDefault()
  if (props.disabled) return
  const html = event.clipboardData?.getData('text/html')
  const plain = event.clipboardData?.getData('text/plain') || ''
  const safe = html ? sanitizeEduEditorHTML(html) : escapeHTML(plain).replace(/\r?\n/g, '<br>')
  format('insertHTML', safe)
}

function loadContent() {
  if (!editor.value) return
  editor.value.innerHTML = renderEduContent(props.modelValue)
  lastValidHTML = editor.value.innerHTML
  selection = null
  active.value = {}
  error.value = ''
}
function startComposition() { composing = true }
function endComposition() { composing = false; syncContent() }
onMounted(loadContent)
watch(() => props.modelValue, value => { if (value !== emitted) loadContent() }, { flush: 'post' })
</script>

<template>
  <div class="edu-rich-editor" :class="{ disabled, invalid: error }">
    <div class="editor-toolbar" role="group" aria-label="正文格式">
      <button v-for="tool in tools" :key="tool.command" type="button" :disabled="disabled"
        :title="tool.label" :aria-label="tool.label" :aria-pressed="active[tool.command] ?? undefined"
        :class="['format-button', tool.command, { active: active[tool.command] }]"
        @mousedown.prevent @click="format(tool.command)">{{ tool.text }}</button>
      <label class="color-tool">文字颜色
        <select v-model="color" :disabled="disabled" aria-label="文字颜色" @change="format('foreColor', color)">
          <option value="#000000">默认</option><option value="#ff0000">红色</option>
          <option value="#b45309">橙色</option><option value="#a16207">黄色</option>
          <option value="#008000">绿色</option><option value="#2563eb">蓝色</option>
          <option value="#9333ea">紫色</option>
        </select>
      </label>
    </div>
    <div ref="editor" class="editor-body" :contenteditable="!disabled" role="textbox" aria-label="正文"
      aria-multiline="true" :aria-disabled="disabled" :aria-invalid="!!error" :aria-describedby="hintId"
      data-placeholder="在这里输入正文，或粘贴已有内容…" @input="syncContent" @paste="paste" @drop.prevent
      @mouseup="rememberSelection" @keyup="rememberSelection" @blur="rememberSelection"
      @compositionstart="startComposition" @compositionend="endComposition" />
    <p :id="hintId" class="editor-hint" :role="error ? 'alert' : undefined">
      {{ error || '选中文字后设置格式；支持直接粘贴富文本，复制与保存会保留正文排版。' }}
    </p>
  </div>
</template>

<style scoped>
.edu-rich-editor { width: 100%; min-width: 0; border: 1px solid var(--td-component-border); border-radius: 8px; overflow: hidden; }
.edu-rich-editor:focus-within { border-color: var(--td-brand-color); }
.editor-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 8px; background: var(--td-bg-color-secondarycontainer); border-bottom: 1px solid var(--td-component-border); }
.format-button, .color-tool select { min-height: 32px; padding: 4px 8px; border: 1px solid var(--td-component-border); border-radius: 4px; background: var(--td-bg-color-container); color: var(--td-text-color-primary); font: inherit; font-size: 13px; cursor: pointer; }
.format-button:hover:not(:disabled), .format-button.active { background: var(--td-brand-color-light); border-color: var(--td-brand-color); }
.format-button:active:not(:disabled) { opacity: .8; }
.format-button:focus-visible, .color-tool select:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: 2px; }
.format-button:disabled, .color-tool select:disabled { cursor: not-allowed; opacity: .5; }
.bold { font-weight: 700; } .italic { font-style: italic; } .underline { text-decoration: underline; } .strikeThrough { text-decoration: line-through; }
.color-tool { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.editor-body { min-height: 200px; max-height: 420px; overflow: auto; padding: 12px; font-size: 16px; line-height: 1.7; overflow-wrap: anywhere; color: var(--td-text-color-primary); background: var(--td-bg-color-container); }
.editor-body:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: -2px; }
.editor-body:empty::before { content: attr(data-placeholder); color: var(--td-text-color-placeholder); pointer-events: none; }
.editor-body :deep(p) { margin: 0 0 8px; } .editor-body :deep(img) { max-width: 100%; }
.editor-body :deep(table), .editor-body :deep(pre) { max-width: 100%; overflow: auto; }
.editor-hint { margin: 0; padding: 8px 12px; font-size: 12px; line-height: 1.5; color: var(--td-text-color-secondary); border-top: 1px solid var(--td-component-border); }
.invalid { border-color: var(--td-error-color); } .invalid .editor-hint { color: var(--td-error-color); }
.disabled .editor-body { opacity: .6; }
</style>
