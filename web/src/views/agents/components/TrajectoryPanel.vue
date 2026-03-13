<template>
  <div class="trajectory-section">
    <!-- 头部：标题 + 阶段进度指示器 -->
    <div class="trajectory-header">
      <div class="trajectory-title">
        <el-icon><DataLine /></el-icon>
        <span>Agent 思考与执行轨迹</span>
        <!-- 阶段进度指示器 -->
      <div class="trajectory-progress">
        <div class="step-item" :class="{ active: currentPhase === 'planning', completed: progressPercent > 20 }">
          <div class="step-icon">
             <el-icon v-if="progressPercent > 20"><Check /></el-icon>
             <el-icon v-else><Aim /></el-icon>
          </div>
          <span class="step-label">规划</span>
        </div>
        <div class="step-divider" :class="{ active: progressPercent > 20 }"></div>
        
        <div class="step-item" :class="{ active: currentPhase === 'executing', completed: progressPercent > 50 }">
          <div class="step-icon">
             <el-icon v-if="progressPercent > 50"><Check /></el-icon>
             <el-icon v-else><Promotion /></el-icon>
          </div>
          <span class="step-label">执行</span>
        </div>
        <div class="step-divider" :class="{ active: progressPercent > 50 }"></div>
        
        <div class="step-item" :class="{ active: currentPhase === 'reflecting', completed: progressPercent > 80 }">
          <div class="step-icon">
             <el-icon v-if="progressPercent > 80"><Check /></el-icon>
             <el-icon v-else><ChatDotRound /></el-icon>
          </div>
          <span class="step-label">反思</span>
        </div>
        <div class="step-divider" :class="{ active: progressPercent > 80 }"></div>
        
        <div class="step-item" :class="{ active: currentPhase === 'completed', completed: currentPhase === 'completed' }">
          <div class="step-icon">
             <el-icon><Finished /></el-icon>
          </div>
          <span class="step-label">完成</span>
        </div>
      </div>
      </div>
    
      
      <!-- 全局操控选项 -->
      <div class="header-actions">
        <el-button size="small" :icon="isAllExpanded ? 'Fold' : 'Expand'" @click="toggleAllExpansion" plain style="border-radius: 6px;">
          {{ isAllExpanded ? '全部折叠' : '全部展开' }}
        </el-button>
      </div>
    </div>
    
    <!-- 流式事件嵌套分组展示 (纯缩进极简树) -->
    <div v-if="streamEvents.length > 0" class="stream-events-wrapper">
      <div
        class="stream-events-container"
        ref="streamEventsContainer"
        @scroll="onTrajectoryScroll"
      >
        <div 
           v-for="node in visibleNodes" 
           :key="node.id" 
           class="trajectory-row"
           :class="['level-' + node.level, { 'is-clickable': node.isParent }]"
           :style="{ paddingLeft: `calc(${node.level} * 24px + 12px)` }"
           @click="node.isParent ? toggleExpansion(node.id) : null"
        >
          <!-- 折叠图标区域 -->
          <div class="row-expander" v-if="node.isParent">
             <el-icon :class="{ 'is-expanded': node.isExpanded }"><CaretRight /></el-icon>
          </div>
          <div class="row-expander-placeholder" v-else></div>

          <!-- 节点内容渲染 -->
          <div class="row-content">
             
             <!-- Level 0: 迭代 -->
             <div v-if="node.type === 'iteration'" class="node-iteration">
                 {{ node.title }}
             </div>

             <!-- Level 1: 核心阶段 -->
             <div v-else-if="node.type === 'phase'" class="node-phase">
                 {{ node.title }}
             </div>

             <!-- 子 Agent 开始 -->
             <div v-else-if="node.type === 'sub_agent'" class="node-sub-agent">
                 <el-icon><User /></el-icon>
                 <span class="sub-label">委派给</span>
                 <span class="mono-tag" style="background:#f3f4f6">{{ node.title }}</span>
             </div>

             <!-- 长文本推理 -->
             <div v-else-if="node.type === 'reasoning'" class="node-reasoning">
                 {{ node.event?.data?.reasoning }}
             </div>

             <!-- 报错与重新规划 -->
             <div v-else-if="node.type === 'error_replan'" class="node-error-replan">
                 <el-icon><Warning /></el-icon>
                 <span>发现问题，要求重新规划：{{ node.event?.data?.feedback }}</span>
             </div>

             <!-- 反思结果本身 -->
             <div v-else-if="node.type === 'reflection'" class="node-reflection">
                 <span class="success-text">反思通过</span>: {{ node.event?.data?.feedback || '无特殊反馈' }}
             </div>

             <!-- 需要用户确认 -->
             <div v-else-if="node.type === 'confirm'" class="node-confirm">
                <div class="confirm-message">
                  <el-icon><WarningFilled /></el-icon> 等待用户确认执行操作 <span class="mono-tag" style="background:#f3f4f6">{{ node.event?.data?.tool_name || '未知操作' }}</span> <span class="blink-cursor">_</span>
                </div>
                <!-- 操作区 -->
                <div v-if="!confirmedIds.includes(node.event?.data?.confirm_id)" class="confirm-actions">
                    <el-button type="primary" size="small" :loading="confirmLoading === node.event?.data?.confirm_id" @click.stop="$emit('confirm', node.event?.data?.confirm_id, 'confirm')">允许</el-button>
                    <el-button type="danger" size="small" :disabled="confirmLoading === node.event?.data?.confirm_id" @click.stop="$emit('confirm', node.event?.data?.confirm_id, 'reject')">拒绝</el-button>
                </div>
                <div v-else class="confirm-status">
                    用户已 {{ confirmActionMap[node.event?.data?.confirm_id] === 'confirm' ? '允许' : '拒绝' }}
                </div>
             </div>

             <!-- 需要用户提供额外信息 - 直接在轨迹中显示输入框 -->
             <div v-else-if="node.type === 'user_input' || node.event?.event === 'await_user_input'" class="node-user-input-wrap">
                <div class="user-input-header-line">
                  <el-icon class="user-input-icon"><WarningFilled /></el-icon>
                  <span class="user-input-title">需要您提供以下信息</span>
                  <span class="mono-tag user-input-tag">{{ node.event?.data?.tool_name || '工具' }}</span>
                </div>
                <p class="user-input-desc">{{ (pendingInputRequest || node.event?.data)?.message || '请提供以下信息' }}</p>
                <div v-if="!isActiveInputNode(node)" class="input-waiting-tip">
                  <el-icon><Check /></el-icon>
                  <span>该输入请求已处理，等待后续执行结果</span>
                </div>
                <!-- 邮件服务专用输入布局（SMTP 配置） -->
                <div v-else-if="isMailInputNode(node)" class="inline-input-form mail-input-form">
                  <el-form label-position="top" size="small" class="inline-form">
                    <el-row :gutter="8">
                      <el-col :span="14">
                        <el-form-item label="SMTP 服务器地址" class="inline-form-item">
                          <el-input
                            size="small"
                            v-model="inputForm['smtp_server']"
                            placeholder="例如: smtp.qq.com"
                          />
                        </el-form-item>
                      </el-col>
                      <el-col :span="10">
                        <el-form-item label="端口" class="inline-form-item">
                          <el-input
                            size="small"
                            type="number"
                            v-model="inputForm['smtp_port']"
                            placeholder="465 / 587"
                          />
                        </el-form-item>
                      </el-col>
                    </el-row>
                    <el-form-item label="发件人邮箱" class="inline-form-item">
                      <el-input
                        size="small"
                        type="email"
                        v-model="inputForm['sender_email']"
                        placeholder="例如: your_email@qq.com"
                      />
                    </el-form-item>
                    <el-form-item label="SMTP 授权码" class="inline-form-item">
                      <el-input
                        size="small"
                        type="password"
                        v-model="inputForm['sender_password']"
                        placeholder="邮箱设置中生成的授权码"
                      />
                    </el-form-item>
                  </el-form>
                  <div class="inline-input-actions">
                    <el-button type="primary" size="small" :loading="userInputLoading === pendingInputRequest?.input_request_id" @click.stop="submitUserInput">
                      提交
                    </el-button>
                  </div>
                </div>
                <!-- 通用输入布局（其他类型的用户输入） -->
                <div v-else class="inline-input-form">
                  <el-form label-position="top" size="small" class="inline-form">
                    <el-form-item
                      v-for="field in (pendingInputRequest?.required_fields || node.event?.data?.required_fields || [])"
                      :key="field.name"
                      :label="field.label"
                      class="inline-form-item"
                    >
                      <el-input
                        v-if="field.type === 'number'"
                        type="number"
                        size="small"
                        v-model="inputForm[field.name]"
                        :placeholder="field.placeholder || ''"
                        :default="field.default"
                      />
                      <el-input
                        v-else-if="field.secret"
                        type="password"
                        size="small"
                        v-model="inputForm[field.name]"
                        :placeholder="field.placeholder || ''"
                      />
                      <el-input
                        v-else
                        size="small"
                        :type="field.type === 'email' ? 'email' : 'text'"
                        v-model="inputForm[field.name]"
                        :placeholder="field.placeholder || ''"
                      />
                    </el-form-item>
                  </el-form>
                  <div class="inline-input-actions">
                    <el-button type="primary" size="small" :loading="userInputLoading === pendingInputRequest?.input_request_id" @click.stop="submitUserInput">
                      提交
                    </el-button>
                  </div>
                </div>
             </div>

             <!-- 普通动作 (Action/Event) -->
             <div v-else-if="node.type === 'action'" class="node-action" :class="{ 'is-thinking': isStreaming && isLastNode(node) }">
                 <!-- 子 Agent 完成委派 -->
                 <template v-if="node.event?.event === 'delegate_complete'">
                    <el-icon class="action-icon success"><User /></el-icon>
                    <span>{{ getAgentDisplayName(node.event?.data) }} 完成委派</span>
                    <span v-if="node.event?.data?.success" class="result-preview success">执行成功</span>
                    <span v-else class="result-preview error">执行失败</span>
                 </template>
                 <!-- 步骤完成 -->
                 <template v-else-if="node.event?.event === 'step_complete'">
                    <el-icon class="action-icon success"><Check /></el-icon>
                    <span>{{ node.event?.data?.step_name || '步骤完成' }}</span>
                    <span v-if="node.event?.data?.message" class="result-preview">{{ node.event?.data?.message }}</span>
                 </template>
                 <!-- 工具调用 -->
                 <template v-else-if="node.event?.event === 'tool_complete' || node.event?.event === 'skill_complete'">
                    <el-icon class="action-icon success"><CopyDocument /></el-icon>
                    <span>调用 <span class="mono-tag" style="background:#f3f4f6">{{ node.event?.data?.tool_name || node.event?.data?.skill_id }}</span></span>
                    <span v-if="node.event?.data?.result" class="result-preview" :title="formatResult(node.event?.data?.result)">
                        {{ formatExecutionTime(node.event?.data) }}
                    </span>
                 </template>
                 <!-- 最终答案 -->
                 <template v-else-if="node.event?.event === 'final_answer'">
                    <el-icon class="action-icon highlight"><List /></el-icon>
                    <div class="final-answer-wrapper">
                        <div class="final-answer-header">
                            <span class="final-answer-label">生成最终答案</span>
                            <el-button class="copy-btn" size="small" plain text :icon="DocumentCopy" @click.stop="copyText(formatResult(node.event?.data?.result))">
                              复制内容
                            </el-button>
                        </div>
                        <div class="final-answer-content">
                            <MarkdownRenderer :content="formatResult(node.event?.data?.result)" />
                        </div>
                    </div>
                 </template>
                 <!-- 错误发生 -->
                 <template v-else-if="['step_error', 'error'].includes(node.event?.event || '')">
                    <el-icon class="action-icon error"><WarningFilled /></el-icon>
                    <span class="error-text">执行发生错误: {{ node.event?.error || node.event?.data?.error || '未知错误' }}</span>
                 </template>
                 <!-- 其他过程事件 -->
                 <template v-else>
                    <el-icon class="action-icon"><InfoFilled /></el-icon>
                    <span class="mono-tag" style="background:#f3f4f6">{{ node.event?.event }}</span>
                 </template>
             </div>

          </div>
        </div>

        <!-- 流式请求等待/执行中的极客感光标状态 -->
        <div v-if="isStreaming && currentPhase !== 'completed'" class="streaming-indicator">
          <span class="indicator-text">思考执行中</span>
          <div class="dot-typing"><span></span></div>
        </div>
      </div>
      
      <!-- 回到底部按钮 -->
      <transition name="el-zoom-in-center">
        <button v-show="showScrollToBottomButton" class="scroll-to-bottom-btn" @click="scrollToLatestEvent" title="回到底部">
          <el-icon size="20"><Bottom /></el-icon>
        </button>
      </transition>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, toRefs } from 'vue'
