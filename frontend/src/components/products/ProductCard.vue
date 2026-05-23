<script setup lang="ts">
import type { ProductResponse } from '@/api/products'

const props = defineProps<{
  product: ProductResponse
}>()

const emit = defineEmits<{
  edit: [product: ProductResponse]
  delete: [product: ProductResponse]
}>()

function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `¥${value.toFixed(2)}`
}

function statusText(active: boolean): string {
  return active ? '上架' : '下架'
}

function statusType(active: boolean): 'success' | 'info' {
  return active ? 'success' : 'info'
}
</script>

<template>
  <div class="product-card">
    <div class="card-body" @click="emit('edit', product)">
      <div class="card-header">
        <h3 class="card-name">{{ product.name }}</h3>
        <el-tag :type="statusType(product.isActive)" size="small" effect="light">
          {{ statusText(product.isActive) }}
        </el-tag>
      </div>

      <div class="card-sku" v-if="product.sku">
        <span class="label">SKU</span>
        <code>{{ product.sku }}</code>
      </div>

      <div class="card-category" v-if="product.categoryName">
        <span class="label">分类</span>
        <el-tag size="small" type="info" effect="plain">{{ product.categoryName }}</el-tag>
      </div>

      <div class="card-desc" v-if="product.description">
        {{ product.description }}
      </div>

      <div class="card-specs" v-if="product.specs">
        <span
          v-for="(val, key) in product.specs"
          :key="key"
          class="spec-tag"
        >
          {{ key }}: {{ val }}
        </span>
      </div>

      <div class="card-footer">
        <span class="price">{{ formatPrice(product.price) }}</span>
        <span class="stock">库存 {{ product.stock }}</span>
      </div>
    </div>

    <div class="card-actions">
      <el-button size="small" @click="emit('edit', product)">编辑</el-button>
      <el-button size="small" type="danger" plain @click="emit('delete', product)">删除</el-button>
    </div>
  </div>
</template>

<style scoped>
.product-card {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  overflow: hidden;
  transition: box-shadow 0.15s;
}

.product-card:hover {
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.card-body {
  padding: 16px;
  cursor: pointer;
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.card-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.card-sku,
.card-category {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 12px;
}

.card-sku code {
  color: var(--text-muted);
  background: var(--surface-soft);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
}

.label {
  color: var(--text-muted);
  font-weight: 500;
}

.card-desc {
  color: var(--text);
  font-size: 13px;
  line-height: 1.5;
  margin: 8px 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-specs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 0;
}

.spec-tag {
  display: inline-block;
  padding: 2px 8px;
  font-size: 11px;
  color: var(--text-muted);
  background: var(--surface-soft);
  border-radius: 4px;
}

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
}

.price {
  font-size: 20px;
  font-weight: 700;
  color: var(--primary);
}

.stock {
  font-size: 12px;
  color: var(--text-muted);
}

.card-actions {
  display: flex;
  gap: 4px;
  padding: 0 16px 14px;
}
</style>
