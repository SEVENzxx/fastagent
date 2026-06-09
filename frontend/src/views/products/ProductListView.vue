<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as productsApi from '@/api/products'
import * as categoriesApi from '@/api/categories'
import * as knowledgeApi from '@/api/knowledge'
import type { ProductCreate, ProductResponse, ProductUpdate } from '@/api/products'
import type { CategoryTreeResponse } from '@/api/categories'
import ProductCard from '@/components/products/ProductCard.vue'
import ProductFormDialog from '@/components/products/ProductFormDialog.vue'
import ProductImportDialog from '@/components/products/ProductImportDialog.vue'
import ProductKnowledgeDialog from '@/components/products/ProductKnowledgeDialog.vue'

const products = ref<ProductResponse[]>([])
const loading = ref(true)
const total = ref(0)
const page = ref(1)
const pageSize = ref(12)

const categories = ref<CategoryTreeResponse[]>([])
const keyword = ref('')
const filterCategoryId = ref<string | null>(null)

const dialogVisible = ref(false)
const importDialogVisible = ref(false)
const editingProduct = ref<ProductResponse | null>(null)

const knowledgeDialogVisible = ref(false)
const knowledgeProduct = ref<ProductResponse | null>(null)
const knowledgeProductIds = ref<Set<string>>(new Set())

async function loadDocStates() {
  // 批量检查当前页商品哪些有关联知识文档
  const ids = products.value.map((p) => p.id)
  if (ids.length === 0) return
  try {
    // 用全量拉取（limit=200）覆盖当前页面所有商品 id，不完美但够用
    const result = await knowledgeApi.listKnowledgeDocs(0, 200)
    const idSet = new Set<string>()
    for (const doc of result.items) {
      if (doc.productId && ids.includes(doc.productId)) {
        idSet.add(doc.productId)
      }
    }
    knowledgeProductIds.value = idSet
  } catch {
    /* ignore */
  }
}

function hasDoc(productId: string): boolean {
  return knowledgeProductIds.value.has(productId)
}

function openKnowledge(product: ProductResponse) {
  knowledgeProduct.value = product
  knowledgeDialogVisible.value = true
}

function onKnowledgeUploaded() {
  // 上传成功后刷新文档状态
  loadDocStates()
}

async function loadCategories() {
  try {
    categories.value = await categoriesApi.getCategoryTree()
  } catch {
    /* ignore */
  }
}

// 级联选择器配置——展示完整分类层级路径（如"电子产品 / 手机"）
const cascaderProps = {
  value: 'id',
  label: 'name',
  children: 'children',
  expandTrigger: 'hover' as const,
  checkStrictly: true,
  emitPath: false,
}

async function loadData() {
  loading.value = true
  try {
    const params: productsApi.ProductSearchParams = {
      keyword: keyword.value || undefined,
      categoryId: filterCategoryId.value || undefined,
      page: page.value,
      pageSize: pageSize.value,
    }
    const result = await productsApi.searchProducts(params)
    products.value = result.items
    total.value = result.total
    await loadDocStates()
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  loadData()
}

function onPageChange(newPage: number) {
  page.value = newPage
  loadData()
}

function openCreate() {
  editingProduct.value = null
  dialogVisible.value = true
}

function openImport() {
  importDialogVisible.value = true
}

function openEdit(product: ProductResponse) {
  editingProduct.value = product
  dialogVisible.value = true
}

async function handleDelete(product: ProductResponse) {
  try {
    await ElMessageBox.confirm(`确定删除商品「${product.name}」吗？`, '确认删除', {
      type: 'warning',
    })
    await productsApi.deleteProduct(product.id)
    ElMessage.success('商品已删除')
    await loadData()
  } catch {
    /* cancelled */
  }
}

async function handleSubmit(data: ProductCreate | ProductUpdate) {
  try {
    if (editingProduct.value) {
      await productsApi.updateProduct(editingProduct.value.id, data as ProductUpdate)
      ElMessage.success('商品已更新')
    } else {
      await productsApi.createProduct(data as ProductCreate)
      ElMessage.success('商品已创建')
    }
    dialogVisible.value = false
    await loadData()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '商品保存失败')
  }
}

onMounted(() => {
  loadCategories()
  loadData()
})
</script>

<template>
  <div class="page">
    <section class="page-header">
      <div>
        <p>商品目录</p>
        <h2>商品管理</h2>
      </div>
      <div class="header-actions">
        <el-button @click="openImport">批量导入</el-button>
        <el-button type="primary" @click="openCreate">新增商品</el-button>
      </div>
    </section>

    <!-- Search & Filter Bar -->
    <section class="filter-bar">
      <el-input
        v-model="keyword"
        placeholder="搜索商品名称 / SKU / 描述..."
        clearable
        @keyup.enter="onSearch"
        @clear="onSearch"
        style="width: 320px"
      >
        <template #prefix>
          <span style="color: var(--text-muted)">🔍</span>
        </template>
      </el-input>
      <el-cascader
        v-model="filterCategoryId"
        :options="categories"
        :props="cascaderProps"
        placeholder="全部分类"
        clearable
        @change="onSearch"
        style="width: 220px"
      />
      <el-button @click="onSearch">搜索</el-button>
    </section>

    <!-- Product Grid -->
    <section class="product-grid-section">
      <el-skeleton :loading="loading" animated :count="6">
        <template #default>
          <div v-if="products.length" class="product-grid">
            <ProductCard
              v-for="product in products"
              :key="product.id"
              :product="product"
              :has-doc="hasDoc(product.id)"
              @edit="openEdit"
              @delete="handleDelete"
              @manage-knowledge="openKnowledge"
            />
          </div>
          <el-empty v-else description="暂无商品" />
        </template>
      </el-skeleton>

      <el-pagination
        v-if="total > pageSize"
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="prev, pager, next"
        background
        class="pagination"
        @current-change="onPageChange"
      />
    </section>

    <ProductFormDialog
      v-model:visible="dialogVisible"
      :product="editingProduct"
      :categories="categories"
      @submit="handleSubmit"
    />

    <ProductImportDialog
      v-model:visible="importDialogVisible"
      @imported="loadData"
    />

    <ProductKnowledgeDialog
      v-model:visible="knowledgeDialogVisible"
      :product="knowledgeProduct"
      @uploaded="onKnowledgeUploaded"
    />
  </div>
</template>

<style scoped>
.page {
  display: grid;
  gap: 18px;
}

.page-header {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
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

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.product-grid-section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
}

.product-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}

.pagination {
  margin-top: 20px;
  justify-content: center;
}
</style>
