<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'
import * as ordersApi from '@/api/orders'
import * as contactsApi from '@/api/contacts'
import * as productsApi from '@/api/products'
import type { OrderResponse, OrderCreate, OrderItemCreate } from '@/api/orders'
import type { ContactListResponse } from '@/api/contacts'
import type { ProductResponse } from '@/api/products'

const orders = ref<OrderResponse[]>([])
const loading = ref(true)
const total = ref(0)
const page = ref(1)
const pageSize = ref(12)
const filterStatus = ref<string | null>(null)

// -- detail drawer
const drawerVisible = ref(false)
const detailOrder = ref<OrderResponse | null>(null)

// -- create dialog
const createDialogVisible = ref(false)
const createForm = ref({
  contactId: null as string | null,
  items: [{ productName: '', quantity: 1 }] as OrderItemCreate[],
  shippingAddress: '' as string,
  receiverName: '' as string,
  receiverPhone: '' as string,
  remark: '' as string,
})

// -- contacts for create form
const contacts = ref<ContactListResponse['items']>([])
const products = ref<ProductResponse[]>([])

async function loadData() {
  loading.value = true
  try {
    const result = await ordersApi.getOrders({
      status: filterStatus.value || undefined,
      page: page.value,
      pageSize: pageSize.value,
    })
    orders.value = result.items
    total.value = result.total
  } catch {
    orders.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function onStatusFilter(status: string | null) {
  filterStatus.value = status
  page.value = 1
  loadData()
}

function onPageChange(newPage: number) {
  page.value = newPage
  loadData()
}

function openDetail(order: OrderResponse) {
  detailOrder.value = order
  drawerVisible.value = true
}

async function openCreateDialog() {
  createDialogVisible.value = true
  createForm.value = {
    contactId: null,
    items: [{ productName: '', quantity: 1 }],
    shippingAddress: '',
    receiverName: '',
    receiverPhone: '',
    remark: '',
  }
  try {
    const cResult = await contactsApi.getContacts({ page: 1, pageSize: 100 })
    contacts.value = cResult.items
    const pResult = await productsApi.getProducts(1, 100)
    products.value = pResult.items
  } catch { /* ignore */ }
}

function addItemRow() {
  createForm.value.items.push({ productName: '', quantity: 1 })
}

function removeItemRow(index: number) {
  if (createForm.value.items.length > 1) {
    createForm.value.items.splice(index, 1)
  }
}

function getSelectedProduct(productName: string) {
  return products.value.find((product) => product.name === productName)
}

function formatCurrency(value: number | null | undefined) {
  return `¥${Number(value || 0).toFixed(2)}`
}

function getItemSubtotal(item: OrderItemCreate) {
  const product = getSelectedProduct(item.productName)
  return Number(product?.price || 0) * Number(item.quantity || 0)
}

function handleContactChange(contactId: string | null) {
  const contact = contacts.value.find((item) => item.id === contactId)
  if (!contact) {
    return
  }
  createForm.value.receiverName = contact.name || ''
  createForm.value.receiverPhone = contact.phone || ''
  createForm.value.shippingAddress = contact.address || ''
}

async function handleCreate() {
  const items = createForm.value.items.filter((it) => it.productName.trim())
  if (items.length === 0) {
    ElMessage.warning('请至少添加一个商品')
    return
  }
  try {
    const body: OrderCreate = {
      contactId: createForm.value.contactId || undefined,
      items,
      shippingAddress: createForm.value.shippingAddress || undefined,
      receiverName: createForm.value.receiverName || undefined,
      receiverPhone: createForm.value.receiverPhone || undefined,
      remark: createForm.value.remark || undefined,
    }
    await ordersApi.createOrder(body)
    ElMessage.success('订单创建成功')
    createDialogVisible.value = false
    loadData()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '创建失败')
  }
}

async function handleStatusTransition(order: OrderResponse, toStatus: string) {
  try {
    await ordersApi.transitionOrderStatus(order.id, toStatus)
    ElMessage.success('状态已更新')
    if (drawerVisible.value && detailOrder.value?.id === order.id) {
      detailOrder.value = await ordersApi.getOrder(order.id)
    }
    loadData()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '操作失败')
  }
}

