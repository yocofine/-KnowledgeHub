<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@/stores/auth'
import { useMenuStore } from '@/stores/menu'
import { renderEduContent } from '@/utils/eduContent'
import EduCardContent from './EduCardContent.vue'
import EduRichTextEditor from './EduRichTextEditor.vue'
import { eduMe, listEdu, createEdu, updateEdu, deleteEdu, pushEduRule, getEduRobot, saveEduRobot, getEduQuestions } from '@/api/edu'
import type { EduItem, EduKind } from '@/api/edu'
import { listEduGroups, createEduGroup, renameEduGroup, deleteEduGroup } from '@/api/edu'
import type { EduScriptGroup } from '@/api/edu'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const menu = useMenuStore()
const analysis = computed(() => route.name === 'eduAnalysis')
const kind = computed<EduKind>(() => route.name === 'eduRules' ? 'rules' : 'scripts')
const heading = computed(() => analysis.value ? 'AI 分析中心' : kind.value === 'scripts' ? '我的话术库' : '规则通知')
const items = ref<EduItem[]>([])
const groups = ref<EduScriptGroup[]>([])
const selectedGroup = ref('__all__')
const groupEditor = ref(false)
const groupSaving = ref(false)
const groupError = ref('')
const groupName = ref('')
const editingGroupId = ref<string | null>(null)
const groupEditorOwner = ref('')
const groupEditorKind = ref<EduKind>('scripts')
const formGroupId = ref('')
const groupLabel = computed(() => kind.value === 'scripts' ? '话术组' : '规则分组')
const itemLabel = computed(() => kind.value === 'scripts' ? '话术' : '规则')
const displayedItems = computed(() => selectedGroup.value === '__all__' ? items.value
  : items.value.filter(item => selectedGroup.value === '__ungrouped__' ? !item.group_id : item.group_id === selectedGroup.value))
const selectedGroupName = computed(() => selectedGroup.value === '__all__' ? `全部${itemLabel.value}`
  : selectedGroup.value === '__ungrouped__' ? '未分组' : groups.value.find(group => group.id === selectedGroup.value)?.name || `全部${itemLabel.value}`)
const questions = ref<Array<{ question: string; count: number }>>([])
const query = ref('')
const loading = ref(false)
const error = ref('')
const canManage = ref(false)
const editor = ref(false)
const saving = ref(false)
const editingId = ref<string | null>(null)
const editorOwner = ref('')
const formRef = ref<any>(null)
const form = ref({ title: '', content: '', group_name: '默认分组', tags: '' })
const robotVisible = ref(false)
const robotSaving = ref(false)
const robot = ref({ enabled: false, webhook: '', secret: '', webhook_configured: false, secret_configured: false })
const busy = ref<Record<string, boolean>>({})
let generation = 0
const canEdit = computed(() => kind.value === 'scripts' || canManage.value)
const formRules = {
  title: [{ required: true, message: '请填写标题', trigger: 'blur' }],
  content: [{ required: true, message: '请填写正文', trigger: 'blur' }],
  group_name: [{ required: true, message: '请填写分组', trigger: 'blur' }],
}
const message = (reason: any) => (typeof reason?.detail === 'string' ? reason.detail : reason?.message) || '操作失败，请稍后重试'

async function load() {
  const scope = ++generation
  const owner = auth.user?.id
  loading.value = true
  error.value = ''
  try {
    const me = await eduMe()
    if (scope !== generation || owner !== auth.user?.id) return
    canManage.value = me.data.can_manage_rules
    if (route.query.robot === '1' && canManage.value && kind.value === 'rules') await openRobot()
    if (analysis.value) {
      const result = await getEduQuestions()
      if (scope === generation && owner === auth.user?.id) questions.value = result.data
    } else {
      const [result, groupResult] = await Promise.all([
        listEdu(kind.value, query.value), listEduGroups(kind.value),
      ])
      if (scope === generation && owner === auth.user?.id) {
        items.value = result.data
        groups.value = groupResult?.data || []
        if (!['__all__', '__ungrouped__'].includes(selectedGroup.value) && !groups.value.some(group => group.id === selectedGroup.value)) selectedGroup.value = '__all__'
      }
    }
  } catch (reason) {
    if (scope === generation) error.value = message(reason)
  } finally {
    if (scope === generation) loading.value = false
  }
}

