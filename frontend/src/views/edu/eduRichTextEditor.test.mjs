import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'

const source = readFileSync(new URL('./EduRichTextEditor.vue', import.meta.url), 'utf8')
const library = readFileSync(new URL('./EduLibrary.vue', import.meta.url), 'utf8')
const utility = readFileSync(new URL('../../utils/eduContent.ts', import.meta.url), 'utf8')

test('rich editor template and script compile', () => {
  const { descriptor, errors } = parse(source)
  assert.deepEqual(errors, [])
  const script = compileScript(descriptor, { id: 'editor-test' })
  const template = compileTemplate({ source: descriptor.template.content, filename: 'EduRichTextEditor.vue', id: 'editor-test', compilerOptions: { bindingMetadata: script.bindings } })
  assert.deepEqual(template.errors, [])
})
test('both libraries edit rendered rich content instead of HTML in a textarea', () => {
  assert.match(library, /<EduRichTextEditor[^>]*v-model="form.content"/)
  assert.doesNotMatch(library, /<t-textarea v-model="form.content"/)
  assert.match(source, /editor.value.innerHTML = renderEduContent\(props.modelValue\)/)
  assert.match(source, /bold/)
  assert.match(source, /italic/)
  assert.match(source, /foreColor/)
  assert.match(source, /insertOrderedList/)
})
test('pasted and emitted HTML are sanitized without reparsing typed Markdown', () => {
  assert.match(source, /@paste="paste"/)
  assert.match(source, /sanitizeEduEditorHTML\(editor.value.innerHTML\)/)
  assert.match(source, /sanitizeEduEditorHTML\(html\)/)
  assert.match(source, /escapeHTML\(plain\)/)
  assert.match(utility, /return sanitizeHTML\(normalizeEduHTML\(content\)\)/)
  assert.match(utility, /sanitizeHTML\(marked.parse/)
})
test('editor preserves selection, IME input, empty and oversized validation', () => {
  assert.match(source, /cloneRange\(\)/)
  assert.match(source, /@mousedown.prevent/)
  assert.match(source, /aria-multiline="true"/)
  assert.match(source, /@compositionend/)
  assert.match(source, /html.length > props.maxlength/)
  assert.match(source, /emit\('update:modelValue', emitted\)/)
})
