<template>
  <div class="workflows-view page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">工作流</h2>
        <p class="page-desc">基于拓扑图的确定性流程引擎，支持 LLM 节点、工具节点、条件分支和并行执行</p>
      </div>
      <el-button :icon="Refresh" @click="loadWorkflows" :loading="loading" text>刷新</el-button>
    </div>

    <div class="workflows-layout">
      <!-- 左侧：工作流列表 -->
      <div class="workflow-list-panel">
        <div class="panel-header">
          <span class="panel-label">可用工作流</span>
        </div>

        <div v-if="loading" class="list-loading">
          <div v-for="i in 2" :key="i" class="skeleton" style="height:100px;border-radius:10px;margin-bottom:10px;"></div>
        </div>

        <div v-else class="workflow-list">
          <div
            v-for="workflow in workflows"
            :key="workflow.workflow_id"
            class="workflow-item card-base"
            :class="{ selected: selectedWorkflow?.workflow_id === workflow.workflow_id }"
            @click="selectWorkflow(workflow)"
          >
            <div class="workflow-item-header">
              <div class="workflow-icon">
                <el-icon :size="18" style="color:white"><Connection /></el-icon>
              </div>
              <div class="workflow-meta">
                <span class="workflow-name">{{ workflow.name }}</span>
                <span class="workflow-id">{{ workflow.workflow_id }}</span>
              </div>
            </div>
            <p class="workflow-desc">{{ workflow.description }}</p>
            <div class="workflow-stats">
              <span class="wf-stat"><el-icon :size="12"><Grid /></el-icon> {{ workflow.node_count }} 个节点</span>
              <span class="wf-stat">入口：{{ workflow.entry_node }}</span>
            </div>
          </div>

          <div v-if="workflows.length === 0" class="empty-panel">
            <el-icon :size="32" style="color:var(--color-text-muted)"><Connection /></el-icon>
            <p>暂无可用工作流</p>
          </div>
        </div>
      </div>

      <!-- 右侧：执行面板 -->
      <div class="wf-execution-panel">
        <div v-if="!selectedWorkflow" class="no-selection">
          <el-icon :size="48" style="color:var(--color-border)"><Connection /></el-icon>
          <p class="no-selection-text">请从左侧选择一个工作流</p>
          <p class="no-selection-hint">选择后可以配置输入数据并执行</p>
        </div>

        <template v-else>
          <!-- 工作流使用说明 -->
          <el-alert
            title="工作流使用说明"
            type="info"
            show-icon
            :closable="false"
            style="margin-bottom: 2px;"
          >
            <p style="margin: 4px 0 0 0; line-height: 1.5; font-size: 0.8rem;">
              工作流（Workflow）是由预定义节点组成的确定性有向无环图。您只需要提供<strong>入口节点所需的初始变量（键值对）</strong>，引擎会自动按拓扑顺序调度大模型进行逻辑处理。<br/>
              <strong>操作指南：</strong>在下方配置对应的变量名和变量值，点击执行即可观测工作流的运转。
            </p>
          </el-alert>
          <!-- 工作流图示（简化流程图） -->
          <div class="wf-diagram card-base">
            <div class="wf-diagram-header">
              <el-icon :size="16" style="color:var(--color-primary)"><Connection /></el-icon>
              <span>{{ selectedWorkflow.name }} · 拓扑结构</span>
            </div>
            <div class="wf-flow">
              <div class="flow-node entry-node">
                <span>{{ selectedWorkflow.entry_node }}</span>
                <small>入口节点</small>
              </div>
              <div class="flow-arrow">→</div>
              <div class="flow-node process-node">
                <span>处理中...</span>
                <small>{{ selectedWorkflow.node_count - selectedWorkflow.exit_nodes.length - 1 }} 个中间节点</small>
              </div>
              <div class="flow-arrow">→</div>
              <div class="exit-nodes">
                <div
                  v-for="exit in selectedWorkflow.exit_nodes"
                  :key="exit"
                  class="flow-node exit-node"
                >
                  <span>{{ exit }}</span>
                  <small>出口节点</small>
                </div>
              </div>
            </div>
          </div>

          <!-- 输入参数配置 -->
          <div class="wf-input-section">
            <div class="section-header" style="justify-content: space-between; width: 100%;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <span class="section-label">工作流输入数据</span>
                <el-tooltip content="输入为 JSON 格式，键值对作为工作流的初始输入变量" placement="top">
                  <el-icon style="color:var(--color-text-muted);cursor:help"><InfoFilled /></el-icon>
                </el-tooltip>
              </div>
              
              <div class="quick-examples" v-if="selectedWorkflow.workflow_id === 'intent_routing'">
                <span class="example-tag" @click="fillIntentExample">示例：售后退货</span>
              </div>
            </div>
            <div class="input-fields">
              <div v-for="(val, key) in inputData" :key="key" class="input-field-row">
                <el-input
                  :model-value="key"
                  placeholder="变量名"
                  size="small"
                  style="width:140px"
                  readonly
                />
                <el-input
                  v-model="inputData[key]"
                  placeholder="变量值"
                  size="small"
                  style="flex:1"
                />
                <el-button size="small" type="danger" text :icon="Delete" @click="removeInputField(key)" />
              </div>
              <div class="add-field-row">
                <el-input v-model="newFieldKey" placeholder="变量名" size="small" style="width:140px" />
                <el-input v-model="newFieldValue" placeholder="变量值" size="small" style="flex:1" />
                <el-button size="small" type="primary" plain @click="addInputField">添加</el-button>
              </div>
            </div>

            <el-button
              type="primary"
              size="large"
              :loading="executing"
              :disabled="Object.keys(inputData).length === 0"
              :icon="CaretRight"
              @click="handleExecute"
              style="margin-top:16px;width:100%"
            >
              {{ executing ? '工作流执行中...' : '执行工作流' }}
            </el-button>
          </div>

          <!-- 执行结果 -->
          <div v-if="executeResult" class="wf-result-section">
            <div class="result-header-row">
              <span class="result-label">执行结果</span>
              <el-tag :type="executeResult.success ? 'success' : 'danger'" size="small">
                {{ executeResult.success ? '执行成功' : '执行失败' }}
              </el-tag>
            </div>
            <div class="result-box card-base">
              <MarkdownRenderer :content="formatWorkflowResult(executeResult.result)" />
            </div>
          </div>

          <div v-if="executeError" class="wf-error">
            <el-alert :title="executeError" type="error" show-icon :closable="false" />
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Connection, Refresh, CaretRight, Delete, InfoFilled, Grid } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getWorkflowList, executeWorkflow } from '@/api/modules/workflows'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import type { WorkflowInfo, WorkflowExecuteResponse } from '@/types/agent'

