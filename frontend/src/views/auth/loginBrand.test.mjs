import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { parse, compileTemplate } from '@vue/compiler-sfc'

const source = readFileSync(new URL('./Login.vue', import.meta.url), 'utf8')
const index = readFileSync(new URL('../../../index.html', import.meta.url), 'utf8')
const css = readFileSync(new URL('./login.css', import.meta.url), 'utf8')

test('login template compiles without missing or mismatched tags', () => {
  const result = parse(source)
  assert.deepEqual(result.errors, [])
  assert.deepEqual(compileTemplate({ source: result.descriptor.template.content, filename: 'Login.vue', id: 'kh-login' }).errors, [])
})
test('login branding and chrome contain no vendor promotion', () => {
  const template = parse(source).descriptor.template.content
  assert.match(template, /智导/)
  assert.match(template, /KnowledgeHub/)
  assert.doesNotMatch(template, /weknora|github|header-links|swiper|platform\.|auth.firstTime/i)
  assert.match(index, /<title>智导 KnowledgeHub<\/title>/)
  assert.match(index, /href="\/knowledgehub.svg"/)
})
test('existing login, invitation, OIDC and registration contracts are retained', () => {
  assert.match(source, /@submit="handleLogin"/)
  assert.match(source, /autocomplete="current-password"/)
  assert.match(source, /v-if="oidcEnabled"/)
  assert.match(source, /registrationEnabled \|\| inviteLookup/)
  assert.match(source, /await persistLoginResponse\(response\)/)
  assert.match(source, /await registerByInvite/)
  assert.match(source, /await authStore.refreshFromAuthMe\(\)/)
})
test('login is mobile first and keeps readable focus and reduced motion', () => {
  assert.match(css, /grid-template-columns: minmax\(0,1fr\)/)
  assert.match(css, /@media \(min-width: 60rem\)/)
  assert.match(css, /:focus-visible/)
  assert.match(css, /min-height: 48px/)
  assert.match(css, /prefers-reduced-motion: reduce/)
})
