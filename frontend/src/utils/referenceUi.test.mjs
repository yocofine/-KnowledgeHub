import assert from 'node:assert/strict'
import { readFileSync, statSync } from 'node:fs'
import test from 'node:test'
import { parse, compileTemplate } from '@vue/compiler-sfc'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const css = read('../assets/theme/reference-ui.css')
test('reference pages retain valid Vue templates and real navigation', () => {
  for (const path of ['../views/creatChat/creatChat.vue', '../components/menu.vue', '../views/edu/EduLibrary.vue']) {
    const { descriptor, errors } = parse(read(path))
    assert.deepEqual(errors, [])
    assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename: path, id: 'reference-ui' }).errors, [])
  }
  const home = read('../views/creatChat/creatChat.vue')
  for (const route of ['knowledge-bases', 'edu-scripts', 'edu-rules']) assert.ok(home.includes(`to="/platform/${route}"`))
})
test('responsive root overrides legacy 600px minimum and grids can shrink', () => {
  assert.match(css, /#app \.main \{ min-width: 0; width: 100%; \}/)
  assert.match(css, /html, body \{ overflow-x: clip; \}/)
  assert.match(css, /repeat\(3,minmax\(0,1fr\)\)/)
  assert.match(css, /max-width: 640px/)
  assert.doesNotMatch(css, /font-size:\s*clamp/)
})
test('brand imagery uses small WebP assets with stable dimensions', () => {
  for (const path of ['../views/auth/Login.vue', '../views/creatChat/creatChat.vue', '../components/menu.vue']) {
    assert.match(read(path), /classbro-mark\.webp/)
  }
  assert.match(read('../views/auth/login.css'), /study-room\.webp/)
  for (const asset of ['classbro-mark.webp', 'study-room.webp']) {
    assert.ok(statSync(new URL(`../../public/brand/${asset}`, import.meta.url)).size < 150000)
  }
})
test('shared wiki stylesheet uses per-component imports without Vite src collisions', () => {
  for (const path of ['../views/chat/components/AgentStreamDisplay.vue', '../views/knowledge/wiki/WikiBrowser.vue']) {
    const source = read(path)
    assert.doesNotMatch(source, /<style[^>]*src="@\/components\/css\/wiki-graph-drawer.less"/)
    assert.match(source, /@import '@\/components\/css\/wiki-graph-drawer.less'/)
  }
})
