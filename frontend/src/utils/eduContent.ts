import { safeMarkdownToHTML } from '@/utils/security'

/** Normalize legacy execCommand HTML before applying the native sanitizer. */
export function renderEduContent(content: string): string {
  const normalized = content.replace(/<(\/?)(b|i)\s*>/gi, (_tag, close, name) =>
    `<${close}${name.toLowerCase() === 'b' ? 'strong' : 'em'}>`)
    .replace(/<font\b[^>]*color\s*=\s*["']([^"']+)["'][^>]*>/gi, (_tag, color: string) => {
      const safeColor = /^(#[0-9a-f]{3,8}|rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)|red|yellow|green|blue|black|white|orange|purple)$/i.test(color.trim())
      return safeColor ? `<span style="color: ${color.trim()}">` : '<span>'
    }).replace(/<\/font\s*>/gi, '</span>')
  return safeMarkdownToHTML(normalized)
}
