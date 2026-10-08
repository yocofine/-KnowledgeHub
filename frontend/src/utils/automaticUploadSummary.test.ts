import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { withAutomaticUploadSummary } from './automaticUploadSummary'
import ts from 'typescript'
import { runInNewContext } from 'node:vm'

test('uploads always enable automatic summary including old disabled templates', () => {
  assert.equal(withAutomaticUploadSummary().summary_enabled, true)
  assert.equal(withAutomaticUploadSummary({ summary_enabled: false }).summary_enabled, true)
  assert.equal(withAutomaticUploadSummary('{"summary_enabled":false}').summary_enabled, true)
})
test('parser, chunking and other settings remain unchanged', () => {
  const original = { summary_enabled: false, parser_engine_rules: [{ file_types: ['pdf'], engine: 'mineru_cloud' }], chunking_config: { chunk_size: 512 } }
  const result = withAutomaticUploadSummary(original)
  assert.deepEqual(result.parser_engine_rules, original.parser_engine_rules)
  assert.deepEqual(result.chunking_config, original.chunking_config)
  assert.equal(original.summary_enabled, false)
})
test('invalid saved JSON fails explicitly rather than silently replacing processing settings', () => {
  assert.throws(() => withAutomaticUploadSummary('bad json'))
  assert.throws(() => withAutomaticUploadSummary('null'))
  assert.throws(() => withAutomaticUploadSummary('[]'))
})
test('all upload entry points apply the policy and the dialog cannot restore an off state', () => {
  const api = readFileSync(new URL('../api/knowledge-base/index.ts', import.meta.url), 'utf8')
  const dialog = readFileSync(new URL('../views/knowledge/components/UploadConfirmDialog.vue', import.meta.url), 'utf8')
  assert.match(api, /process_config: withAutomaticUploadSummary\(data.process_config\)/)
  assert.match(api, /Object.keys\(uploadData\)/)
  assert.match(dialog, /summary_enabled: true/)
  assert.match(dialog, /<t-switch :model-value="true" disabled/)
  assert.doesNotMatch(dialog, /s.summaryEnabled = o.summary_enabled/)
})
test('actual upload API includes automatic summary while preserving file, tags and folder', async () => {
  const source = readFileSync(new URL('../api/knowledge-base/index.ts', import.meta.url), 'utf8')
  const ast = ts.createSourceFile('Api.ts', source, ts.ScriptTarget.Latest, true)
  const upload = ast.statements.find(statement => ts.isFunctionDeclaration(statement) && statement.name?.text === 'uploadKnowledgeFile')!
  const compiled = ts.transpileModule(upload.getText(ast).replace('export function', 'function'), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  let captured: { url: string; body: FormData } | undefined
  const uploadFile = runInNewContext(compiled + '\nuploadKnowledgeFile', {
    FormData, File, withAutomaticUploadSummary,
    postUpload: async (url: string, body: FormData) => { captured = { url, body }; return { success: true } },
  }) as (...args: unknown[]) => Promise<unknown>
  await uploadFile('kb-id', { file: new File(['verification text'], 'test.txt'), fileName: 'test.txt',
    tag_ids: ['tag-one', 'tag-two'], folder_path: 'training', process_config: '{"summary_enabled":false,"chunking_config":{"chunk_size":512}}' })
  assert.equal(captured!.url, '/api/v1/knowledge-bases/kb-id/knowledge/file')
  const config = JSON.parse(String(captured!.body.get('process_config')))
  assert.equal(config.summary_enabled, true)
  assert.equal(config.chunking_config.chunk_size, 512)
  assert.equal(captured!.body.get('folder_path'), 'training')
  assert.equal(captured!.body.get('tag_ids'), 'tag-one,tag-two')
  assert.equal(captured!.body.get('fileName'), 'test.txt')
  assert.equal(await (captured!.body.get('file') as File).text(), 'verification text')
})