async function handleCancel(order: OrderResponse) {
  try {
    const { value: reason } = await ElMessageBox.prompt(
      '取消后客户将收到通知，请填写取消原因。',
      '取消订单',
      {
        confirmButtonText: '确定取消',
        cancelButtonText: '返回',
        inputPlaceholder: '请填写取消原因',
        inputValidator: (v: string) => !!v.trim() || '取消原因不能为空',
      },
    )
    await ordersApi.transitionOrderStatus(order.id, 'cancelled', reason)
    ElMessage.success('订单已取消，已通知客户')
    loadData()
    drawerVisible.value = false
  } catch { /* cancelled */ }
}

function canTransition(order: OrderResponse, toStatus: string): boolean {
  const transitions: Record<string, string[]> = {
    draft: ['pending_customer_confirm', 'cancelled'],
    pending_customer_confirm: ['customer_confirmed', 'cancelled'],
    customer_confirmed: ['shipped', 'cancelled'],
    agent_confirmed: ['shipped', 'cancelled'],
    shipped: ['signed'],
    signed: [],
    cancelled: [],
  }
  return (transitions[order.status] || []).includes(toStatus)
}

const statusTabs = [
  { label: '全部', value: null },
  { label: '待客户确认', value: 'pending_customer_confirm' },
  { label: '待审核发货', value: 'customer_confirmed' },
  { label: '已发货', value: 'shipped' },
  { label: '已签收', value: 'signed' },
]

onMounted(() => {
  loadData()
})
</script>

