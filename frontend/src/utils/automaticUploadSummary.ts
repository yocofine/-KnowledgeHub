import type { KnowledgeProcessOverrides } from '@/types/knowledgeProcess'

/** Every new knowledge-file upload asks the durable post-processing queue for a summary. */
export function withAutomaticUploadSummary(overrides?: KnowledgeProcessOverrides | string): KnowledgeProcessOverrides {
  const parsed = typeof overrides === 'string' ? JSON.parse(overrides) : overrides ?? {}
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('文件处理配置无效，请重新选择上传设置。')
  }
  return { ...parsed, summary_enabled: true }
}