watch([() => auth.user?.id, () => route.name], () => {
  generation++
  items.value = []
  groups.value = []
  selectedGroup.value = '__all__'
  groupEditor.value = false
  groupError.value = ''
  formGroupId.value = ''
  questions.value = []
  editor.value = false
  robotVisible.value = false
  canManage.value = false
  query.value = ''
  form.value = { title: '', content: '', group_name: '默认分组', tags: '' }
  if (auth.user?.id) void load()
}, { immediate: true })

function edit(item?: EduItem) {
  editingId.value = item?.id || null
  editorOwner.value = auth.user?.id || ''
  form.value = item ? { title: item.title, content: item.content, group_name: item.group_name, tags: item.tags || '' }
    : { title: '', content: '', group_name: kind.value === 'rules' ? '通知规则' : '默认分组', tags: '' }
  formGroupId.value = item ? item.group_id || '' : groups.value.some(group => group.id === selectedGroup.value) ? selectedGroup.value : ''
  editor.value = true
}

function editGroup(group?: EduScriptGroup) {
  editingGroupId.value = group?.id || null
  groupName.value = group?.name || ''
  groupError.value = ''
  groupEditorOwner.value = auth.user?.id || ''
  groupEditorKind.value = kind.value
  groupEditor.value = true
}

async function saveGroup() {
  if (groupSaving.value || groupEditorOwner.value !== auth.user?.id || groupEditorKind.value !== kind.value || !canEdit.value) return
  const name = groupName.value.trim()
  if (!name) { groupError.value = `请输入${groupLabel.value}名称`; return }
  groupSaving.value = true
  groupError.value = ''
  const owner = groupEditorOwner.value
  const itemKind = groupEditorKind.value
  try {
    const result = editingGroupId.value ? await renameEduGroup(itemKind, editingGroupId.value, name) : await createEduGroup(itemKind, name)
    if (owner !== auth.user?.id || kind.value !== itemKind) return
    selectedGroup.value = result.data.id
    groupEditor.value = false
    MessagePlugin.success(`${groupLabel.value}${editingGroupId.value ? '已重命名' : '已创建'}`)
    await load()
  } catch (reason) { if (owner === auth.user?.id && kind.value === itemKind) groupError.value = message(reason) }
  finally { groupSaving.value = false }
}

function removeGroup(group: EduScriptGroup) {
  const owner = auth.user?.id
  const itemKind = kind.value
  const label = itemLabel.value
  let deleting = false
  const dialog = DialogPlugin.confirm({
    header: `删除${groupLabel.value}`, theme: 'danger',
    body: `确定删除“${group.name}”吗？组内${label}会保留并移到“未分组”。`,
    onConfirm: async () => {
      if (deleting) return
      if (owner !== auth.user?.id || kind.value !== itemKind || !canEdit.value) { dialog.hide(); return }
      deleting = true
      try {
        await deleteEduGroup(itemKind, group.id)
        dialog.hide()
        if (owner !== auth.user?.id || kind.value !== itemKind) return
        if (selectedGroup.value === group.id) selectedGroup.value = '__ungrouped__'
        MessagePlugin.success(`${groupLabel.value}已删除，${label}已保留`)
        await load()
      } catch (reason) { MessagePlugin.error(message(reason)) }
      finally { deleting = false }
    },
  })
}