const workflows = ref<WorkflowInfo[]>([])
const loading = ref<boolean>(false)
const selectedWorkflow = ref<WorkflowInfo | null>(null)
const executing = ref<boolean>(false)
const executeResult = ref<WorkflowExecuteResponse | null>(null)
const executeError = ref<string>('')

// 输入字段管理
const inputData = ref<Record<string, string>>({})
const newFieldKey = ref<string>('')
const newFieldValue = ref<string>('')

/** 加载工作流列表 */
async function loadWorkflows(): Promise<void> {
  loading.value = true
  try {
    workflows.value = await getWorkflowList()
    console.log('[WorkflowsView] 已加载工作流列表，数量:', workflows.value.length)
  } catch (error) {
    console.error('[WorkflowsView] 加载工作流列表失败:', error)
    ElMessage.error('加载工作流列表失败')
  } finally {
    loading.value = false
  }
}

/** 选择工作流，预置默认输入字段 */
function selectWorkflow(workflow: WorkflowInfo): void {
  selectedWorkflow.value = workflow
  executeResult.value = null
  executeError.value = ''

  // 根据已知工作流 ID 预置输入字段
  if (workflow.workflow_id === 'intent_routing') {
    inputData.value = { user_query: '' }
  } else {
    inputData.value = {}
  }

  newFieldKey.value = ''
  newFieldValue.value = ''
  console.log('[WorkflowsView] 已选择工作流:', workflow.workflow_id)
}

/** 添加输入字段 */
function addInputField(): void {
  if (!newFieldKey.value.trim()) {
    ElMessage.warning('变量名不能为空')
    return
  }
  inputData.value[newFieldKey.value.trim()] = newFieldValue.value
  newFieldKey.value = ''
  newFieldValue.value = ''
}

/** 填充意图路由示例数据 */
function fillIntentExample(): void {
  inputData.value = { user_query: '我买的衣服破损了，麻烦帮我处理下退货退款，订单号是 12345688' }
}

/** 删除输入字段 */
function removeInputField(key: string): void {
  delete inputData.value[key]
}

/** 执行工作流 */
async function handleExecute(): Promise<void> {
  if (!selectedWorkflow.value) return

  // 过滤空值
  const filteredInput: Record<string, string> = {}
  Object.entries(inputData.value).forEach(([k, v]) => {
    filteredInput[k] = v
  })

  executing.value = true
  executeResult.value = null
  executeError.value = ''

  try {
    const result = await executeWorkflow(selectedWorkflow.value.workflow_id, {
      input_data: filteredInput,
    })
    executeResult.value = result
    ElMessage.success('工作流执行完成！')
    console.log('[WorkflowsView] 工作流执行成功')
  } catch (error) {
    executeError.value = error instanceof Error ? error.message : '执行失败'
    console.error('[WorkflowsView] 工作流执行失败:', error)
  } finally {
    executing.value = false
  }
}

