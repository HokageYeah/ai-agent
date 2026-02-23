<template>
  <div class="agents-view page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">Agent 执行</h2>
        <p class="page-desc">选择专家 Agent，输入任务后启动 Planning → Execution → Reflection 执行闭环</p>
      </div>
    </div>

    <div class="agents-layout">
      <!-- 左侧：Agent 列表 -->
      <div class="agent-list-panel">
        <div class="panel-header">
          <span class="panel-label">可用 Agent</span>
          <el-button size="small" :icon="Refresh" text @click="loadAgents" :loading="loadingAgents">刷新</el-button>
        </div>

        <!-- 加载状态 -->
        <div v-if="loadingAgents" class="list-loading">
          <div v-for="i in 3" :key="i" class="skeleton" style="height:80px;border-radius:10px;margin-bottom:10px;"></div>
        </div>

        <!-- Agent 卡片列表 -->
        <div v-else class="agent-cards">
          <div
            v-for="agent in agents"
            :key="agent.agent_id"
            class="agent-card card-base"
            :class="{ selected: selectedAgent?.agent_id === agent.agent_id }"
            @click="selectAgent(agent)"
          >
            <div class="agent-card-header">
              <div class="agent-avatar">
                <el-icon :size="20" style="color:white"><Setting /></el-icon>
              </div>
              <div class="agent-info">
                <span class="agent-name">{{ agent.name }}</span>
                <span class="agent-id">{{ agent.agent_id }}</span>
              </div>
            </div>
            <p class="agent-desc">{{ agent.description }}</p>
            <div class="agent-capabilities">
              <span v-for="cap in agent.capabilities.slice(0,3)" :key="cap" class="capability-tag">{{ cap }}</span>
              <span v-if="agent.capabilities.length > 3" class="capability-more">+{{ agent.capabilities.length - 3 }}</span>
            </div>
          </div>

          <div v-if="agents.length === 0" class="empty-panel">
            <el-icon :size="32" style="color:var(--color-text-muted)"><Setting /></el-icon>
            <p>暂无可用 Agent</p>
          </div>
        </div>
      </div>

      <!-- 右侧：执行面板 -->
      <div class="execution-panel">
        <!-- 未选择 Agent 时的占位 -->
        <div v-if="!selectedAgent" class="no-selection">
          <el-icon :size="48" style="color:var(--color-border)"><Setting /></el-icon>
          <p class="no-selection-text">请从左侧选择一个 Agent</p>
          <p class="no-selection-hint">选择后可以输入任务描述并执行</p>
        </div>

        <!-- 已选择 Agent：显示执行界面 -->
        <template v-else>
          <!-- Agent 详情头部 -->
          <div class="selected-agent-header">
            <div class="selected-agent-avatar">
              <el-icon :size="24" style="color:white"><Setting /></el-icon>
            </div>
            <div>
              <div class="selected-agent-name">{{ selectedAgent.name }}</div>
              <div class="selected-agent-desc">{{ selectedAgent.description }}</div>
            </div>
            <div class="selected-agent-meta">
              <span class="meta-item">工具: {{ selectedAgent.available_tools.length }}</span>
              <span class="meta-item">技能: {{ selectedAgent.available_skills.length }}</span>
            </div>
          </div>

          <!-- 任务输入 -->
          <div class="task-section">
            <label class="input-label">任务描述</label>
            <el-input
              v-model="taskInput"
              type="textarea"
              :autosize="{ minRows: 3, maxRows: 8 }"
              placeholder="描述你想要 Agent 完成的任务...&#10;例如：帮我算一下 100 * 365 并写一首庆祝的诗"
              :disabled="executing"
            />
            <el-button
              type="primary"
              size="large"
              :loading="executing"
              :disabled="!taskInput.trim()"
              :icon="CaretRight"
              @click="handleExecute"
              style="margin-top:12px;width:100%"
            >
              {{ executing ? 'Agent 执行中...' : '开始执行任务' }}
            </el-button>
          </div>

          <!-- 执行结果 -->
          <div v-if="executeResult" class="result-section">
            <div class="result-header">
              <span class="result-label">执行结果</span>
              <el-tag :type="executeResult.success ? 'success' : 'danger'" size="small">
                {{ executeResult.success ? '成功' : '失败' }}
              </el-tag>
              <span class="result-iterations">{{ executeResult.iterations }} 次迭代</span>
            </div>
            <div class="result-content card-base">
              <MarkdownRenderer :content="formatAgentResult(executeResult.result)" />
            </div>
          </div>

          <!-- 执行错误 -->
          <div v-if="executeError" class="error-section">
            <el-alert :title="executeError" type="error" show-icon :closable="false" />
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Setting, Refresh, CaretRight } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getAgentList, executeAgent } from '@/api/modules/agents'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import type { AgentInfo, AgentExecuteResponse } from '@/types/agent'

const agents = ref<AgentInfo[]>([])
const selectedAgent = ref<AgentInfo | null>(null)
const loadingAgents = ref<boolean>(false)
const taskInput = ref<string>('')
const executing = ref<boolean>(false)
const executeResult = ref<AgentExecuteResponse | null>(null)
const executeError = ref<string>('')

/**
 * 加载所有可用 Agent 列表
 */
