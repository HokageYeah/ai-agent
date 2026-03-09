<template>
  <div class="agent-list-panel">
    <div class="panel-header">
      <span class="panel-label">可用 Agent</span>
      <el-button size="small" :icon="Refresh" text @click="$emit('refresh')" :loading="loading">刷新</el-button>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="list-loading">
      <div v-for="i in 3" :key="i" class="skeleton" style="height:80px;border-radius:10px;margin-bottom:10px;"></div>
    </div>

    <!-- Agent 卡片列表 -->
    <div v-else class="agent-cards">
      <div
        v-for="agent in agents"
        :key="agent.agent_id"
        class="agent-card card-base"
        :class="{ selected: selectedAgent?.agent_id === agent.agent_id }"
        @click="$emit('select', agent)"
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
</template>

<script setup lang="ts">
import { Refresh, Setting } from '@element-plus/icons-vue'
import type { AgentInfo } from '@/types/agent'

defineProps<{
  agents: AgentInfo[]
  selectedAgent: AgentInfo | null
  loading: boolean
}>()

defineEmits<{
  (e: 'refresh'): void
  (e: 'select', agent: AgentInfo): void
}>()
</script>

<style scoped>
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
</style>
