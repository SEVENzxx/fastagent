<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as contactsApi from '@/api/contacts'
import type { ContactImportResponse } from '@/api/contacts'

const props = defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  imported: []
}>()

const selectedFile = ref<File | null>(null)
const importing = ref(false)
const result = ref<ContactImportResponse | null>(null)

const hasErrors = computed(() => (result.value?.errors.length ?? 0) > 0)

watch(
  () => props.visible,
  (visible) => {
    if (!visible) return
    selectedFile.value = null
    result.value = null
    importing.value = false
  },
)

function selectFile(file: File) {
  if (!file.name.toLowerCase().endsWith('.csv')) {
    ElMessage.warning('请上传 CSV 文件')
    return false
  }
  if (file.size > 2 * 1024 * 1024) {
    ElMessage.warning('CSV 文件不能超过 2MB')
    return false
  }
  selectedFile.value = file
  result.value = null
  return false
}

function handleFileChange(uploadFile: any) {
  const file = uploadFile.raw as File | undefined
  if (file) selectFile(file)
}

async function downloadTemplate() {
  try {
    const blob = await contactsApi.downloadContactImportTemplate()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'contact_import_template.csv'
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '模板下载失败')
  }
}

async function handleImport() {
  if (!selectedFile.value) {
    ElMessage.warning('请先选择 CSV 文件')
    return
  }

  importing.value = true
  try {
    result.value = await contactsApi.importContacts(selectedFile.value)
    if (result.value.success) {
      ElMessage.success(`成功导入 ${result.value.createdCount} 个联系人`)
      emit('imported')
    } else {
      ElMessage.warning('导入文件存在错误，请修正后重新上传')
    }
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '批量导入失败')
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="批量导入联系人"
    width="720px"
    destroy-on-close
    @update:model-value="emit('update:visible', $event)"
  >
    <div class="import-body">
      <div class="toolbar">
        <el-button @click="downloadTemplate">下载 CSV 模板</el-button>
      </div>

      <el-alert
        title="导入前会校验联系人名称、电话、企微外部联系人 ID、标签和分配员工。发现任意错误时，整批联系人都不会写入。"
        type="info"
        show-icon
        :closable="false"
      />

      <el-upload
        drag
        action="#"
        :auto-upload="false"
        :show-file-list="false"
        :before-upload="selectFile"
        :on-change="handleFileChange"
        accept=".csv,text/csv"
      >
        <div class="upload-inner">
          <div class="upload-title">选择或拖入 CSV 文件</div>
          <div class="upload-subtitle">支持 UTF-8 或 GBK 编码，最大 2MB</div>
        </div>
      </el-upload>

      <div v-if="selectedFile" class="file-line">
        <span>{{ selectedFile.name }}</span>
        <small>{{ (selectedFile.size / 1024).toFixed(1) }} KB</small>
      </div>

      <el-alert
        v-if="result?.success"
        :title="`导入完成：共 ${result.totalRows} 行，成功创建 ${result.createdCount} 个联系人`"
        type="success"
        show-icon
        :closable="false"
      />

      <div v-if="hasErrors" class="error-panel">
        <div class="error-title">
          <strong>发现 {{ result?.errors.length }} 个错误</strong>
          <span>请修正 CSV 后重新上传</span>
        </div>
        <el-table :data="result?.errors" size="small" max-height="260" border>
          <el-table-column prop="row" label="行号" width="80" />
          <el-table-column prop="field" label="字段" width="140" />
          <el-table-column prop="message" label="错误原因" min-width="280" />
        </el-table>
      </div>
    </div>

    <template #footer>
      <el-button @click="emit('update:visible', false)">关闭</el-button>
      <el-button type="primary" :loading="importing" @click="handleImport">
        开始导入
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.import-body {
  display: grid;
  gap: 14px;
}

.toolbar {
  display: flex;
  justify-content: flex-end;
}

.upload-inner {
  padding: 18px 0;
}

.upload-title {
  color: var(--text-strong);
  font-weight: 600;
}

.upload-subtitle {
  margin-top: 6px;
  color: var(--text-muted);
  font-size: 12px;
}

.file-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-soft);
}

.file-line small {
  color: var(--text-muted);
}

.error-panel {
  display: grid;
  gap: 10px;
}

.error-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.error-title span {
  color: var(--text-muted);
  font-size: 13px;
}
</style>
