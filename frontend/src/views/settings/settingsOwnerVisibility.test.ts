import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { OWNER_ONLY_SETTINGS_SECTIONS, SETTINGS_SECTION_MIN_ROLE, SYSTEM_ADMIN_SETTINGS_SECTIONS } from '../../config/settingsAccess'
import { INTEGRATION_TAB_MIN_ROLE } from '../../config/integrations'
import { isIntegrationSection, integrationTabFromSection, normalizeSettingsSection } from '../../config/settingsRoute'

const source = readFileSync(new URL('./Settings.vue', import.meta.url), 'utf8')
const script = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)![1]!
const ast = ts.createSourceFile('Settings.ts', script, ts.ScriptTarget.Latest, true)
const gate = ast.statements.find(statement => ts.isVariableStatement(statement)
  && statement.declarationList.declarations.some(declaration => ts.isIdentifier(declaration.name) && declaration.name.text === 'canSeeSection'))!
const compiled = ts.transpileModule(gate.getText(ast), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText

function access(role: string, superuser = false) {
  const levels: Record<string, number> = { viewer: 1, contributor: 2, admin: 3, owner: 4 }
  const authStore = { currentTenantRole: role, canAccessAllTenants: superuser, isSystemAdmin: superuser,
    hasRole: (minimum: string) => (levels[role] ?? 0) >= (levels[minimum] ?? 100) }
  const canSee = runInNewContext(`${compiled}\ncanSeeSection`, { authStore, OWNER_ONLY_SETTINGS_SECTIONS,
    isIntegrationSection, integrationTabFromSection, INTEGRATION_TAB_MIN_ROLE,
    SETTINGS_SECTION_MIN_ROLE, SYSTEM_ADMIN_SECTIONS: SYSTEM_ADMIN_SETTINGS_SECTIONS }) as (key: string) => boolean
  return { authStore, canSee }
}

test('only active workspace owners see the four requested settings panels', () => {
  for (const role of ['', 'viewer', 'contributor', 'admin', 'owner']) {
    for (const superuser of [false, true]) {
      for (const section of OWNER_ONLY_SETTINGS_SECTIONS) {
        assert.equal(access(role, superuser).canSee(section), role === 'owner', `${role}/${superuser}/${section}`)
      }
    }
  }
})
test('legacy links and role downgrades use the same gate', () => {
  const state = access('owner', true)
  assert.equal(state.canSee(normalizeSettingsSection('integrations', 'im')), true)
  state.authStore.currentTenantRole = 'admin'
  assert.equal(state.canSee(normalizeSettingsSection('im')), false)
  assert.equal(state.canSee(normalizeSettingsSection('embed')), false)
  assert.equal(state.canSee(normalizeSettingsSection('mcpserver')), false)
  assert.equal(state.canSee('system'), false)
})
test('personal settings and read-only workspace information remain available', () => {
  for (const section of ['general', 'userprofile', 'mymemory', 'envvars', 'tenant', 'members']) {
    assert.equal(access('viewer').canSee(section), true)
  }
  assert.match(source, /v-if="!canSeeSection\(currentSection\)"/)
  assert.match(source, /canSeeSection\(it.key\)/)
  assert.match(source, /filter\(\(group\) => group.items.length > 0\)/)
})