/** 格式化工作流执行结果为 Markdown */
function formatWorkflowResult(result: Record<string, unknown>): string {
  if (result.content) return String(result.content)
  if (result.message) return String(result.message)
  if (result.output) return String(result.output)
  return '```json\n' + JSON.stringify(result, null, 2) + '\n```'
}

onMounted(() => { loadWorkflows() })
</script>

<style scoped>
.workflows-view { height: 100%; display: flex; flex-direction: column; overflow: hidden; }

.workflows-layout {
  flex: 1;
  display: flex;
  gap: 0;
  overflow: hidden;
}

/* 左侧工作流列表 */
.workflow-list-panel {
  width: 280px;
  min-width: 280px;
  border-right: 1px solid var(--color-border);
  background: var(--color-bg-primary);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  padding: 14px 16px;
  border-bottom: 1px solid var(--color-border-light);
}

.panel-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.list-loading, .workflow-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.workflow-item {
  padding: 14px;
  margin-bottom: 10px;
  cursor: pointer;
  transition: all var(--transition-fast);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.workflow-item:hover, .workflow-item.selected {
  box-shadow: var(--shadow-md);
  border-color: var(--color-primary);
}

.workflow-item.selected {
  background: var(--color-primary-lighter);
}

.workflow-item-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.workflow-icon {
  width: 34px;
  height: 34px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, #f59e0b, #d97706);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.workflow-name {
  display: block;
  font-weight: 600;
  font-size: 0.875rem;
  color: var(--color-text-primary);
}

.workflow-id {
  display: block;
  font-size: 0.7rem;
  color: var(--color-text-muted);
  font-family: var(--font-mono);
}

.workflow-desc {
  font-size: 0.78rem;
  color: var(--color-text-secondary);
  line-height: 1.5;
}

.workflow-stats {
  display: flex;
  gap: 10px;
}

.wf-stat {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.7rem;
  color: var(--color-text-muted);
}

.empty-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 16px;
  gap: 8px;
  color: var(--color-text-muted);
  font-size: 0.85rem;
}

/* 右侧执行面板 */
.wf-execution-panel {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.no-selection {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.no-selection-text { font-size: 1rem; font-weight: 500; color: var(--color-text-secondary); }
.no-selection-hint { font-size: 0.8rem; color: var(--color-text-muted); }

/* 工作流拓扑图示 */
.wf-diagram {
  padding: 16px 20px;
}

.wf-diagram-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 16px;
}

.wf-flow {
  display: flex;
  align-items: center;
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.flow-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 8px 16px;
  border-radius: var(--radius-md);
  border: 1px solid;
  min-width: 100px;
  text-align: center;
  flex-shrink: 0;
}

.flow-node span { font-size: 0.78rem; font-weight: 600; font-family: var(--font-mono); }
.flow-node small { font-size: 0.65rem; color: var(--color-text-muted); }

.entry-node {
  border-color: var(--color-primary);
  background: var(--color-primary-lighter);
}

.entry-node span { color: var(--color-primary); }

.process-node {
  border-color: var(--color-border);
  background: var(--color-bg-secondary);
}

.exit-node {
  border-color: var(--color-success);
  background: #d1fae5;
  margin-bottom: 8px;
}

.exit-node span { color: var(--color-success); }

.exit-nodes {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.flow-arrow {
  font-size: 1.2rem;
  color: var(--color-text-muted);
  flex-shrink: 0;
}

/* 输入配置区 */
.wf-input-section { display: flex; flex-direction: column; gap: 12px; }

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--color-text-primary);
}

.input-fields { display: flex; flex-direction: column; gap: 8px; }

.input-field-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.add-field-row {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 8px;
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
  border: 1px dashed var(--color-border);
}

/* 结果展示 */
.wf-result-section { display: flex; flex-direction: column; gap: 12px; }
.result-header-row { display: flex; align-items: center; gap: 10px; }
.result-label { font-weight: 600; font-size: 0.875rem; color: var(--color-text-primary); }
.result-box { padding: 16px; max-height: 400px; overflow-y: auto; }

.quick-examples {
  display: flex;
  gap: 8px;
}
.example-tag {
  font-size: 0.7rem;
  padding: 2px 8px;
  background: var(--color-bg-secondary);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--color-primary);
  transition: all 0.2s;
}
.example-tag:hover {
  background: var(--color-primary-lighter);
}
</style>
