<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { TreeInstance } from 'element-plus'
import type { PermissionGroupedResponse, RoleDetailResponse } from '@/api/roles'

interface PermissionTreeNode {
  id: string
  label: string
  description?: string | null
  children?: PermissionTreeNode[]
}

const props = defineProps<{
  visible: boolean
  role?: RoleDetailResponse | null
  permissionGroups: PermissionGroupedResponse[]
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  submit: [data: { name: string; description: string | null; permissionIds: string[] }]
}>()

const form = ref({
  name: '',
  description: '',
})
const treeRef = ref<TreeInstance>()
const checkedPermissions = ref<string[]>([])
const submitting = ref(false)
const treeRenderKey = ref(0)

const isEdit = () => !!props.role
const treeProps = {
  children: 'children',
  label: 'label',
}

const permissionTree = computed<PermissionTreeNode[]>(() => {
  return props.permissionGroups.map((group) => ({
    id: `module:${group.module}`,
    label: group.module,
    children: group.permissions.map((permission) => ({
      id: permission.id,
      label: permission.name,
      description: permission.description,
    })),
  }))
})

const expandedKeys = computed(() => permissionTree.value.map((group) => group.id))

async function syncTreeCheckedKeys() {
  await nextTick()
  treeRef.value?.setCheckedKeys(checkedPermissions.value, false)
}

function resetFormState() {
  if (props.role) {
    form.value.name = props.role.name
    form.value.description = props.role.description || ''
    checkedPermissions.value = props.role.permissions.map((permission) => permission.id)
    return
  }

  form.value.name = ''
  form.value.description = ''
  checkedPermissions.value = []
}

watch(
  () => props.visible,
  async (visible) => {
    if (!visible) return

    resetFormState()
    treeRenderKey.value += 1
    await syncTreeCheckedKeys()
  },
)

watch(
  () => props.permissionGroups,
  async () => {
    if (props.visible) {
      await syncTreeCheckedKeys()
    }
  },
  { deep: true },
)

function handleClose() {
  emit('update:visible', false)
}

function handleClosed() {
  form.value.name = ''
  form.value.description = ''
  checkedPermissions.value = []
  treeRef.value?.setCheckedKeys([], false)
  treeRenderKey.value += 1
}

function handleTreeCheck() {
  const keys = treeRef.value?.getCheckedKeys(true) ?? []
  checkedPermissions.value = keys
    .filter((key): key is string => typeof key === 'string')
    .filter((key) => !key.startsWith('module:'))
}

async function handleSubmit() {
  if (!form.value.name.trim()) return
  submitting.value = true
  try {
    emit('submit', {
      name: form.value.name.trim(),
      description: form.value.description || null,
      permissionIds: checkedPermissions.value,
    })
    emit('update:visible', false)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="isEdit() ? '编辑角色' : '新建角色'"
    width="680px"
    destroy-on-close
    @update:model-value="emit('update:visible', $event)"
    @closed="handleClosed"
  >
    <el-form label-position="top">
      <el-form-item label="角色名称" required>
        <el-input v-model="form.name" placeholder="如：客服坐席" maxlength="50" />
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="form.description" type="textarea" placeholder="角色职责说明" :rows="3" />
      </el-form-item>
      <el-form-item label="权限">
        <div class="permission-tree-wrap">
          <el-tree
            :key="treeRenderKey"
            ref="treeRef"
            class="permission-tree"
            :data="permissionTree"
            :props="treeProps"
            node-key="id"
            show-checkbox
            :default-expanded-keys="expandedKeys"
            :default-checked-keys="checkedPermissions"
            @check="handleTreeCheck"
          >
            <template #default="{ node, data }">
              <span class="tree-node">
                <span>{{ node.label }}</span>
                <small v-if="data.description">{{ data.description }}</small>
              </span>
            </template>
          </el-tree>
        </div>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="handleClose">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">
        {{ isEdit() ? '保存' : '创建' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.permission-tree-wrap {
  width: 100%;
  max-height: 360px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-soft);
}

.permission-tree {
  padding: 8px 10px;
  background: transparent;
}

.permission-tree :deep(.el-tree-node__content) {
  min-height: 34px;
  border-radius: 6px;
}

.permission-tree :deep(.el-tree-node__content:hover) {
  background: #eef4ff;
}

.tree-node {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.tree-node span {
  color: var(--text-strong);
  font-weight: 500;
}

.tree-node small {
  overflow: hidden;
  color: var(--text-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
