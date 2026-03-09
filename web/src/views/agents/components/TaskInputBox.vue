<template>
  <div class="task-input-section card-base">
    <div class="task-input-header">
      <div class="input-label">
        <el-icon><ChatDotRound /></el-icon>
        配置并执行任务
      </div>
      <div class="quick-examples">
        <span class="example-tag" @click="setExample(1)">示例1：简单任务</span>
        <span class="example-tag" @click="setExample(2)">示例2：复杂查询</span>
        <span class="example-tag example-tag-delegate" @click="setExample(3)">示例3：子Agent委派</span>
      </div>
    </div>
    
    <div class="input-controls">
      <el-input 
        v-model="internalConversationId" 
        placeholder="会话 ID (可选，留空则开启新会话)" 
        size="small"
        style="width: 260px;"
        clearable
      >
        <template #prefix>
          <el-icon><Setting /></el-icon>
        </template>
      </el-input>
      <el-tooltip content="相同会话 ID 可让 Agent 记住上次的上下文" placement="top">
        <el-icon class="info-icon" style="font-size: 14px; color: var(--color-text-muted)"><InfoFilled /></el-icon>
      </el-tooltip>
    </div>

    <!-- 改进的输入框，支持自动调节高度 -->
    <el-input
      v-model="internalTaskInput"
      type="textarea"
      :rows="3"
      :autosize="{ minRows: 3, maxRows: 8 }"
      placeholder="描述您需要解决的问题... (例如: 帮我查询订单 1002 的详情)"
      resize="none"
      class="custom-textarea"
    />
    
    <div class="action-footer">
      <!-- 执行过程中的状态条 -->
      <transition name="el-fade-in-linear">
        <div v-if="isStreaming" class="stream-status">
          <el-icon class="stream-status-icon"><Loading /></el-icon>
          <span class="stream-status-text">{{ streamStatusText }}</span>
          <span class="stream-events-count">{{ eventsCount }} 个事件</span>
        </div>
        <div v-else></div> <!-- 占位撑开 flex 布局 -->
      </transition>
      
      <el-button 
        type="primary" 
        size="large" 
        :icon="Promotion"
        :loading="executing"
        @click="$emit('execute')"
        class="execute-btn"
      >
        执行 Agent
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ChatDotRound, Setting, InfoFilled, Loading, Promotion } from '@element-plus/icons-vue'

const props = defineProps<{
  taskInput: string
  conversationId: string
  agentId: string
  executing: boolean
  isStreaming: boolean
  streamStatusText: string
  eventsCount: number
}>()

const emit = defineEmits<{
  (e: 'update:taskInput', val: string): void
  (e: 'update:conversationId', val: string): void
  (e: 'execute'): void
}>()

const internalTaskInput = computed({
  get: () => props.taskInput,
  set: (val) => emit('update:taskInput', val)
})

const internalConversationId = computed({
  get: () => props.conversationId,
  set: (val) => emit('update:conversationId', val)
})

const EXAMPLE_MAP: Record<number, Record<string, string>> = {
  1: {
    default:      '帮我查询订单号 1002 的详细情况，包括商品、客户和配送状态。',
    cs_master:    '帮我查询订单号 1002 的详细情况，包括商品、客户和配送状态。',
    order_agent:  '查询订单号 1002 的详细信息：买了什么商品、支付了多少、现在的配送状态是什么，物流单号是多少？',
    refund_agent: '查询订单号 1003 的退款进度，请告知当前处理状态和退款金额。',
    general_agent: '请把这句话翻译成英文："人工智能在改变我们的生活。"',
  },
  2: {
    default:      '帮我查询客户"李娜"的所有订单记录，列出每笔订单的金额和当前状态。',
    cs_master:    '帮我查询客户"李娜"的所有订单，并汇总她的总消费金额。',
    order_agent:  '查询客户ID为2的所有订单，统计她的订单总数、总金额。',
    refund_agent: '查询所有待审核的退款申请（status=pending），列出申请人。',
    general_agent: '搜一下什么是 MCP，通俗地解释一下。',
  },
  3: {
    default:      '统计各种订单状态的订单数量，给出业务分析。',
    cs_master:    '查询订单号 1002 的详细情况，找到订单的总金额，写入本地',
    order_agent:  '分析已发货但未签收的订单，列出订单号、客户。',
    refund_agent: '统计所有退款记录的总退款金额，按退款状态分组。',
    general_agent: '用 Python 写一个快速排序算法。',
  },
}

function setExample(num: number) {
  const map = EXAMPLE_MAP[num] || {}
  const text = map[props.agentId] || map['default'] || ''
  internalTaskInput.value = text
}
</script>

<style scoped>
.task-input-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  padding: 16px;
  border-radius: var(--radius-lg);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.05); /* 底部输入框加上浅轻的阴影，让它像浮起的控制台面板 */
}

.task-input-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.input-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.quick-examples {
  display: flex;
  gap: 8px;
}

.example-tag {
  font-size: 0.7rem;
  padding: 4px 10px;
  background: var(--color-bg-secondary);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--color-primary);
  transition: all 0.2s ease;
}

.example-tag:hover {
  background: var(--color-primary-lighter);
  transform: translateY(-1px);
}

.input-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.action-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.execute-btn {
  padding: 0 32px;
  font-weight: 600;
  border-radius: var(--radius-md);
  box-shadow: 0 4px 12px rgba(var(--el-color-primary-rgb), 0.3);
}

.stream-status {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08) 0%, rgba(139, 92, 246, 0.06) 100%);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  font-size: 0.85rem;
}

.stream-status-icon {
  animation: spin 1s linear infinite;
  color: var(--color-primary);
}

.stream-status-text {
  font-weight: 500;
  color: var(--color-text-primary);
}

.stream-events-count {
  font-size: 0.75rem;
  padding: 2px 8px;
  background: var(--color-bg-primary);
  border-radius: var(--radius-full);
  color: var(--color-text-muted);
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

:deep(.custom-textarea .el-textarea__inner) {
  border-radius: var(--radius-md);
  padding: 12px;
  font-size: 0.95rem;
  line-height: 1.5;
  background-color: var(--color-bg-secondary);
  border-color: var(--color-border-light);
  transition: all 0.3s ease;
}

:deep(.custom-textarea .el-textarea__inner:focus) {
  background-color: var(--color-bg-primary);
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px rgba(var(--el-color-primary-rgb), 0.1);
}
</style>
