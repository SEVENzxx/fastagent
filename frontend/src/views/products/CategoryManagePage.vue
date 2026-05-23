<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as categoriesApi from '@/api/categories'
import type { CategoryTreeResponse } from '@/api/categories'

interface TreeNode {
  id: string
  label: string
  children?: TreeNode[]
  data: CategoryTreeResponse
}

const treeData = ref<TreeNode[]>([])
const loading = ref(true)

const dialogVisible = ref(false)
const editingNode = ref<TreeNode | null>(null)
const parentId = ref<string | null>(null)
const formName = ref('')
const formSortOrder = ref(0)
const submitting = ref(false)

// selected node
const selectedNode = ref<TreeNode | null>(null)

async function loadTree() {
  loading.value = true
  try {
    const tree = await categoriesApi.getCategoryTree()
    treeData.value = buildTreeNodes(tree)
  } finally {
    loading.value = false
  }
}

function buildTreeNodes(tree: CategoryTreeResponse[]): TreeNode[] {
  return tree.map((node) => ({
    id: node.id,
    label: node.name,
    data: node,
    children: node.children?.length ? buildTreeNodes(node.children) : [],
  }))
}

function handleNodeClick(data: TreeNode) {
  selectedNode.value = data
}

function openCreate(parentNode?: TreeNode) {
  editingNode.value = null
  parentId.value = parentNode?.id ?? null
  formName.value = ''
  formSortOrder.value = 0
  dialogVisible.value = true
}

function openEdit(node: TreeNode) {
  editingNode.value = node
  parentId.value = node.data.parentId
  formName.value = node.data.name
  formSortOrder.value = node.data.sortOrder ?? 0
  dialogVisible.value = true
}

async function handleDelete(node: TreeNode) {
  try {
    await ElMessageBox.confirm(
      `确定删除分类「${node.data.name}」吗？其下所有子分类将被一并删除。`,
      '确认删除',
      { type: 'warning' },
    )
    await categoriesApi.deleteCategory(node.id)
    ElMessage.success('分类已删除')
    if (selectedNode.value?.id === node.id) {
      selectedNode.value = null
    }
    await loadTree()
  } catch {
    /* cancelled */
  }
}

async function handleSubmit() {
  if (!formName.value.trim()) {
    ElMessage.warning('请输入分类名称')
    return
  }
  submitting.value = true
  try {
    if (editingNode.value) {
      await categoriesApi.updateCategory(editingNode.value.id, {
        name: formName.value.trim(),
        parentId: parentId.value || undefined,
        sortOrder: formSortOrder.value,
      })
      ElMessage.success('分类已更新')
    } else {
      await categoriesApi.createCategory({
        name: formName.value.trim(),
        parentId: parentId.value || undefined,
        sortOrder: formSortOrder.value,
      })
      ElMessage.success('分类已创建')
    }
    dialogVisible.value = false
    await loadTree()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '分类保存失败')
  } finally {
    submitting.value = false
  }
}

onMounted(loadTree)
</script>

<template>
  <div class="page">
    <section class="page-header">
      <div>
        <p>商品目录</p>
        <h2>分类管理</h2>
      </div>
      <el-button type="primary" @click="openCreate()">新增分类</el-button>
    </section>

    <section class="tree-panel">
      <div class="panel-left">
        <el-skeleton :loading="loading" animated :count="5">
          <el-tree
            :data="treeData"
            node-key="id"
            default-expand-all
            highlight-current
            @node-click="handleNodeClick"
          >
            <template #default="{ node, data }">
              <div class="tree-node-row">
                <span class="tree-label">{{ node.label }}</span>
                <span class="tree-actions">
                  <el-button
                    text
                    size="small"
                    @click.stop="openCreate(data)"
                    title="添加子分类"
                  >
                    +
                  </el-button>
                  <el-button
                    text
                    size="small"
                    @click.stop="openEdit(data)"
                    title="编辑"
                  >
                    编辑
                  </el-button>
                  <el-button
                    text
                    size="small"
                    type="danger"
                    @click.stop="handleDelete(data)"
                    title="删除"
                  >
                    删除
                  </el-button>
                </span>
              </div>
            </template>
          </el-tree>
        </el-skeleton>
      </div>
      <div class="panel-right">
        <template v-if="selectedNode">
          <h3>分类详情</h3>
          <dl>
            <dt>名称</dt>
            <dd>{{ selectedNode.data.name }}</dd>
            <dt>排序</dt>
            <dd>{{ selectedNode.data.sortOrder }}</dd>
            <dt>创建时间</dt>
            <dd>{{ new Date(selectedNode.data.createdAt).toLocaleString() }}</dd>
          </dl>
        </template>
        <el-empty v-else description="选择左侧分类查看详情" />
      </div>
    </section>

    <!-- Dialog -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingNode ? '编辑分类' : '新增分类'"
      width="480px"
      destroy-on-close
    >
      <el-form label-position="top">
        <el-form-item label="分类名称" required>
          <el-input v-model="formName" placeholder="请输入分类名称" maxlength="200" />
        </el-form-item>
        <el-form-item label="排序值">
          <el-input-number v-model="formSortOrder" :min="0" :max="9999" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          保存
        </el-button>
      </template>
    </el-dialog>
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

.tree-panel {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: 18px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  min-height: 400px;
}

.panel-left {
  border-right: 1px solid var(--border);
  padding-right: 20px;
}

.panel-right {
  padding-left: 4px;
}

.panel-right h3 {
  color: var(--text-strong);
  font-size: 16px;
  margin-bottom: 16px;
}

.panel-right dl {
  display: grid;
  gap: 12px;
}

.panel-right dt {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
}

.panel-right dd {
  color: var(--text);
  font-size: 14px;
}

.tree-node-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding-right: 4px;
}

.tree-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-actions {
  display: none;
  gap: 2px;
  margin-left: 8px;
}

.tree-node-row:hover .tree-actions,
:deep(.el-tree-node.is-current) .tree-actions {
  display: flex;
}

@media (max-width: 860px) {
  .tree-panel {
    grid-template-columns: 1fr;
  }
  .panel-left {
    border-right: 0;
    padding-right: 0;
    border-bottom: 1px solid var(--border);
    padding-bottom: 20px;
  }
}
</style>
