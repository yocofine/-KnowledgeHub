import { get, post, put, del } from '@/utils/request'

export interface EduItem {
  id: string
  title: string
  content: string
  group_name: string
  group_id?: string | null
  tags?: string
  updated_at: string
  state?: string
  error?: string
  push_status?: string
}
export interface EduContent { title: string; content: string; group_name: string; group_id?: string | null; tags?: string }
export interface EduScriptGroup { id: string; name: string; count: number }
export interface RobotSettings { enabled: boolean; webhook_configured: boolean; secret_configured: boolean }
export type EduKind = 'scripts' | 'rules'
export interface CreatedMemberAccount {
  created: boolean
  user: { id: string; username: string; email: string }
  generated_password?: string
  membership: { tenant_id: number; role: string }
}
export const createMemberAccount = (tenantId: number, body: { username: string; email: string; password?: string }) =>
  post<CreatedMemberAccount>(`/api/v1/edu/tenants/${tenantId}/members/create`, body)
interface Result<T> { success: boolean; data: T }

export const listScriptGroups = () => get<Result<EduScriptGroup[]>>('/api/v1/edu/script-groups')
export const createScriptGroup = (name: string) => post<Result<EduScriptGroup>>('/api/v1/edu/script-groups', { name })
export const renameScriptGroup = (id: string, name: string) => put<Result<EduScriptGroup>>(`/api/v1/edu/script-groups/${encodeURIComponent(id)}`, { name })
export const deleteScriptGroup = (id: string) => del(`/api/v1/edu/script-groups/${encodeURIComponent(id)}`)
const groupPath = (kind: EduKind) => `/api/v1/edu/${kind === 'scripts' ? 'script-groups' : 'rule-groups'}`
export const listEduGroups = (kind: EduKind) => get<Result<EduScriptGroup[]>>(groupPath(kind))
export const createEduGroup = (kind: EduKind, name: string) => post<Result<EduScriptGroup>>(groupPath(kind), { name })
export const renameEduGroup = (kind: EduKind, id: string, name: string) => put<Result<EduScriptGroup>>(`${groupPath(kind)}/${encodeURIComponent(id)}`, { name })
export const deleteEduGroup = (kind: EduKind, id: string) => del(`${groupPath(kind)}/${encodeURIComponent(id)}`)

export const eduMe = () => get<Result<{ user_id: string; can_manage_rules: boolean; faq_kb_id?: string; rules_kb_id?: string }>>('/api/v1/edu/me')
export const listEdu = (kind: EduKind, query = '') => get<Result<EduItem[]>>(`/api/v1/edu/${kind}?q=${encodeURIComponent(query)}`)
export const createEdu = (kind: EduKind, content: EduContent) => post(`/api/v1/edu/${kind}`, content)
export const updateEdu = (kind: EduKind, id: string, content: EduContent) => put(`/api/v1/edu/${kind}/${encodeURIComponent(id)}`, content)
export const deleteEdu = (kind: EduKind, id: string) => del(`/api/v1/edu/${kind}/${encodeURIComponent(id)}`)
export const pushEduRule = (id: string) => post(`/api/v1/edu/rules/${encodeURIComponent(id)}/push`)
export const getEduRobot = () => get<Result<RobotSettings>>('/api/v1/edu/dingtalk')
export const saveEduRobot = (settings: { enabled: boolean; webhook?: string; secret?: string }) => put('/api/v1/edu/dingtalk', settings)
export const getEduQuestions = () => get<Result<Array<{ question: string; count: number }>>>('/api/v1/edu/questions')
export const recordEduQuestion = (question: string) => post('/api/v1/edu/questions', {
  question: question.slice(0, 500), source_id: crypto.randomUUID(),
})
