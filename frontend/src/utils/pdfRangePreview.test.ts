import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'
import { knowledgePdfRangeOptions } from './pdfRangePreview'

test('PDF uses authenticated ranges without background whole-file fetching', () => {
  const options = knowledgePdfRangeOptions('file/id', '/app/', 'test-token', '10001')
  assert.equal(options.url, '/app/api/v1/knowledge/file%2Fid/preview')
  assert.equal(options.httpHeaders.Authorization, 'Bearer test-token')
  assert.equal(options.httpHeaders['X-Tenant-ID'], '10001')
  assert.equal(options.rangeChunkSize, 65536)
  assert.equal(options.disableStream, true)
  assert.equal(options.disableAutoFetch, true)
  assert.equal(options.disableRange, false)
  assert.equal(options.isEvalSupported, false)
  assert.doesNotMatch(options.url, /test-token/)
})
test('anonymous previews are not enabled and tenant scope is never invented', () => {
  assert.throws(() => knowledgePdfRangeOptions('file', '', '', '10001'))
  assert.throws(() => knowledgePdfRangeOptions('', '', 'token', '10001'))
  assert.equal('X-Tenant-ID' in knowledgePdfRangeOptions('file', '', 'token', '').httpHeaders, false)
})
test('knowledge PDFs bypass full-blob downloading before the request starts', () => {
  const source = readFileSync(new URL('../components/document-preview.vue', import.meta.url), 'utf8')
  const start = source.indexOf('async function loadPreview()')
  const load = source.slice(start, source.indexOf('\nfunction cleanup()', start))
  assert.ok(load.indexOf('rangePdf.value = true') < load.indexOf('await fetchPreviewBlob()'))
  assert.match(load, /knowledgeId && !props.sourceBlob/)
  assert.match(source, /<PdfRangePreview :knowledge-id="knowledgeId" :active="active"/)
})
test('range renderer has page-one loading, text selection and lifecycle cleanup', () => {
  const source = readFileSync(new URL('../components/PdfRangePreview.vue', import.meta.url), 'utf8')
  const { descriptor, errors } = parse(source)
  assert.deepEqual(errors, [])
  const script = compileScript(descriptor, { id: 'pdf-test' })
  assert.deepEqual(compileTemplate({ source: descriptor.template!.content, filename: 'PdfRangePreview.vue', id: 'pdf-test', compilerOptions: { bindingMetadata: script.bindings } }).errors, [])
  assert.match(source, /pageNumber.value = pageInput.value = 1/)
  const page = readFileSync(new URL('../components/PdfScrollPage.vue', import.meta.url), 'utf8')
  assert.match(page, /new TextLayer/)
  assert.match(source, /loadingTask\?\.destroy\(\)/)
  assert.match(page, /render\?\.cancel\(\)/)
  assert.match(source, /onBeforeUnmount/)
  assert.match(source, /scope !== generation/)
  assert.match(source, /refreshAccessTokenShared/)
})