import {
  DataLine, Aim, Promotion, ChatDotRound, Finished, CaretRight, User, Check,
  WarningFilled, CopyDocument, Warning, List, Bottom, InfoFilled, Fold, Expand, DocumentCopy, Loading
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { StreamEvent, ExecutionPhase, TrajectoryNode } from '@/types/stream'
import type { AgentInfo } from '@/types/agent'
import { useTrajectory } from '../hooks/useTrajectory'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'

const props = defineProps<{
  streamEvents: StreamEvent[]
  selectedAgent: AgentInfo | null
  isStreaming: boolean
  currentPhase: ExecutionPhase
  progressPercent: number
  confirmLoading: string | null
  confirmedIds: string[]
  confirmActionMap: Record<string, string>
  userInputLoading: string | null
  pendingInputRequest: {
    input_request_id: string
    tool_name: string
    required_fields: Array<{
      name: string
      label: string
      type: string
      placeholder?: string
      default?: string
      secret?: boolean
    }>
    message: string
  } | null
}>()

const emit = defineEmits<{
  (e: 'confirm', confirmId: string, action: 'confirm'|'reject'): void
  (e: 'submitInput', inputRequestId: string, inputs: Record<string, any>): void
}>()

const propRefs = toRefs(props)

const {
  streamEventsContainer,
  userAtBottom,
  showScrollToBottomButton,
  onTrajectoryScroll,
  scrollToLatestEvent,
  expansionState,
  toggleExpansion,
  visibleNodes
} = useTrajectory({
  streamEvents: propRefs.streamEvents,
  selectedAgent: propRefs.selectedAgent
})

const isAllExpanded = ref(true)

// 用户输入表单相关
const inputForm = ref<Record<string, string>>({})

// 判断当前节点是否属于「邮件服务配置」类型输入
function isMailInputNode(node: TrajectoryNode): boolean {
  // 优先使用挂起的 pendingInputRequest，其次回退到当前节点事件数据
  const data: any = props.pendingInputRequest || node.event?.data
  const fields: Array<{ name: string }> = data?.required_fields || []
  if (!fields.length) return false

  const names = fields.map(f => f.name)
  const REQUIRED_SMTP_FIELDS = ['smtp_server', 'smtp_port', 'sender_email', 'sender_password']

  return REQUIRED_SMTP_FIELDS.every(key => names.includes(key))
}

function submitUserInput() {
  if (!props.pendingInputRequest) return
  emit('submitInput', props.pendingInputRequest.input_request_id, inputForm.value)
  // 清空表单
  inputForm.value = {}
}

function cancelUserInput() {
  // 取消输入时，也需要通知后端（可以发送一个空输入或者特殊标记）
  if (props.pendingInputRequest) {
    emit('submitInput', props.pendingInputRequest.input_request_id, {})
  }
  inputForm.value = {}
}

function expandAll() {
  visibleNodes.value.forEach(node => {
     if (node.isParent) expansionState.value[node.id] = true
  })
}

function collapseAll() {
  visibleNodes.value.forEach(node => {
     if (node.isParent) expansionState.value[node.id] = false
  })
}

function toggleAllExpansion() {
  if (isAllExpanded.value) {
    collapseAll()
  } else {
    expandAll()
  }
  isAllExpanded.value = !isAllExpanded.value
}

function isLastNode(node: TrajectoryNode): boolean {
  if (!visibleNodes.value.length) return false
  return visibleNodes.value[visibleNodes.value.length - 1].id === node.id
}

function getInputRequestId(node: TrajectoryNode): string {
  return (
    node.event?.data?.input_request_id ||
    node.event?.data?.message_id ||
    ''
  )
}

function isActiveInputNode(node: TrajectoryNode): boolean {
  if (!props.pendingInputRequest) return false
  const nodeInputRequestId = getInputRequestId(node)
  return !!nodeInputRequestId && nodeInputRequestId === props.pendingInputRequest.input_request_id
}

function formatResult(res: any): string {
  if (res === null || res === undefined) return ''
  if (typeof res === 'object') {
    try {
      return '```json\n' + JSON.stringify(res, null, 2) + '\n```'
    } catch {
      return String(res)
    }
  }
  return String(res)
}

function formatExecutionTime(data: any): string {
  const raw =
    data?.execution_time_ms ??
    data?.result?.execution_time_ms ??
    data?.result?.elapsed_ms
  const value = Number(raw)
  if (Number.isFinite(value) && value >= 0) {
    return `耗时 ${value.toFixed(2)}ms`
  }
  return '执行完成'
}

function copyText(text: string) {
  if (!text) return
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(() => {
      ElMessage.success('已成功复制答案到剪贴板')
    }).catch((err) => {
      console.error('复制失败:', err)
      ElMessage.error('复制失败，请手动选择复制')
    })
  } else {
    // 降级方案
    const textArea = document.createElement("textarea")
    textArea.value = text
    textArea.style.position = "absolute"
    textArea.style.opacity = "0"
    textArea.style.left = "-999999px"
    textArea.style.top = "-999999px"
    document.body.appendChild(textArea)
    textArea.focus()
    textArea.select()
    try {
      document.execCommand('copy')
      ElMessage.success('已成功复制答案到剪贴板')
    } catch (err) {
      console.error('复制失败:', err)
      ElMessage.error('复制失败，请手动选择复制')
    }
    textArea.remove()
  }
}

