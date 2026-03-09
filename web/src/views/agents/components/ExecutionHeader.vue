<template>
  <div class="selected-agent-header">
    <div class="selected-agent-avatar">
      <el-icon :size="24" style="color:white"><Setting /></el-icon>
    </div>
    <div class="selected-agent-info">
      <div class="selected-agent-name">{{ agent.name }}</div>
      <div class="selected-agent-desc">{{ agent.description }}</div>
    </div>
    
    <!-- 使用说明 tooltip：悬停图标显示说明 -->
    <el-tooltip placement="top" effect="light">
      <template #content>
        <div class="agent-usage-guide">
          <p><strong>Agent 角色说明：</strong>{{ agent.description }}</p>
          <p>Agent 能够基于选定的专家角色，自主规划（Planning）→ 执行（Execution）→ 思考（Reasoning）→ 产生最终结果（Final Answer）。</p>
          <p><strong>操作指南：</strong>在下方输入需要解决的复杂问题，点击执行即可观测大模型的自动化思维与行为闭环。</p>
        </div>
      </template>
      <el-icon :size="18" class="info-icon"><InfoFilled /></el-icon>
    </el-tooltip>
    
    <div class="selected-agent-meta">
      <span class="meta-item">工具: {{ agent.available_tools.length }}</span>
      <span class="meta-item">技能: {{ agent.available_skills.length }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Setting, InfoFilled } from '@element-plus/icons-vue'
import type { AgentInfo } from '@/types/agent'

defineProps<{
  agent: AgentInfo
}>()
</script>

<style scoped>
.selected-agent-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 20px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08) 0%, rgba(139, 92, 246, 0.06) 100%);
  border-radius: 12px;
  border: 1px solid rgba(99, 102, 241, 0.2);
  box-shadow: 0 2px 12px rgba(99, 102, 241, 0.08);
}

.selected-agent-avatar {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-lg);
  background: var(--gradient-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.selected-agent-info {
  flex: 1;
}

.selected-agent-name {
  font-weight: 600;
  font-size: 1.1rem;
  color: var(--color-text-primary);
  margin-bottom: 4px;
}

.selected-agent-desc {
  font-size: 0.85rem;
  color: var(--color-text-secondary);
}

.info-icon {
  cursor: pointer;
  transition: color 0.2s ease;
  color: var(--color-text-muted);
}

.info-icon:hover {
  color: var(--color-primary);
}

.agent-usage-guide {
  padding: 12px 16px;
  max-width: 300px;
}

.agent-usage-guide p {
  margin: 0 0 8px 0;
  line-height: 1.6;
}

.agent-usage-guide p:last-child {
  margin-bottom: 0;
}

.selected-agent-meta {
  display: flex;
  gap: 12px;
}

.meta-item {
  font-size: 0.75rem;
  color: var(--color-primary);
  background: var(--color-bg-primary);
  padding: 4px 10px;
  border-radius: var(--radius-full);
  border: 1px solid rgba(99, 102, 241, 0.2);
  font-weight: 500;
}
</style>
