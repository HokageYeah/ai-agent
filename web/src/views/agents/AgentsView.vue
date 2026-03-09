<template>
  <div class="agents-view page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">Agent 执行</h2>
        <p class="page-desc">选择专家 Agent，输入任务后启动 Planning → Execution → Reflection 执行闭环</p>
      </div>
    </div>

    <div class="agents-layout">
      <!-- 左侧：Agent 列表组件 -->
      <AgentListPanel 
        :agents="agents" 
        :loading="loadingAgents" 
        :selectedAgent="selectedAgent"
        @refresh="loadAgents" 
        @select="onSelectAgent" 
      />

      <!-- 右侧：执行面板 -->
      <div class="execution-panel">
        <!-- 未选择 Agent 时的占位 -->
        <div v-if="!selectedAgent" class="no-selection">
          <el-icon :size="48" style="color:var(--color-border)"><Setting /></el-icon>
          <p class="no-selection-text">请从左侧选择一个 Agent</p>
          <p class="no-selection-hint">选择后可以输入任务描述并执行</p>
        </div>

        <!-- 已选择 Agent：显示执行流界面 -->
        <template v-else>
          <!-- 头部信息 -->
          <ExecutionHeader :agent="selectedAgent" />

          <!-- 轨迹流看板 -->
          <TrajectoryPanel 
            v-if="executeResult || isStreaming || (streamEvents && streamEvents.length > 0)"
            :streamEvents="streamEvents"
            :selectedAgent="selectedAgent"
            :isStreaming="isStreaming"
            :currentPhase="currentPhase"
            :progressPercent="progressPercent"
            :confirmLoading="confirmLoading"
            :confirmedIds="confirmedIds"
            :confirmActionMap="confirmActionMap as Record<string, string>"
            @confirm="handleConfirm"
          />

          <!-- 底部任务输入与控制 -->
          <TaskInputBox 
            v-model:taskInput="taskInput"
            v-model:conversationId="conversationId"
            :agentId="selectedAgent.agent_id"
            :executing="executing"
            :isStreaming="isStreaming"
            :streamStatusText="getStreamStatusText()"
            :eventsCount="streamEvents.length"
            @execute="handleExecute"
          />
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Setting } from '@element-plus/icons-vue'
import type { AgentInfo } from '@/types/agent'

// 导入拆分的子组件
import AgentListPanel from './components/AgentListPanel.vue'
import ExecutionHeader from './components/ExecutionHeader.vue'
import TaskInputBox from './components/TaskInputBox.vue'
import TrajectoryPanel from './components/TrajectoryPanel.vue'

// 导入逻辑 hooks
import { useAgentList } from './hooks/useAgentList'
import { useAgentStream } from './hooks/useAgentStream'

// === 1. 面板级别共享状态 ===
const taskInput = ref('')
const conversationId = ref('')

// === 2. 左侧 Agent 列表处理 Hook ===
const {
  agents,
  selectedAgent,
  loadingAgents,
  loadAgents,
  selectAgent
} = useAgentList()

// === 3. 右侧流式通信 Hook ===
const {
  executing,
  isStreaming,
  executeResult,
  streamEvents,
  confirmLoading,
  confirmedIds,
  confirmActionMap,
  currentPhase,
  progressPercent,
  handleExecute,
  handleConfirm,
  getStreamStatusText
} = useAgentStream({
  selectedAgent,
  taskInput,
  conversationId
})

// === 事件包装：在切换 Agent 时顺便清空输入和状态 ===
function onSelectAgent(agent: AgentInfo) {
  selectAgent(agent)
  taskInput.value = ''
  streamEvents.value = []
  executeResult.value = null
}

// === 初次挂载加载列表 ===
onMounted(() => {
  loadAgents()
})
</script>

<style scoped>
.agents-view { 
  height: 100%; 
  display: flex; 
  flex-direction: column; 
}

.agents-layout {
  flex: 1;
  display: flex;
  gap: 0;
  overflow: hidden;
}

/* 右侧执行面板 - flex 列布局，使中间轨迹区可独立滚动，底部输入区固定 */
.execution-panel {
  flex: 1;
  overflow: hidden; 
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
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
</style>