/**
 * 代理 ID 到中文名称的映射表
 * 用于显示代理委派完成时的代理名称
 */
const AGENT_NAME_MAP: Record<string, string> = {
  'order_agent': '订单专员',
  'refund_agent': '退款专员',
  'general_agent': '通用助手',
  'cs_master': '客服总监'
}

/**
 * 获取代理的中文名称
 * 优先从 event.data.result.agent_name 获取，如果没有则使用映射表
 * @param agentId - 代理 ID
 * @returns 代理的中文名称
 */
function getAgentDisplayName(eventData: any): string {
  // 优先从 result.agent_name 获取
  if (eventData?.result?.agent_name) {
    return eventData.result.agent_name
  }
  // 降级：使用 agent_id 从映射表获取
  const agentId = eventData?.agent_id
  if (agentId && AGENT_NAME_MAP[agentId]) {
    return AGENT_NAME_MAP[agentId]
  }
  // 最后降级：直接返回 agent_id
  return agentId || '未知代理'
}
</script>

<style scoped>
.trajectory-section {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background: var(--color-bg-primary);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-sm);
}

.trajectory-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--color-border-light);
  z-index: 10;
}
.trajectory-title { font-size: 1rem; font-weight: 600; display:flex; gap:8px; align-items:center; color: var(--color-text-primary); }

