import { cp, mkdir } from 'node:fs/promises'
const base = new URL('../', import.meta.url)
for (const directory of ['cmaps', 'standard_fonts', 'wasm', 'iccs']) {
  const target = new URL(`public/pdfjs/${directory}/`, base)
  await mkdir(target, { recursive: true })
  await cp(new URL(`node_modules/pdfjs-dist/${directory}/`, base), target, { recursive: true })
}
// Serve the module worker with a .js extension understood by existing Nginx MIME maps.
await cp(new URL('node_modules/pdfjs-dist/build/pdf.worker.min.mjs', base),
  new URL('public/pdfjs/pdf.worker.min.js', base))