<template>
  <div class="order-list-page">
    <div class="page-header">
      <h2>订单管理</h2>
      <el-button type="primary" :icon="Plus" @click="openCreateDialog">创建订单</el-button>
    </div>

    <!-- status filter tabs -->
    <div class="status-filter">
      <el-radio-group v-model="filterStatus" size="small" @change="onStatusFilter">
        <el-radio-button
          v-for="tab in statusTabs"
          :key="tab.value"
          :value="tab.value"
        >
          {{ tab.label }}
        </el-radio-button>
      </el-radio-group>
    </div>

    <!-- table -->
    <el-table
      :data="orders"
      v-loading="loading"
      stripe
      @row-click="openDetail"
      style="cursor: pointer; width: 100%"
    >
      <el-table-column label="订单号" width="180">
        <template #default="{ row }">
          <span class="order-id">{{ row.id }}</span>
        </template>
      </el-table-column>
      <el-table-column label="客户" width="140">
        <template #default="{ row }">
          {{ row.contactName || row.contactId }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="ordersApi.STATUS_COLORS[row.status] || 'info'">
            {{ ordersApi.STATUS_LABELS[row.status] || row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="应付金额" width="120" align="right">
        <template #default="{ row }">
          ¥{{ row.payableAmount.toFixed(2) }}
        </template>
      </el-table-column>
      <el-table-column label="商品数" width="80" align="center">
        <template #default="{ row }">
          {{ row.items?.length || 0 }}
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="180">
        <template #default="{ row }">
          {{ new Date(row.createdAt).toLocaleString('zh-CN') }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="canTransition(row, 'customer_confirmed')"
            size="small"
            type="success"
            @click.stop="handleStatusTransition(row, 'customer_confirmed')"
          >
            确认
          </el-button>
          <el-button
            v-if="canTransition(row, 'agent_confirmed')"
            size="small"
            type="primary"
            @click.stop="handleStatusTransition(row, 'agent_confirmed')"
          >
            审核
          </el-button>
          <el-button
            v-if="canTransition(row, 'shipped')"
            size="small"
            type="warning"
            @click.stop="handleStatusTransition(row, 'shipped')"
          >
            {{ row.status === 'customer_confirmed' ? '审核并发货' : '发货' }}
          </el-button>
          <el-button
            v-if="canTransition(row, 'cancelled')"
            size="small"
            type="danger"
            @click.stop="handleCancel(row)"
          >
            取消
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- pagination -->
    <div class="pagination-wrap">
      <el-pagination
        v-model:current-page="page"
        :total="total"
        :page-size="pageSize"
        layout="total, prev, pager, next"
        @current-change="onPageChange"
      />
    </div>

    <!-- detail drawer -->
    <el-drawer
      v-model="drawerVisible"
      title="订单详情"
      size="480px"
    >
      <template v-if="detailOrder">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="订单号">{{ detailOrder.id }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="ordersApi.STATUS_COLORS[detailOrder.status] || 'info'">
              {{ ordersApi.STATUS_LABELS[detailOrder.status] || detailOrder.status }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="客户">
            {{ detailOrder.contactName || detailOrder.contactId }}
          </el-descriptions-item>
          <el-descriptions-item label="商品合计">
            ¥{{ detailOrder.totalAmount.toFixed(2) }}
          </el-descriptions-item>
          <el-descriptions-item label="优惠金额">
            ¥{{ detailOrder.discountAmount.toFixed(2) }}
          </el-descriptions-item>
          <el-descriptions-item label="应付金额">
            <strong>¥{{ detailOrder.payableAmount.toFixed(2) }}</strong>
          </el-descriptions-item>
          <el-descriptions-item v-if="detailOrder.receiverName" label="收货人">
            {{ detailOrder.receiverName }}
          </el-descriptions-item>
          <el-descriptions-item v-if="detailOrder.receiverPhone" label="联系电话">
            {{ detailOrder.receiverPhone }}
          </el-descriptions-item>
          <el-descriptions-item v-if="detailOrder.shippingAddress" label="收货地址">
            {{ detailOrder.shippingAddress }}
          </el-descriptions-item>
          <el-descriptions-item v-if="detailOrder.remark" label="备注">
            {{ detailOrder.remark }}
          </el-descriptions-item>
          <el-descriptions-item label="创建来源">
            {{ detailOrder.createdByType === 'ai' ? 'AI' : detailOrder.createdByType === 'agent' ? '坐席' : '系统' }}
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">
            {{ new Date(detailOrder.createdAt).toLocaleString('zh-CN') }}
          </el-descriptions-item>
        </el-descriptions>

        <h4 style="margin-top: 20px; margin-bottom: 12px">商品明细</h4>
        <el-table :data="detailOrder.items" size="small">
          <el-table-column label="商品名">
            <template #default="{ row }">
              {{ row.productSnapshot?.product_name || '-' }}
            </template>
          </el-table-column>
          <el-table-column label="数量" width="60">
            <template #default="{ row }">{{ row.quantity }}</template>
          </el-table-column>
          <el-table-column label="单价" width="100">
            <template #default="{ row }">¥{{ row.unitPrice.toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="小计" width="100">
            <template #default="{ row }">¥{{ row.subtotal.toFixed(2) }}</template>
          </el-table-column>
        </el-table>

        <div class="drawer-actions" style="margin-top: 24px">
          <el-button
            v-if="canTransition(detailOrder, 'customer_confirmed')"
            type="success"
            @click="handleStatusTransition(detailOrder, 'customer_confirmed')"
          >
            确认订单
          </el-button>
          <el-button
            v-if="canTransition(detailOrder, 'agent_confirmed')"
            type="primary"
            @click="handleStatusTransition(detailOrder, 'agent_confirmed')"
          >
            审核通过
          </el-button>
          <el-button
            v-if="canTransition(detailOrder, 'shipped')"
            type="warning"
            @click="handleStatusTransition(detailOrder, 'shipped')"
          >
            {{ detailOrder.status === 'customer_confirmed' ? '审核通过并发货' : '标记发货' }}
          </el-button>
          <el-button
            v-if="canTransition(detailOrder, 'signed')"
            type="success"
            @click="handleStatusTransition(detailOrder, 'signed')"
          >
            标记签收
          </el-button>
          <el-button
            v-if="canTransition(detailOrder, 'cancelled')"
            type="danger"
            @click="handleCancel(detailOrder)"
          >
            取消订单
          </el-button>
        </div>
      </template>
    </el-drawer>

    <!-- create order dialog -->
    <el-dialog
      v-model="createDialogVisible"
      title="创建订单"
      width="640px"
      @close="createDialogVisible = false"
    >
      <el-form label-width="100px">
        <el-form-item label="客户">
          <el-select
            v-model="createForm.contactId"
            filterable
            remote
            placeholder="搜索客户"
            style="width: 100%"
            @change="handleContactChange"
          >
            <el-option
              v-for="c in contacts"
              :key="c.id"
              :label="c.name || c.id"
              :value="c.id"
            >
              <div class="contact-option">
                <span>{{ c.name || c.id }}</span>
                <span>{{ c.phone || '无电话' }} · {{ c.address || '无地址' }}</span>
              </div>
            </el-option>
          </el-select>
        </el-form-item>

        <el-form-item label="商品">
          <div class="order-items-editor">
            <div class="order-items-head">
              <span>商品</span>
              <span>数量</span>
              <span>小计</span>
              <span>操作</span>
            </div>
            <div v-for="(item, idx) in createForm.items" :key="idx" class="order-item-row">
              <div class="product-cell">
                <el-select
                  v-model="item.productName"
                  filterable
                  allow-create
                  default-first-option
                  placeholder="选择或输入商品名"
                  class="product-select"
                >
                  <el-option
                    v-for="p in products"
                    :key="p.id"
                    :label="`${p.name} (${formatCurrency(p.price)})`"
                    :value="p.name"
                  >
                    <div class="product-option">
                      <span>{{ p.name }}</span>
                      <span>{{ formatCurrency(p.price) }} · 库存 {{ p.stock }}</span>
                    </div>
                  </el-option>
                </el-select>
                <div v-if="getSelectedProduct(item.productName)" class="product-meta">
                  单价 {{ formatCurrency(getSelectedProduct(item.productName)?.price) }}
                  <span>库存 {{ getSelectedProduct(item.productName)?.stock }}</span>
                </div>
              </div>
              <el-input-number
                v-model="item.quantity"
                :min="1"
                :max="999"
                controls-position="right"
                class="quantity-input"
              />
              <div class="subtotal-cell">{{ formatCurrency(getItemSubtotal(item)) }}</div>
              <el-button
                :icon="Delete"
                :disabled="createForm.items.length <= 1"
                circle
                plain
                @click="removeItemRow(idx)"
              />
            </div>
            <el-button size="small" :icon="Plus" @click="addItemRow">
              添加商品
            </el-button>
          </div>
        </el-form-item>

        <el-form-item label="收货人">
          <el-input v-model="createForm.receiverName" placeholder="收货人姓名" />
        </el-form-item>
        <el-form-item label="联系电话">
          <el-input v-model="createForm.receiverPhone" placeholder="联系电话" />
        </el-form-item>
        <el-form-item label="收货地址">
          <el-input v-model="createForm.shippingAddress" type="textarea" placeholder="收货地址" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="createForm.remark" type="textarea" placeholder="备注" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.order-list-page {
  padding: 20px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-header h2 {
  margin: 0;
  font-size: 20px;
}
.status-filter {
  margin-bottom: 16px;
}
.order-id {
  font-family: monospace;
  font-size: 13px;
  color: var(--el-color-primary);
}
.pagination-wrap {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}
.order-items-editor {
  width: 100%;
  min-width: 0;
}

.order-items-head,
.order-item-row {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 110px 92px 44px;
  gap: 10px;
  align-items: start;
}

.order-items-head {
  margin-bottom: 6px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 20px;
}

.order-item-row {
  margin-bottom: 10px;
}

.product-cell {
  min-width: 0;
}

.product-select,
.quantity-input {
  width: 100%;
}

.product-meta {
  display: flex;
  gap: 10px;
  margin-top: 4px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 18px;
}

.product-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.product-option span:last-child {
  color: var(--text-muted);
  font-size: 12px;
}

.contact-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.contact-option span:first-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.contact-option span:last-child {
  flex: 0 1 auto;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-muted);
  font-size: 12px;
}

.subtotal-cell {
  min-height: 32px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  color: var(--text-strong);
  font-weight: 600;
  white-space: nowrap;
}
.drawer-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