.trajectory-progress { 
  display: flex; 
  align-items: center; 
  background: var(--color-bg-secondary, #f3f4f6);
  padding: 4px 6px;
  border-radius: 24px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  margin-left: 20px;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px 4px 6px;
  border-radius: 20px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  color: var(--color-text-muted, #6b7280);
}

.step-item .step-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
  font-size: 12px;
  color: inherit;
  transition: all 0.3s ease;
}

.step-item .step-label {
  font-size: 0.75rem;
  font-weight: 500;
  white-space: nowrap;
}

.step-item.completed {
  color: var(--el-color-success, #10b981);
}

.step-item.completed .step-icon {
  background: var(--el-color-success-light-9, #ecfdf5);
  color: var(--el-color-success, #10b981);
  box-shadow: none;
}

.step-item.active {
  background: var(--color-primary, #6366f1);
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.25);
}

.step-item.active .step-icon {
  background: rgba(255, 255, 255, 0.2);
  color: #ffffff;
  box-shadow: none;
}

.step-divider {
  width: 16px;
  height: 2px;
  background: var(--color-border, #d1d5db);
  margin: 0 2px;
  border-radius: 2px;
  transition: background 0.3s;
}

.step-divider.active {
  background: var(--el-color-success, #10b981);
}

.stream-events-wrapper { position: relative; flex: 1; display:flex; flex-direction:column; min-height:0; }
.stream-events-container { 
  flex: 1; 
  overflow-y: auto; 
  padding: 10px; 
  background: #ffffff; /* 强制白底 */
}
.stream-events-container::-webkit-scrollbar { width: 6px; }
.stream-events-container::-webkit-scrollbar-thumb { background: var(--color-border); border-radius: 3px; }

/* 核心缩进列样式 */
.trajectory-row {
  display: flex;
  align-items: flex-start;
  padding-top: 8px;
  padding-bottom: 8px;
  padding-right: 16px;
  border-radius: 4px;
  transition: background-color 0.2s ease;
  color: #111827; /* 深灰 */
  font-family: inherit; /* 无衬线 */
  line-height: 1.5;
}

.trajectory-row:hover {
  background-color: #f9fafb; /* 悬停高亮 */
}

.trajectory-row.is-clickable {
  cursor: pointer;
}

.row-expander {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  color: #9ca3af; /* 浅灰折叠箭头 */
  transition: transform 0.2s;
  flex-shrink: 0;
}
.row-expander .el-icon {
  transition: transform 0.2s;
}
.row-expander .el-icon.is-expanded {
  transform: rotate(90deg);
}

.row-expander-placeholder {
  width: 24px;
  height: 24px;
  flex-shrink: 0;
}

.row-content {
  flex: 1;
  min-width: 0; /* 允许内部折行 */
  padding-top: 2px; /* 和图标稍微对齐 */
}

/* 节点层级特定的字体渲染 */
.node-iteration {
  font-weight: 700;
  font-size: 1rem;
}

.node-phase {
  font-weight: 600;
  font-size: 0.95rem;
  color: #374151;
}

.node-sub-agent {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.9rem;
}
.node-sub-agent .sub-label {
  color: #6b7280;
}

.node-reasoning {
  color: #6b7280;
  font-size: 0.85rem;
  white-space: pre-wrap; /* 保持段落和换行 */
}

.node-error-replan {
  color: #ef4444; /* 红色 */
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 0.9rem;
}

.node-reflection .success-text {
  color: #10b981; /* 绿色 */
  font-weight: 600;
}

.node-confirm {
  color: #f59e0b; /* 橙色 */
  font-size: 0.9rem;
  display: flex;
  align-items: center;
  gap: 12px;
}
.confirm-message { display: flex; align-items: center; gap: 6px; }
.blink-cursor { animation: blink 1s step-end infinite; font-weight: bold; }
@keyframes blink { 50% { opacity: 0; } }
.confirm-actions { display: flex; gap: 8px; }
.confirm-status { font-size: 0.85rem; }

.node-action {
  font-size: 0.9rem;
  display: flex;
  align-items: flex-start; /* 文本可能换行 */
  gap: 6px;
}
.node-action.is-thinking { opacity: 0.7; }
.action-icon { margin-top: 4px; }
.action-icon.success { color: #10b981; }
.action-icon.highlight { color: #8b5cf6; }
.action-icon.error { color: #ef4444; }

.error-text { color: #ef4444; }
.result-preview { color: #9ca3af; font-size: 0.8rem; margin-left: auto; /* 推到右边 */ }

.final-answer-wrapper {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 100%;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
  margin-top: -2px;
}

.final-answer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: #f1f5f9;
  border-bottom: 1px solid #e2e8f0;
}

.final-answer-label {
  font-weight: 600;
  color: #334155;
  font-size: 0.85rem;
}

.copy-btn {
  font-size: 0.8rem !important;
  color: #64748b !important;
}
.copy-btn:hover {
  color: var(--color-primary) !important;
}

.final-answer-content {
  padding: 14px;
}

:deep(.final-answer-content p) {
  margin: 0; /* 清除默认 markdown p 带来的过大边距 */
}

/* 全局专业名词标签 (Monospace) */
.mono-tag {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  background-color: #f3f4f6; /* 极致微弱的浅灰背景色 */
  color: #374151; /* 略深字体 */
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.85em; /* 轻微缩小以匹配无衬线字体高度 */
  border: 1px solid #e5e7eb; /* 极淡的边框增加对比度 */
}

.scroll-to-bottom-btn {
  position: absolute; right: 16px; bottom: 16px; width:40px; height:40px; background: var(--color-primary); color: white;
  border-radius: 50%; border:none; cursor: pointer; display:flex; align-items:center; justify-content:center;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15); transition: 0.2s;
}
.scroll-to-bottom-btn:hover { transform: scale(1.05); }

:deep(.final-answer-text p) {
  margin: 0; /* 清除默认 markdown p 的边距 */
}

/* ======== 流式加载指示器 (律动渐变省略号) ======== */
.streaming-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  padding: 8px 12px;
  font-family: inherit;
  font-size: 0.85rem;
  font-weight: 600;
}

.indicator-text {
  background: linear-gradient(90deg, var(--color-primary, #8b5cf6), #3b82f6, var(--color-primary, #8b5cf6));
  background-size: 200% auto;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: shine 2.5s linear infinite;
}

@keyframes shine {
  to {
    background-position: 200% center;
  }
}

.dot-typing {
  display: inline-flex;
  gap: 4px;
  align-items: center;
  height: 14px;
  padding-bottom: 2px;
}
.dot-typing::before,
.dot-typing::after,
.dot-typing span {
  content: '';
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background-color: var(--color-primary, #8b5cf6);
  animation: bounce 1.4s infinite ease-in-out both;
}
.dot-typing::before { 
  animation-delay: -0.32s; 
}
.dot-typing span { 
  animation-delay: -0.16s; 
}

@keyframes bounce {
  0%, 80%, 100% { 
    transform: scale(0);
    opacity: 0.3;
  }
  40% { 
    transform: scale(1);
    opacity: 1;
  }
}

/* 用户输入对话框样式 */
.user-input-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.user-input-dialog {
  background: white;
  border-radius: 12px;
  padding: 24px;
  width: 480px;
  max-width: 90%;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}

.user-input-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 16px;
  color: #303133;
}

.user-input-content {
  margin-bottom: 20px;
}

.input-message {
  color: #606266;
  margin-bottom: 16px;
}

.input-form .el-form-item {
  margin-bottom: 12px;
}

.user-input-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

/* 需要用户提供信息 - 整体区块 */
.node-user-input-wrap {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 10px 14px 12px;
  background: #fdf6ec;
  border-left: 3px solid #e6a23c;
  border-radius: 6px;
  font-size: 0.875rem;
}

/* 标题行：单行紧凑，不撑高 */
.user-input-header-line {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
  line-height: 1.4;
  min-height: unset;
}

.user-input-icon {
  flex-shrink: 0;
  color: #e6a23c;
  font-size: 1rem;
}

.user-input-title {
  color: #92400e;
  font-weight: 500;
  white-space: nowrap;
}

.user-input-tag {
  flex-shrink: 0;
  background: #fef3c7 !important;
  color: #92400e;
  font-size: 0.75rem;
  padding: 2px 6px;
  border-radius: 4px;
}

/* 说明文案：紧凑一行或两行 */
.user-input-desc {
  color: #606266;
  font-size: 0.8125rem;
  margin: 6px 0 10px 0;
  padding: 0;
  line-height: 1.4;
}

.input-waiting-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #909399;
  font-size: 13px;
  padding-left: 24px;
  margin-top: 8px;
}

/* 内联输入表单 - 紧凑排版 */
.inline-input-form {
  padding: 10px 12px;
  background: #fff;
  border-radius: 6px;
  border: 1px solid #fde68a;
  margin-top: 2px;
}

.inline-form {
  --el-form-item-margin-bottom: 8px;
}

.inline-form .el-form-item.inline-form-item {
  margin-bottom: 8px;
}

.inline-form .el-form-item:last-child {
  margin-bottom: 0;
}

.inline-form .el-form-item__label {
  font-size: 0.8125rem;
  color: #606266;
  line-height: 1.3;
  padding-bottom: 2px;
}

.inline-form .el-input__wrapper {
  min-height: 28px;
  padding: 0 8px;
}

.inline-input-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
  padding-top: 4px;
}
</style>