async function loadAgents(): Promise<void> {
  loadingAgents.value = true
  executeResult.value = null
  executeError.value = ''
  try {
    agents.value = await getAgentList()
    console.log('[AgentView] 已加载 Agent 列表，数量:', agents.value.length)
  } catch (error) {
    console.error('[AgentView] 加载 Agent 列表失败:', error)
    ElMessage.error('加载 Agent 列表失败')
  } finally {
    loadingAgents.value = false
  }
}

/**
 * 选择一个 Agent，重置之前的执行结果
 */
function selectAgent(agent: AgentInfo): void {
  selectedAgent.value = agent
  executeResult.value = null
  executeError.value = ''
  taskInput.value = ''
  console.log('[AgentView] 已选择 Agent:', agent.agent_id)
}

/**
 * 执行选中的 Agent
 */
async function handleExecute(): Promise<void> {
  if (!selectedAgent.value || !taskInput.value.trim()) return

  executing.value = true
  executeResult.value = null
  executeError.value = ''

  try {
    console.log('[AgentView] 开始执行 Agent:', selectedAgent.value.agent_id)
    const result = await executeAgent(selectedAgent.value.agent_id, {
      task: taskInput.value,
    })
    executeResult.value = result
    ElMessage.success('Agent 执行完成！')
    console.log('[AgentView] Agent 执行成功，迭代次数:', result.iterations)
  } catch (error) {
    const errMsg = error instanceof Error ? error.message : '执行失败'
    executeError.value = errMsg
    console.error('[AgentView] Agent 执行失败:', error)
  } finally {
    executing.value = false
  }
}

/**
 * 将 Agent 执行结果对象格式化为 Markdown 字符串
 */
function formatAgentResult(result: Record<string, unknown>): string {
  // 尝试提取 final_answer 字段
  if (result.final_answer) {
    return String(result.final_answer)
  }
  if (result.content) {
    return String(result.content)
  }
  if (result.message) {
    return String(result.message)
  }
  // 否则格式化为 JSON 展示
  return '```json\n' + JSON.stringify(result, null, 2) + '\n```'
}

onMounted(() => {
  loadAgents()
})
</script>

<style scoped>
.agents-view { height: 100%; display: flex; flex-direction: column; }

.agents-layout {
  flex: 1;
  display: flex;
  gap: 0;
  overflow: hidden;
}

/* 左侧 Agent 列表面板 */
.agent-list-panel {
  width: 280px;
  min-width: 280px;
  border-right: 1px solid var(--color-border);
  background: var(--color-bg-primary);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
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

.list-loading, .agent-cards {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.agent-card {
  padding: 14px;
  margin-bottom: 10px;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.agent-card:hover {
  box-shadow: var(--shadow-md);
  transform: translateX(2px);
}

.agent-card.selected {
  border-color: var(--color-primary);
  background: var(--color-primary-lighter);
}

.agent-card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.agent-avatar {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: var(--gradient-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.agent-name {
  display: block;
  font-weight: 600;
  font-size: 0.875rem;
  color: var(--color-text-primary);
}

.agent-id {
  display: block;
  font-size: 0.7rem;
  color: var(--color-text-muted);
  font-family: var(--font-mono);
}

.agent-desc {
  font-size: 0.78rem;
  color: var(--color-text-secondary);
  line-height: 1.5;
  margin-bottom: 8px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.agent-capabilities {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.capability-tag {
  font-size: 0.65rem;
  padding: 2px 6px;
  background: var(--color-bg-secondary);
  color: var(--color-text-muted);
  border-radius: var(--radius-full);
  border: 1px solid var(--color-border);
}

.capability-more {
  font-size: 0.65rem;
  color: var(--color-primary);
  padding: 2px 4px;
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
.execution-panel {
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

.no-selection-text {
  font-size: 1rem;
  font-weight: 500;
  color: var(--color-text-secondary);
}

.no-selection-hint {
  font-size: 0.8rem;
  color: var(--color-text-muted);
}

/* 选中 Agent 的头部信息 */
.selected-agent-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  background: var(--gradient-primary-soft);
  border-radius: var(--radius-lg);
  border: 1px solid #ddd6fe;
}

.selected-agent-avatar {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  background: var(--gradient-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.selected-agent-name {
  font-weight: 700;
  font-size: 1rem;
  color: var(--color-text-primary);
}

.selected-agent-desc {
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  margin-top: 2px;
}

.selected-agent-meta {
  margin-left: auto;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}

.meta-item {
  font-size: 0.75rem;
  color: var(--color-text-muted);
  background: var(--color-bg-card);
  padding: 2px 8px;
  border-radius: var(--radius-full);
  border: 1px solid var(--color-border);
}

/* 任务输入区 */
.task-section { display: flex; flex-direction: column; gap: 8px; }
.input-label { font-size: 0.8rem; font-weight: 600; color: var(--color-text-secondary); }

/* 执行结果区域 */
.result-section { display: flex; flex-direction: column; gap: 12px; }
.result-header { display: flex; align-items: center; gap: 10px; }
.result-label { font-size: 0.875rem; font-weight: 600; color: var(--color-text-primary); }
.result-iterations { font-size: 0.75rem; color: var(--color-text-muted); margin-left: auto; }

.result-content {
  padding: 20px;
  max-height: 500px;
  overflow-y: auto;
}
</style>
