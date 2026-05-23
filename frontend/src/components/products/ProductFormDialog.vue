<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { reactive, ref, watch } from 'vue'
import type { ProductResponse, ProductCreate, ProductUpdate } from '@/api/products'
import type { CategoryTreeResponse } from '@/api/categories'

const props = defineProps<{
  visible: boolean
  product?: ProductResponse | null
  categories?: CategoryTreeResponse[]
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  submit: [data: ProductCreate | ProductUpdate]
}>()

const formRef = ref()
const submitting = ref(false)

const form = reactive({
  name: '',
  categoryId: null as string | null,
  sku: '',
  description: '',
  price: null as number | null,
  floorPrice: null as number | null,
  stock: 0,
  isSample: false,
  specsText: '',
  isActive: true,
})

const rules = {
  name: [
    { required: true, message: '请输入商品名称', trigger: 'blur' },
    { max: 300, message: '商品名称不能超过300个字符', trigger: 'blur' },
  ],
  price: [{ type: 'number', min: 0, message: '价格不能为负数', trigger: 'blur' }],
  floorPrice: [{ type: 'number', min: 0, message: '底价不能为负数', trigger: 'blur' }],
}

const categoryTreeProps = {
  value: 'id',
  label: 'name',
  children: 'children',
}

watch(
  () => props.visible,
  (visible) => {
    if (!visible) return
    if (props.product) {
      const p = props.product
      form.name = p.name
      form.categoryId = p.categoryId
      form.sku = p.sku ?? ''
      form.description = p.description ?? ''
      form.price = p.price
      form.floorPrice = p.floorPrice
      form.stock = p.stock
      form.isSample = p.isSample
      form.isActive = p.isActive
      form.specsText = p.specs ? JSON.stringify(p.specs, null, 2) : ''
    } else {
      form.name = ''
      form.categoryId = null
      form.sku = ''
      form.description = ''
      form.price = null
      form.floorPrice = null
      form.stock = 0
      form.isSample = false
      form.isActive = true
      form.specsText = ''
    }
  },
)

async function handleSubmit() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }

  let specs: Record<string, any> | null = null
  if (form.specsText.trim()) {
    try {
      specs = JSON.parse(form.specsText)
    } catch {
      ElMessage.warning('规格 JSON 格式不正确')
      return
    }
  }

  submitting.value = true
  emit('submit', {
    name: form.name.trim(),
    categoryId: form.categoryId || undefined,
    sku: form.sku.trim() || undefined,
    description: form.description.trim() || undefined,
    price: form.price,
    floorPrice: form.floorPrice,
    stock: form.stock,
    isSample: form.isSample,
    isActive: form.isActive,
    specs: specs || undefined,
  })
  submitting.value = false
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="product ? '编辑商品' : '新增商品'"
    width="640px"
    destroy-on-close
    @update:model-value="emit('update:visible', $event)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-row :gutter="16">
        <el-col :span="16">
          <el-form-item label="商品名称" prop="name" required>
            <el-input v-model="form.name" maxlength="300" placeholder="请输入商品名称" />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="SKU">
            <el-input v-model="form.sku" maxlength="100" placeholder="SKU编码" />
          </el-form-item>
        </el-col>
      </el-row>

      <el-form-item label="所属分类">
        <el-tree-select
          v-model="form.categoryId"
          :data="categories"
          :props="categoryTreeProps"
          placeholder="选择分类"
          clearable
          check-strictly
          default-expand-all
          style="width: 100%"
        />
      </el-form-item>

      <el-row :gutter="16">
        <el-col :span="8">
          <el-form-item label="售价" prop="price">
            <el-input-number
              v-model="form.price"
              :min="0"
              :precision="2"
              :controls="false"
              style="width: 100%"
            />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="底价" prop="floorPrice">
            <el-input-number
              v-model="form.floorPrice"
              :min="0"
              :precision="2"
              :controls="false"
              style="width: 100%"
            />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="库存">
            <el-input-number
              v-model="form.stock"
              :min="0"
              :step="1"
              :controls="true"
              style="width: 100%"
            />
          </el-form-item>
        </el-col>
      </el-row>

      <el-form-item label="商品描述">
        <el-input
          v-model="form.description"
          type="textarea"
          :rows="3"
          maxlength="5000"
          show-word-limit
          placeholder="商品描述..."
        />
      </el-form-item>

      <el-form-item label="规格 (JSON)">
        <el-input
          v-model="form.specsText"
          type="textarea"
          :rows="3"
          placeholder='{"规格": "500g", "产地": "杭州"}'
        />
      </el-form-item>

      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="状态">
            <el-switch v-model="form.isActive" active-text="上架" inactive-text="下架" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="是否样品">
            <el-switch v-model="form.isSample" active-text="是" inactive-text="否" />
          </el-form-item>
        </el-col>
      </el-row>
    </el-form>

    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
    </template>
  </el-dialog>
</template>
