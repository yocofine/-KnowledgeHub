import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const library = readFileSync(new URL('./EduLibrary.vue', import.meta.url), 'utf8')
const content = readFileSync(new URL('./EduCardContent.vue', import.meta.url), 'utf8')
const faq = readFileSync(new URL('../knowledge/components/FAQEntryManager.vue', import.meta.url), 'utf8')

test('cards keep compact widths and align to the tallest card in each row', () => {
  assert.match(library, /repeat\(auto-fill,min\(340px,100%\)\)/)
  assert.match(library, /\.edu-grid \{[^}]*align-items: stretch/)
  assert.match(library, /grid-template-columns: minmax\(0,1fr\)/)
})
test('card metadata and actions stay together at the bottom', () => {
  assert.match(library, /\.edu-card \{[^}]*display: flex; flex-direction: column/)
  assert.match(library, /\.edu-card-bottom \{ margin-top: auto/)
  assert.match(library, /<div class="edu-card-bottom">\s*<p v-if="item.error"/)
  assert.match(library, /grid-template-columns: minmax\(0,1fr\) minmax\(0,88px\)/)
})
test('both libraries use the same compact rich content component', () => {
  assert.match(library, /<EduCardContent :content="item.content"/)
  assert.match(content, /renderEduContent\(props.content\)/)
  assert.match(content, /max-height: var\(--preview-height\)/)
  assert.match(content, /\.expanded \{ max-height: none/)
})
test('disclosure measures overflow, exposes keyboard operable state and cleans up', () => {
  assert.match(content, /scrollHeight/)
  assert.match(content, /new ResizeObserver\(measure\)/)
  assert.match(content, /onBeforeUnmount\(\(\) => observer\?\.disconnect\(\)\)/)
  assert.match(content, /<button v-if="overflowing" type="button"/)
  assert.match(content, /:aria-expanded="expanded" :aria-controls="contentId"/)
  assert.match(content, /watch\(\(\) => props.content/)
})
test('copy and edit retain complete content rather than the preview', () => {
  assert.match(library, /const html = renderEduContent\(item.content\)/)
  assert.match(library, /content: item.content/)
  assert.match(library, /items.value = \[\]/)
})
test('FAQ cards use equal-height rows and no longer apply masonry positions', () => {
  assert.match(faq, /\.faq-card-list \{\s*display: grid/)
  assert.match(faq, /align-items: stretch/)
  assert.match(faq, /margin: auto -10px -10px/)
  assert.doesNotMatch(faq, /arrangeCards|columnHeights|card\.style\.position/)
})
