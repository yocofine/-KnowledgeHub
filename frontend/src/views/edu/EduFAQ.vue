<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { eduMe } from '@/api/edu'
const router = useRouter()
const error = ref('')
onMounted(async () => {
  try {
    const response = await eduMe()
    if (!response.data.faq_kb_id) throw new Error('FAQ 库尚未配置')
    await router.replace(`/platform/knowledge-bases/${response.data.faq_kb_id}`)
  } catch (reason: any) { error.value = reason?.message || '加载失败，请刷新重试' }
})
</script>
<template><main style="padding:32px"><t-alert v-if="error" theme="error" :message="error" /><t-loading v-else loading text="正在打开独立 FAQ 库" /></main></template>
