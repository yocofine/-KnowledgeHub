export function knowledgePdfRangeOptions(id: string, base: string, token: string, tenantId: string) {
  if (!id || !token) throw new Error('请重新登录后打开文件预览。')
  return {
    url: `${base.replace(/\/+$/, '')}/api/v1/knowledge/${encodeURIComponent(id)}/preview`,
    httpHeaders: { Authorization: `Bearer ${token}`, ...(tenantId ? { 'X-Tenant-ID': tenantId } : {}) },
    rangeChunkSize: 65536,
    disableRange: false,
    disableStream: true,
    disableAutoFetch: true,
    isEvalSupported: false,
  }
}
