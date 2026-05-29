<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as contactsApi from '@/api/contacts'
import * as ordersApi from '@/api/orders'
import type { ContactResponse } from '@/api/contacts'
import type { OrderResponse } from '@/api/orders'
import OrderCard from '@/components/orders/OrderCard.vue'

const route = useRoute()
const router = useRouter()
const contact = ref<ContactResponse | null>(null)
const loading = ref(true)
const activeTab = ref('profile')
const orders = ref<OrderResponse[]>([])
const ordersLoading = ref(false)

async function loadData() {
  loading.value = true
  try {
    contact.value = await contactsApi.getContact(route.params.id as string)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '联系人不存在')
    router.push('/contacts')
  } finally {
    loading.value = false
  }
}

async function loadOrders() {
  ordersLoading.value = true
  try {
    const result = await ordersApi.getOrders({
      contactId: route.params.id as string,
      page: 1,
      pageSize: 50,
    })
    orders.value = result.items
  } finally {
    ordersLoading.value = false
  }
}

function onTabChange(tab: string) {
  if (tab === 'orders' && orders.value.length === 0) {
    loadOrders()
  }
}

async function handleOrderStatusChange(orderId: string, toStatus: string) {
  try {
    await ordersApi.transitionOrderStatus(orderId, toStatus)
    ElMessage.success('订单状态已更新')
    loadOrders()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '操作失败')
  }
}

onMounted(loadData)
</script>

<template>
  <div class="page" v-loading="loading">
    <section class="page-header">
      <div>
        <p>联系人详情</p>
        <h2>{{ contact?.name || '-' }}</h2>
      </div>
      <el-button @click="router.push('/contacts')">返回列表</el-button>
    </section>

    <section>
      <el-tabs v-model="activeTab" @tab-change="onTabChange">
        <el-tab-pane label="基本资料" name="profile">
          <div v-if="contact" class="detail-panel">
            <div class="profile-row">
              <el-avatar :size="64" :src="contact.avatarUrl || undefined">
                {{ contact.name.slice(0, 1) }}
              </el-avatar>
              <div>
                <h3>{{ contact.name }}</h3>
                <p>{{ contact.phone || '暂无电话' }}</p>
              </div>
            </div>

            <el-descriptions :column="2" border>
              <el-descriptions-item label="分配员工">
                {{ contact.assignedEmployeeName || '未分配' }}
              </el-descriptions-item>
              <el-descriptions-item label="创建时间">
                {{ new Date(contact.createdAt).toLocaleString() }}
              </el-descriptions-item>
              <el-descriptions-item label="地址" :span="2">
                {{ contact.address || '暂无' }}
              </el-descriptions-item>
              <el-descriptions-item label="标签" :span="2">
                <div class="tag-list">
                  <el-tag v-for="tag in contact.tags" :key="tag" effect="plain">{{ tag }}</el-tag>
                  <span v-if="!contact.tags.length">暂无</span>
                </div>
              </el-descriptions-item>
              <el-descriptions-item label="外部 ID" :span="2">
                <pre>{{ JSON.stringify(contact.externalIds || {}, null, 2) }}</pre>
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </el-tab-pane>

        <el-tab-pane label="订单历史" name="orders">
          <div v-loading="ordersLoading" class="order-tab">
            <el-empty v-if="!orders.length && !ordersLoading" description="暂无订单" />
            <div v-else class="order-list">
              <OrderCard
                v-for="order in orders"
                :key="order.id"
                :order="order"
                @status-change="(orderId: any, toStatus: any) => handleOrderStatusChange(orderId, toStatus)"
              />
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>
  </div>
</template>

<style scoped>
.page {
  display: grid;
  gap: 18px;
}

.page-header,
.detail-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 22px;
}

.page-header p {
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 600;
}

.page-header h2 {
  margin-top: 4px;
  color: var(--text-strong);
  font-size: 22px;
}

.detail-panel {
  display: grid;
  gap: 22px;
  padding: 22px;
}

.profile-row {
  display: flex;
  align-items: center;
  gap: 16px;
}

.profile-row h3 {
  color: var(--text-strong);
  font-size: 18px;
}

.profile-row p {
  margin-top: 4px;
  color: var(--text-muted);
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

pre {
  margin: 0;
  white-space: pre-wrap;
  color: var(--text);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.order-tab {
  min-height: 200px;
}

.order-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0;
}
</style>