async function save() {
  if (saving.value || await formRef.value?.validate() !== true) return
  if (editorOwner.value !== auth.user?.id) {
    editor.value = false
    return
  }
  saving.value = true
  try {
    const content = { ...form.value, group_id: formGroupId.value || null }
    if (editingId.value) await updateEdu(kind.value, editingId.value, content)
    else await createEdu(kind.value, content)
    if (editorOwner.value === auth.user?.id) {
      editor.value = false
      MessagePlugin.success(kind.value === 'rules' ? '规则已保存，后台同步检索与钉钉推送' : '话术已保存，仅你可见')
      await load()
    }
  } catch (reason) {
    MessagePlugin.error(message(reason))
  } finally {
    saving.value = false
  }
}

function remove(item: EduItem) {
  const owner = auth.user?.id
  const itemKind = kind.value
  const dialog = DialogPlugin.confirm({
    header: `删除${itemKind === 'scripts' ? '话术' : '规则'}`,
    body: `确定删除“${item.title}”吗？`, theme: 'danger',
    onConfirm: async () => {
      if (owner !== auth.user?.id) { dialog.hide(); return }
      try {
        await deleteEdu(itemKind, item.id)
        dialog.hide()
        MessagePlugin.success('已删除')
        await load()
      } catch (reason) { MessagePlugin.error(message(reason)) }
    },
  })
}

async function copy(item: EduItem) {
  try {
    const html = renderEduContent(item.content)
    const plain = new DOMParser().parseFromString(html.replace(/<br\s*\/?\s*>/gi, '\n'), 'text/html').body.textContent || ''
    if (typeof ClipboardItem !== 'undefined' && navigator.clipboard.write) {
      await navigator.clipboard.write([new ClipboardItem({
        'text/plain': new Blob([plain], { type: 'text/plain' }),
        'text/html': new Blob([html], { type: 'text/html' }),
      })])
    } else await navigator.clipboard.writeText(plain)
    MessagePlugin.success('已复制')
  } catch { MessagePlugin.error('复制失败，请允许剪贴板访问或手动选择正文复制') }
}

async function push(item: EduItem) {
  busy.value[item.id] = true
  try { await pushEduRule(item.id); MessagePlugin.success('钉钉已确认推送成功'); await load() }
  catch (reason) { MessagePlugin.error(message(reason)) }
  finally { busy.value[item.id] = false }
}

async function openRobot() {
  try {
    const result = await getEduRobot()
    robot.value = { ...result.data, webhook: '', secret: '' }
    robotVisible.value = true
  } catch (reason) { MessagePlugin.error(message(reason)) }
}

async function saveRobot() {
  robotSaving.value = true
  try {
    await saveEduRobot({ enabled: robot.value.enabled,
      ...(robot.value.webhook.trim() ? { webhook: robot.value.webhook.trim() } : {}),
      ...(robot.value.secret.trim() ? { secret: robot.value.secret.trim() } : {}),
    })
    robotVisible.value = false
    robot.value.webhook = ''
    robot.value.secret = ''
    MessagePlugin.success('钉钉机器人配置已保存')
  } catch (reason) { MessagePlugin.error(message(reason)) }
  finally { robotSaving.value = false }
}

function quickQuestion(question: string) {
  menu.setPrefillQuery(question)
  void router.push('/platform/creatChat')
}
</script>

