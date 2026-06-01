<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { isAxiosError } from 'axios'
import { Delete, Upload } from '@element-plus/icons-vue'
import * as imagesApi from '@/api/images'
import type { ImageResponse } from '@/api/images'

const images = ref<ImageResponse[]>([])
const loading = ref(true)
const total = ref(0)
const page = ref(1)
const pageSize = ref(12)
const uploading = ref(false)
const fileInput = ref<HTMLInputElement>()

async function loadData() {
  loading.value = true
  try {
    const skip = (page.value - 1) * pageSize.value
    const result = await imagesApi.listImages(skip, pageSize.value)
    images.value = result.items
    total.value = result.total
  } catch {
    images.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

async function handleUpload(file: File) {
  uploading.value = true
  try {
    await imagesApi.uploadImage(file)
    ElMessage.success('上传成功')
    await loadData()
  } catch (error) {
    const message = isAxiosError(error) ? error.response?.data?.detail : null
    ElMessage.error(message || '上传失败')
  } finally {
    uploading.value = false
  }
}

function openFilePicker() {
  if (!uploading.value) {
    fileInput.value?.click()
  }
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) handleUpload(file)
  input.value = ''
}

async function handleDelete(img: ImageResponse) {
  await ElMessageBox.confirm(`确定删除「${img.filename}」吗？`, '删除确认', { type: 'warning' })
  await imagesApi.deleteImage(img.id)
  ElMessage.success('已删除')
  await loadData()
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

onMounted(loadData)
</script>

<template>
  <div class="image-library">
    <div class="page-header">
      <h2>图片库</h2>
      <el-button type="primary" :icon="Upload" :loading="uploading" @click="openFilePicker">
        {{ uploading ? '上传中...' : '上传图片' }}
      </el-button>
      <input ref="fileInput" type="file" accept="image/*" @change="onFileChange" hidden />
    </div>

    <div v-if="images.length === 0 && !loading" class="empty-state">暂无图片</div>

    <div class="image-grid">
      <div v-for="img in images" :key="img.id" class="image-card">
        <div class="image-preview">
          <img :src="img.fileUrl" :alt="img.filename" />
        </div>
        <div class="image-info">
          <span class="image-name" :title="img.filename">{{ img.filename }}</span>
          <span class="image-size">{{ formatFileSize(img.fileSize) }}</span>
        </div>
        <div class="image-actions">
          <el-button text type="danger" :icon="Delete" size="small" @click="handleDelete(img)" />
        </div>
      </div>
    </div>

    <div class="pagination-wrap">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="loadData"
      />
    </div>
  </div>
</template>

<style scoped>
.image-library { padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h2 { margin: 0; }
.empty-state { text-align: center; color: #909399; padding: 48px; }
.image-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 16px; }
.image-card { border: 1px solid #ebeef5; border-radius: 8px; overflow: hidden; }
.image-preview { height: 150px; overflow: hidden; background: #f5f7fa; display: flex; align-items: center; justify-content: center; }
.image-preview img { max-width: 100%; max-height: 100%; object-fit: cover; }
.image-info { padding: 8px 12px; display: flex; flex-direction: column; }
.image-name { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.image-size { font-size: 12px; color: #909399; margin-top: 2px; }
.image-actions { padding: 0 8px 8px; text-align: right; }
.pagination-wrap { display: flex; justify-content: center; margin-top: 16px; }
</style>
