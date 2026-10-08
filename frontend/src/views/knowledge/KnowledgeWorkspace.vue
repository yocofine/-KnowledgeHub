<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import KnowledgeBaseList from './KnowledgeBaseList.vue'
import KnowledgeBase from './KnowledgeBase.vue'

const route = useRoute()
const selectedId = computed(() => String(route.params.kbId || ''))
const revision = ref(0)
function onSaved(id: string) {
  if (id === selectedId.value) revision.value++
}
</script>

<template>
  <div class="knowledge-workspace">
    <aside class="knowledge-workspace__libraries" aria-label="知识库列表">
      <KnowledgeBaseList sidebar @knowledge-base-updated="onSaved" />
    </aside>
    <section class="knowledge-workspace__content" aria-label="知识库内容">
      <KnowledgeBase v-if="selectedId" :key="`${selectedId}:${revision}`" :editor-host="false" />
      <div v-else class="knowledge-workspace__empty">
        <t-icon name="folder-open" size="36px" aria-hidden="true" />
        <h2>选择一个知识库</h2>
        <p>点击中间列表，查看该知识库的文件和内容。</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.knowledge-workspace { display: grid; grid-template-columns: 280px minmax(0,1fr); width: 100%; height: 100%; min-width: 0; min-height: 0; overflow: hidden; }
.knowledge-workspace__libraries { min-width: 0; min-height: 0; overflow: hidden; border-right: 1px solid var(--td-component-border); background: var(--td-bg-color-sidebar); }
.knowledge-workspace__content { min-width: 0; min-height: 0; overflow: auto; background: var(--td-bg-color-container); }
.knowledge-workspace__empty { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 320px; height: 100%; padding: 24px; box-sizing: border-box; text-align: center; color: var(--td-text-color-secondary); }
.knowledge-workspace__empty h2 { font-size: 20px; margin: 16px 0 8px; color: var(--td-text-color-primary); }
.knowledge-workspace__empty p { margin: 0; line-height: 1.6; }
@media (max-width: 960px) { .knowledge-workspace { grid-template-columns: 240px minmax(0,1fr); } }
@media (max-width: 640px) {
  .knowledge-workspace { display: flex; flex-direction: column; overflow: auto; }
  .knowledge-workspace__libraries { flex: 0 0 300px; border-right: 0; border-bottom: 1px solid var(--td-component-border); }
  .knowledge-workspace__content { flex: 1 0 360px; }
}
</style>
