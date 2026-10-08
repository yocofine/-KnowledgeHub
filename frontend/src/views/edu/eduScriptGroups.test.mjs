import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const library = readFileSync(new URL('./EduLibrary.vue', import.meta.url), 'utf8')
const api = readFileSync(new URL('../../api/edu.ts', import.meta.url), 'utf8')
const theme = readFileSync(new URL('../../assets/theme/reference-ui.css', import.meta.url), 'utf8')
const content = readFileSync(new URL('./EduCardContent.vue', import.meta.url), 'utf8')
const tokens = readFileSync(new URL('../../../../tokens.css', import.meta.url), 'utf8')

test('new group action precedes the existing new script action', () => {
  assert.ok(library.indexOf('新建{{ groupLabel }}</t-button>') < library.indexOf("{{ kind === 'scripts' ? '新建话术'"))
  assert.match(library, /<aside class="edu-groups"/)
  assert.match(library, /grid-template-columns: 216px minmax\(0,1fr\)/)
  assert.match(library, /@media \(max-width: 64rem\)/)
})
test('groups filter by stable ID and resets on account change', () => {
  assert.match(library, /item\.group_id === selectedGroup\.value/)
  assert.match(library, /groups\.value = \[\]/)
  assert.match(library, /groupEditor\.value = false/)
  assert.match(library, /owner !== auth\.user\?\.id/)
  assert.match(library, /group_id: formGroupId\.value \|\| null/)
})
test('group rename and delete use private server endpoints, preserve contents', () => {
  assert.match(api, /\/api\/v1\/edu\/script-groups/)
  assert.match(api, /encodeURIComponent\(id\)/)
  assert.match(library, /重命名<\/t-dropdown-item>/)
  assert.match(library, /组内\$\{label\}会保留并移到“未分组”/)
  assert.match(library, /:aria-pressed="selectedGroup === group\.id"/)
  assert.match(library, /管理\$\{groupLabel\}：/)
})
test('compact styles override old global rules for both grouped pages', () => {
  const override = theme.slice(theme.indexOf('/* Grouped edu workbench'))
  assert.match(override, /#app \.platform-route-outlet \.edu-page--grouped \.edu-grid/)
  assert.match(override, /minmax\(min\(280px,100%\),1fr\)/)
  assert.match(override, /min-height: 0; padding: var\(--kh-space-md\)/)
  assert.match(override, /font-size: var\(--kh-text-sm\); line-height: 1\.6/)
  assert.match(tokens, /--kh-text-sm: 14px/)
  assert.match(content, /props\.compact \? 84 : 128/)
})
test('rules group management retains the existing administrator gate', () => {
  assert.match(library, /<t-dropdown v-if="canEdit"/)
  assert.match(library, /v-if="!analysis && canEdit" variant="outline" @click="editGroup/)
  assert.match(api, /'script-groups' : 'rule-groups'/)
})