<template>
  <main class="edu-page" :class="{ 'edu-page--scripts': !analysis && kind === 'scripts', 'edu-page--grouped': !analysis }">
    <header class="edu-header">
      <div>
        <h1>{{ heading }}</h1>
        <p>{{ analysis ? '你的高频问题，点击后到智能搜索快速提问。' : kind === 'scripts' ? '所有话术按账号隔离，包括管理员；不会共享到文档库。' : '管理员维护公共规则，普通用户可以查看和复制。' }}</p>
      </div>
      <div class="edu-actions">
        <t-button variant="outline" :loading="loading" @click="load">刷新</t-button>
        <t-button v-if="!analysis && kind === 'rules' && canManage" variant="outline" @click="openRobot">钉钉设置</t-button>
        <t-button v-if="!analysis && canEdit" variant="outline" @click="editGroup()">新建{{ groupLabel }}</t-button>
        <t-button v-if="!analysis && canEdit" @click="edit()">{{ kind === 'scripts' ? '新建话术' : '新建规则' }}</t-button>
      </div>
    </header>
    <t-alert v-if="error" theme="error" :message="error" class="edu-alert" />
    <t-loading :loading="loading" class="edu-loading">
      <template v-if="analysis">
        <section class="edu-cloud" aria-labelledby="edu-cloud-heading">
          <h2 id="edu-cloud-heading">高频问题云</h2>
          <div v-if="questions.length" class="edu-keywords">
            <t-button v-for="entry in questions" :key="entry.question" variant="outline" @click="quickQuestion(entry.question)">
              {{ entry.question }} <span class="edu-frequency">{{ entry.count }} 次</span>
            </t-button>
          </div>
          <div v-else class="edu-analysis-empty"><t-icon name="file-search" size="92px" aria-hidden="true" /><p>暂时没有提问记录。在智能搜索提问后会自动汇总到这里。</p></div>
        </section>
      </template>
      <template v-else>
        <div class="edu-workbench edu-workbench--grouped">
        <aside class="edu-groups" :aria-label="groupLabel">
          <h2>{{ groupLabel }} <span>{{ groups.length }}</span></h2>
          <button type="button" class="edu-group-select" :class="{ selected: selectedGroup === '__all__' }"
            :aria-pressed="selectedGroup === '__all__'" @click="selectedGroup = '__all__'">全部{{ itemLabel }}</button>
          <button type="button" class="edu-group-select" :class="{ selected: selectedGroup === '__ungrouped__' }"
            :aria-pressed="selectedGroup === '__ungrouped__'" @click="selectedGroup = '__ungrouped__'">未分组</button>
          <div v-for="group in groups" :key="group.id" class="edu-group-row" :class="{ selected: selectedGroup === group.id }">
            <button type="button" class="edu-group-select" :aria-pressed="selectedGroup === group.id"
              :title="group.name" @click="selectedGroup = group.id"><span>{{ group.name }}</span><small>{{ group.count }}</small></button>
            <t-dropdown v-if="canEdit" trigger="click" placement="bottom-right">
              <t-button variant="text" shape="square" :aria-label="`管理${groupLabel}：${group.name}`"><t-icon name="more" /></t-button>
              <t-dropdown-menu><t-dropdown-item @click="editGroup(group)">重命名</t-dropdown-item><t-dropdown-item @click="removeGroup(group)">删除{{ groupLabel }}</t-dropdown-item></t-dropdown-menu>
            </t-dropdown>
          </div>
          <p v-if="!groups.length && !loading" class="edu-group-hint">{{ canEdit ? `点击“新建${groupLabel}”分类管理${itemLabel}。` : '暂时没有分组。' }}</p>
        </aside>
        <section class="edu-library-content" :aria-label="selectedGroupName">
        <form class="edu-search" @submit.prevent="load">
          <label for="edu-search">{{ kind === 'scripts' ? '搜索我的话术' : '搜索规则' }}</label>
          <t-input id="edu-search" v-model="query" clearable :maxlength="200" />
          <t-button type="submit" variant="outline" :disabled="loading">搜索</t-button>
        </form>
        <div class="edu-result-heading"><h2>{{ selectedGroupName }}</h2><span>{{ displayedItems.length }} 条{{ query ? '匹配' : '' }}{{ itemLabel }}</span></div>
        <div v-if="displayedItems.length" class="edu-grid">
          <article v-for="item in displayedItems" :key="item.id" class="edu-card">
            <div class="edu-card-head"><h2>{{ item.title }}</h2><t-tag variant="light">{{ item.group_name }}</t-tag></div>
            <EduCardContent :content="item.content" compact />
            <div class="edu-card-bottom">
            <p v-if="item.error" class="edu-status" role="status">{{ item.error }}</p>
            <p v-else-if="kind === 'rules' && item.state" class="edu-status">{{ item.state === 'synced' ? '已提交到知识库' : '后台同步中' }} · 钉钉：{{ item.push_status === 'sent' ? '已推送' : item.push_status === 'failed' ? '推送未确认' : item.push_status === 'pending' ? '推送中' : '未推送' }}</p>
            <footer class="edu-card-actions">
              <t-button variant="outline" @click="copy(item)">复制</t-button>
              <t-button v-if="canEdit" variant="text" @click="edit(item)">编辑</t-button>
              <t-button v-if="kind === 'rules' && canManage" variant="text" :loading="busy[item.id]" @click="push(item)">推送钉钉</t-button>
              <t-button v-if="canEdit" theme="danger" variant="text" @click="remove(item)">删除</t-button>
            </footer>
            </div>
          </article>
        </div>
        <div v-else-if="!loading && !error" class="edu-empty"><p>{{ kind === 'scripts' ? query ? '没有找到匹配的话术，请调整搜索词或切换话术组。' : '该分组暂无话术，可以创建第一条话术。' : '暂无规则通知。' }}</p><t-button v-if="kind === 'scripts'" variant="outline" @click="edit()">新建话术</t-button></div>
        </section>
        </div>
      </template>
    </t-loading>

    <t-dialog v-model:visible="editor" :header="`${editingId ? '编辑' : '新建'}${kind === 'scripts' ? '话术' : '规则'}`"
      width="min(720px, 92vw)" :confirm-btn="{ content: '保存', loading: saving, disabled: saving }"
      :close-on-overlay-click="false" :close-on-esc-keydown="!saving" @confirm="save">
      <t-form ref="formRef" :data="form" :rules="formRules" label-align="top" @submit="save">
        <t-form-item label="标题" name="title"><t-input v-model="form.title" :maxlength="255" /></t-form-item>
        <t-form-item label="分组" name="group_name">
          <t-select v-model="formGroupId" :disabled="saving" :options="[{ label: '未分组', value: '' }, ...groups.map(group => ({ label: group.name, value: group.id }))]" />
        </t-form-item>
        <t-form-item label="标签" name="tags"><t-input v-model="form.tags" :maxlength="2000" /></t-form-item>
        <t-form-item label="正文" name="content">
          <EduRichTextEditor :key="editingId || 'new'" v-model="form.content" :disabled="saving" :maxlength="300000" />
        </t-form-item>
        <section class="edu-preview"><h3>预览</h3><div class="edu-content" v-html="renderEduContent(form.content)" /></section>
      </t-form>
    </t-dialog>
    <t-dialog v-model:visible="groupEditor" :header="`${editingGroupId ? '重命名' : '新建'}${groupLabel}`" width="min(420px, 92vw)"
      :confirm-btn="{ content: '保存', loading: groupSaving, disabled: groupSaving }"
      :cancel-btn="{ content: '取消', disabled: groupSaving }" :close-btn="!groupSaving"
      :close-on-overlay-click="false" :close-on-esc-keydown="!groupSaving" @confirm="saveGroup">
      <form @submit.prevent="saveGroup">
        <label for="edu-group-name">{{ groupLabel }}名称</label>
        <input id="edu-group-name" v-model="groupName" class="edu-group-input" type="text" maxlength="120" :disabled="groupSaving"
          :aria-invalid="!!groupError" aria-describedby="edu-group-error" required />
        <p id="edu-group-error" class="edu-group-error" role="status">{{ groupError || (kind === 'scripts' ? '话术组仅自己可见，最多 120 个字符。' : '规则分组由管理员维护，最多 120 个字符。') }}</p>
      </form>
    </t-dialog>
    <t-dialog v-model:visible="robotVisible" header="钉钉机器人配置" width="min(640px, 92vw)"
      :confirm-btn="{ content: '保存配置', loading: robotSaving }" :destroy-on-close="true" :close-on-overlay-click="false" @confirm="saveRobot">
      <t-form label-align="top">
        <t-form-item label="启用规则推送"><t-switch v-model="robot.enabled" /></t-form-item>
        <t-form-item label="群机器人 Webhook"><t-input v-model="robot.webhook" type="password" name="edu-robot-webhook" autocomplete="new-password" :placeholder="robot.webhook_configured ? '已配置；留空保留现有地址' : 'https://oapi.dingtalk.com/robot/send?access_token=...'" /></t-form-item>
        <t-form-item label="加签密钥"><t-input v-model="robot.secret" type="password" name="edu-robot-secret" autocomplete="new-password" :placeholder="robot.secret_configured ? '已配置；留空保留现有密钥' : '选填，填写机器人安全设置中的 SEC...'" /></t-form-item>
        <p>密钥只保存在服务端，不会返回浏览器。迁移已有规则不会自动向群聊重发。</p>
      </t-form>
    </t-dialog>
  </main>
</template>

<style scoped>
/* Hallmark · genre: modern-minimal · macrostructure: Workbench · design-system: design.md · designed-as-app
 * Compact private scripts with a group rail; no decorative motion. */
.edu-workbench--grouped { display: grid; grid-template-columns: 216px minmax(0,1fr); gap: var(--kh-space-lg); }
.edu-library-content { min-width: 0; }
.edu-groups { min-width: 0; border-inline-end: 1px solid var(--td-component-border); padding-inline-end: var(--kh-space-md); }
.edu-groups h2 { display: flex; justify-content: space-between; font-size: 14px; margin-bottom: var(--kh-space-sm); }
.edu-groups h2 span, .edu-group-select small, .edu-result-heading span { font-size: 12px; color: var(--td-text-color-secondary); }
.edu-group-row { display: flex; align-items: center; border-radius: var(--kh-radius); margin-top: 4px; min-width: 0; }
.edu-group-select { display: flex; align-items: center; justify-content: space-between; gap: var(--kh-space-xs); width: 100%; min-width: 0; min-height: 40px; padding: var(--kh-space-xs) var(--kh-space-sm); border: 0; border-radius: var(--kh-radius); color: var(--td-text-color-primary); background: transparent; font: inherit; font-size: 14px; text-align: start; cursor: pointer; }
.edu-group-select span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.edu-group-select small { flex-shrink: 0; }
.edu-groups .selected { background: var(--td-brand-color-light); }
.edu-groups .selected > .edu-group-select, .edu-group-select.selected { color: var(--td-brand-color); font-weight: 600; }
.edu-group-select:focus-visible { outline: 2px solid var(--kh-ui-focus); outline-offset: 2px; }
.edu-group-select:active { background: var(--td-brand-color-light); }
.edu-group-row :deep(.t-button) { flex-shrink: 0; }
.edu-group-hint, .edu-group-error { font-size: 12px; line-height: 1.6; color: var(--td-text-color-secondary); }
.edu-group-error { min-height: 20px; }
.edu-group-input { display: block; box-sizing: border-box; width: 100%; height: 36px; margin-top: var(--kh-space-xs); padding-inline: var(--kh-space-sm); border: 1px solid var(--td-component-border); border-radius: var(--kh-radius); background: var(--td-bg-color-container); color: var(--td-text-color-primary); font: inherit; }
.edu-group-input:focus-visible { outline: 2px solid var(--kh-ui-focus); outline-offset: 2px; }
.edu-group-input[aria-invalid="true"] { border-color: var(--td-error-color); }
.edu-group-input:disabled { opacity: .6; cursor: not-allowed; }
.edu-result-heading { display: flex; align-items: baseline; justify-content: space-between; gap: var(--kh-space-sm); margin-bottom: var(--kh-space-md); }
.edu-result-heading h2 { font-size: 16px; overflow-wrap: anywhere; }
@media (hover:hover) { .edu-group-select:hover { background: var(--td-bg-color-secondarycontainer); } }
@media (max-width: 64rem) {
  .edu-workbench--grouped { grid-template-columns: minmax(0,1fr); gap: var(--kh-space-md); }
  .edu-groups { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; padding-inline-end: 0; padding-bottom: var(--kh-space-sm); border-inline-end: 0; border-bottom: 1px solid var(--td-component-border); }
  .edu-groups h2 { width: 100%; margin-bottom: 4px; }
  .edu-groups > .edu-group-select, .edu-group-row { width: auto; max-width: 100%; margin: 0; }
  .edu-group-row { max-width: 240px; }
}
@media (pointer:coarse) { .edu-group-select, .edu-group-row :deep(.t-button) { min-height: 44px; } }
.edu-page { box-sizing: border-box; padding: 24px; width: 100%; min-width: 0; overflow: auto; color: var(--td-text-color-primary); background: var(--td-bg-color-container); }
.edu-header { display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: 20px; margin-bottom: 24px; }
h1 { font-size: 24px; line-height: 1.4; margin: 0 0 8px; } h2 { font-size: 18px; margin: 0; line-height: 1.5; } h3 { font-size: 15px; }
.edu-header p { margin: 0; color: var(--td-text-color-secondary); line-height: 1.6; }
.edu-actions, .edu-card-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.edu-alert { margin-bottom: 16px; } .edu-loading { width: 100%; min-height: 160px; }
.edu-search { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 24px; }
.edu-search :deep(.t-input__wrap) { max-width: 360px; width: min(360px,100%); }
.edu-grid { display: grid; grid-template-columns: repeat(auto-fill,min(340px,100%)); align-items: stretch; gap: 16px; }
.edu-card, .edu-cloud { padding: 24px; border: 1px solid var(--td-component-border); border-radius: 12px; min-width: 0; }
.edu-card { display: flex; flex-direction: column; box-sizing: border-box; padding: 16px; border-radius: 8px; }
.edu-card-head { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,88px); align-items: start; gap: 8px; min-height: 48px; margin-bottom: 12px; }
.edu-card-head h2 { font-size: 16px; overflow-wrap: anywhere; }
.edu-card-head :deep(.t-tag) { justify-self: end; max-width: 100%; height: auto; white-space: normal; overflow-wrap: anywhere; }
.edu-content { line-height: 1.75; overflow-wrap: anywhere; max-width: 76ch; } .edu-content :deep(img) { max-width: 100%; }
.edu-content :deep(pre) { overflow: auto; } .edu-content :deep(table) { display: block; overflow: auto; }
.edu-card-bottom { margin-top: auto; padding-top: 12px; }
.edu-card-actions { margin-top: 0; padding-top: 12px; gap: 8px; border-top: 1px solid var(--td-component-border); }
.edu-card-actions :deep(.t-button) { flex-shrink: 0; }
.edu-status { color: var(--td-text-color-secondary); font-size: 13px; line-height: 1.6; }
.edu-empty { padding: 48px 0; text-align: center; color: var(--td-text-color-secondary); }
.edu-keywords { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 24px; }
.edu-keywords :deep(.t-button) { height: auto; min-height: 40px; white-space: normal; text-align: left; max-width: 100%; }
.edu-frequency { margin-left: 8px; color: var(--td-text-color-secondary); white-space: nowrap; }
.edu-preview { margin-top: 20px; padding: 16px; background: var(--td-bg-color-secondarycontainer); border-radius: 8px; }
@media (max-width: 600px) { .edu-page { padding: 20px 16px; } .edu-grid { grid-template-columns: minmax(0,1fr); } }
</style>
