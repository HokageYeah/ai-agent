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
          <el-alert
            title="Agent 使用说明"
            type="info"
            show-icon
            :closable="false"
            style="margin-bottom: 2px;"
          >
            <p style="margin: 4px 0 0 0; line-height: 1.5; font-size: 0.8rem;">
              Agent 能够基于选定的专家角色，对您输入的任务进行<strong>自主规划（Planning）</strong>需要的工具和技能，逐步<strong>执行（Execution）</strong>，并进行<strong>自我反思（Reflection）</strong>来检验目标是否完成。
              <br/>
              <strong>操作指南：</strong>在下方输入需要解决的复杂问题，点击执行即可观测大模型的自动化思维与行为闭环。
            </p>
          </el-alert>
          
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
            <div style="display: flex; justify-content: space-between; align-items: flex-end;">
              <label class="input-label">任务描述</label>
              <div class="quick-examples">
                <span class="example-tag example-tag-delegate" @click="setExample(1)">
                  {{ selectedAgent?.agent_id === 'general_agent' ? '示例 1：中英翻译' : '示例 1：订单详情' }}
                </span>
                <span class="example-tag example-tag-delegate" @click="setExample(2)">
                  {{ selectedAgent?.agent_id === 'general_agent' ? '示例 2：网络查询' : '示例 2：客户订单' }}
                </span>
                <span class="example-tag example-tag-delegate" @click="setExample(3)">
                  {{ selectedAgent?.agent_id === 'general_agent' ? '示例 3：代码生成' : '示例 3：数据分析' }}
                </span>
              </div>
            </div>
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

          <!-- 执行轨迹 (详情) -->
          <div class="trajectory-section" v-if="executeResult">
            <div class="trajectory-header">
              <el-icon><DataLine /></el-icon>
              <span>Agent 思考与执行轨迹</span>
            </div>
            
            <el-timeline style="margin-top: 20px;">
              <!-- Message列表 -->
              <el-timeline-item
                v-for="(msg, index) in executeResult?.messages || []"
                :key="'msg-'+index"
                type="info"
                :hollow="true"
                size="large"
              >
                <div class="trajectory-content card-base" style="margin-top: 0;">
                  <div style="margin-bottom: 8px; font-weight: 600;">
                    <el-tag size="small" type="info">系统日志</el-tag>
                    <span style="font-size: 0.8rem; color: var(--color-text-muted); margin-left: 8px;">{{ msg.type }}</span>
                  </div>
                  <div style="font-size: 0.9rem;" class="trajectory-result-block">
                     <MarkdownRenderer v-if="typeof msg.content === 'string'" :content="msg.content" />
                     <div v-else>{{ msg.content }}</div>
                  </div>
                </div>
              </el-timeline-item>

              <!-- 执行步骤展示 -->
              <template v-for="(step, index) in parsedResult?.step_results || []" :key="'step-'+index">
                <el-timeline-item
                  v-if="step.action !== 'final_answer'"
                  :type="step.success ? 'primary' : 'danger'"
                  :hollow="true"
                  size="large"
                >
                  <div class="trajectory-content card-base" style="margin-top: 0;">
                    <div style="margin-bottom: 8px; font-weight: 600; display: flex; align-items: center; justify-content: space-between;">
                      <span v-if="step.action === 'tool'"><el-tag size="small" type="success">调用工具: {{ step.tool_name }}</el-tag></span>
                      <span v-else-if="step.action === 'skill'"><el-tag size="small" type="warning">使用技能: {{ step.skill_id }}</el-tag></span>
                      <span v-else-if="step.action === 'delegate'">
                        <el-tag size="small" type="primary" effect="plain">
                          🤖 委派子Agent: {{ step.agent_id || step.result?.agent_id || step.result?.agent_name || '子Agent' }}
                        </el-tag>
                      </span>
                      <span v-else><el-tag size="small">{{ step.action || '执行步骤' }}</el-tag></span>
                      
                      <span v-if="!step.success" style="color: var(--el-color-danger); font-size: 0.8rem;">执行异常</span>
                    </div>

                    <!-- delegate 步骤专属展示 -->
                    <template v-if="step.action === 'delegate'">
                      <div v-if="!step.success" class="trajectory-result-block delegate-error-block">
                        <el-icon style="color:var(--el-color-danger); margin-right:4px"><WarningFilled /></el-icon>
                        <span style="color:var(--el-color-danger)">{{ step.result?.error || step.error || '子Agent执行失败' }}</span>
                      </div>
                      <div v-else class="trajectory-result-block delegate-result-block">
                        <div class="delegate-agent-badge">
                          <el-icon style="margin-right:4px"><User /></el-icon>
                          {{ step.result?.agent_name || step.agent_id || '子Agent' }} 执行轨迹
                        </div>
                        
                        <!-- 嵌套渲染子 Agent 的 step_results -->
                        <div v-if="step.result?.step_results && step.result.step_results.length > 0" class="delegate-sub-steps" style="margin-top: 12px; padding: 12px; background: var(--color-bg-primary); border-left: 3px solid var(--el-color-primary-light-5); border-radius: 4px;">
                           <div v-for="(subStep, sIdx) in step.result.step_results" :key="'sub-' + sIdx" style="margin-bottom: 12px; font-size: 0.85rem;">
                              <div style="font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between;">
                                <span>
                                  <span v-if="subStep.action === 'tool'"><el-tag size="small" type="success">调用工具: {{ subStep.tool_name }}</el-tag></span>
                                  <span v-else-if="subStep.action === 'skill'"><el-tag size="small" type="warning">使用技能: {{ subStep.skill_id }}</el-tag></span>
                                  <span v-else-if="subStep.action === 'delegate'"><el-tag size="small" type="primary" effect="plain">委派孙Agent: {{ subStep.agent_id || subStep.result?.agent_name || '未知' }}</el-tag></span>
                                  <span v-else-if="subStep.action === 'final_answer'"><el-tag size="small" type="info" effect="dark">合成答案</el-tag></span>
                                  <span v-else><el-tag size="small">{{ subStep.action || '执行步骤' }}</el-tag></span>
                                </span>
                                <span v-if="!subStep.success" style="color: var(--el-color-danger); font-size: 0.75rem;">失败</span>
                              </div>
                              <div style="padding: 8px 10px; background: var(--color-bg-secondary); border-radius: 4px; border: 1px solid var(--color-border-light);">
                                <MarkdownRenderer v-if="typeof subStep.result === 'string'" :content="subStep.result" />
                                <div v-else-if="subStep.result?.error" style="color: var(--el-color-danger)">{{ subStep.result.error }}</div>
                                <MarkdownRenderer v-else :content="'```json\n' + JSON.stringify(subStep.result?.result ?? subStep.result, null, 2) + '\n```'" />
                              </div>
                           </div>
                           
                           <!-- 子 Agent 反思结果 -->
                           <div v-if="step.result.reflection" style="margin-top: 12px; padding: 10px; background: var(--color-warning-light-9); border-radius: 4px; border: 1px dashed var(--el-color-warning-light-5);">
                             <div style="font-size: 0.8rem; font-weight: 600; margin-bottom: 6px; color: var(--el-color-warning-dark-2);">
                               自我反思 ({{ step.result.reflection.success ? '成功' : '存在短板' }})
                             </div>
                             <div style="font-size: 0.85rem; color: var(--color-text-primary);">{{ step.result.reflection.summary }}</div>
                           </div>
                        </div>

                        <!-- 子 Agent 最终结论 -->
                        <div style="margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--color-border-light);">
                          <div style="font-size: 0.85rem; font-weight: 600; margin-bottom: 8px; color: var(--color-text-secondary);">最终结论：</div>
                          <div style="font-size: 0.95rem;">
                            <MarkdownRenderer v-if="typeof step.result?.result === 'string'" :content="step.result.result" />
                            <MarkdownRenderer v-else :content="'```json\n' + JSON.stringify(step.result?.result ?? step.result, null, 2) + '\n```'" />
                          </div>
                        </div>
                      </div>
                    </template>

                    <!-- 渲染工具/技能返回的复杂数据或普通文本 -->
                    <div v-else class="trajectory-result-block" style="background: var(--color-bg-secondary); padding: 12px; border-radius: 8px;">
                      <MarkdownRenderer v-if="typeof step.result === 'string'" :content="step.result" />
                      <!-- 如果是对象，格式化输出。或者有专门的 error 则展示 error -->
                      <div v-else-if="step.result?.error" style="color: var(--el-color-danger)">
                        {{ step.result.error }}
                      </div>
                      <MarkdownRenderer v-else :content="'```json\n' + JSON.stringify(step.result, null, 2) + '\n```'" />
                    </div>
                  </div>
                </el-timeline-item>
              </template>

              <!-- 反思节点展示 -->
              <el-timeline-item
                v-if="parsedResult?.reflection"
                type="warning"
                :hollow="true"
                size="large"
              >
                <div class="trajectory-content card-base" style="margin-top: 0; background: var(--color-warning-light-9);">
                  <div style="margin-bottom: 8px; font-weight: 600;">
                    <el-tag size="small" type="warning">自我反思 (Reflection)</el-tag>
                    <el-tag size="small" :type="parsedResult.reflection.success ? 'success' : 'danger'" style="margin-left: 8px;">
                      总结论: {{ parsedResult.reflection.success ? '✅ 任务完成' : '❌ 存在短板' }}
                    </el-tag>
                  </div>
                  <div style="font-size: 0.9rem; margin-bottom: 8px;">
                    <strong>分析反馈：</strong>{{ parsedResult.reflection.feedback }}
                  </div>
                  <div style="font-size: 0.9rem;">
                    <strong>最终总结：</strong>{{ parsedResult.reflection.summary }}
                  </div>
                </div>
              </el-timeline-item>

              <!-- 最终结果展示 -->
              <el-timeline-item
                v-if="finalResult"
                type="success"
                size="large"
              >
                <div class="trajectory-content card-base" style="margin-top: 0; background: var(--color-success-light-9); border: 1px solid var(--color-success-light-5);">
                  <div style="margin-bottom: 8px; font-weight: 600;">
                    <el-tag size="small" type="success" effect="dark">最终结果 (Final Answer)</el-tag>
                  </div>
                  <div class="trajectory-result-block" style="font-size: 1rem; color: var(--color-text-primary);">
                    <MarkdownRenderer :content="finalResult" />
                  </div>
                </div>
              </el-timeline-item>
            </el-timeline>
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
import { ref, onMounted, computed } from 'vue'
import { Setting, Refresh, CaretRight, DataLine, WarningFilled, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getAgentList, executeAgent } from '@/api/modules/agents'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import type { AgentInfo, AgentExecuteResponse } from '@/types/agent'

// 为更复杂的执行结果定义内部便捷接口以在模板中使用
interface StepResult {
  action: string;
  success: boolean;
  tool_name?: string;
  skill_id?: string;
  agent_id?: string;
  error?: string;
  result: any;
}

interface ReflectionResult {
  success: boolean;
  needs_replanning: boolean;
  feedback: string;
  summary: string;
}

interface ParsedExecuteResult {
  step_results?: StepResult[];
  reflection?: ReflectionResult;
  [key: string]: any;
}

const agents = ref<AgentInfo[]>([])
const selectedAgent = ref<AgentInfo | null>(null)
const loadingAgents = ref<boolean>(false)
const taskInput = ref<string>('')
const executing = ref<boolean>(false)
const executeResult = ref<AgentExecuteResponse | null>(null)
const executeError = ref<string>('')

// 对执行结果增加强类型转换（用于 Template 解析展示）
const parsedResult = computed<ParsedExecuteResult | null>(() => {
  if (!executeResult.value || !executeResult.value.result) return null
  return executeResult.value.result as ParsedExecuteResult
})

// 计算最终结果
const finalResult = computed<string>(() => {
  if (!parsedResult.value) return ''
  if (typeof parsedResult.value.result === 'string') {
    return parsedResult.value.result
  }
  if (parsedResult.value.step_results) {
    const finalStep = parsedResult.value.step_results.find(s => s.action === 'final_answer')
    if (finalStep && typeof finalStep.result === 'string') {
      return finalStep.result
    }
  }
  return ''
})

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

// 根据当前选中的 Agent，分别给出最合适的示例任务
// 数据库测试数据覆盖订单 1001-1010（含客户、商品、退款信息）
const EXAMPLE_MAP: Record<number, Record<string, string>> = {
  // 示例1：查询单笔订单详情（已发货，覆盖 delegate 场景）
  1: {
    default:      '帮我查询订单号 1002 的详细情况，包括商品、客户和配送状态。',
    cs_master:    '帮我查询订单号 1002 的详细情况，包括商品、客户和配送状态。',
    order_agent:  '查询订单号 1002 的详细信息：买了什么商品、支付了多少、现在的配送状态是什么，物流单号是多少？',
    refund_agent: '查询订单号 1003 的退款进度，客户反馈已申请退款，请告知当前处理状态和退款金额。',
    general_agent: '请把这句话翻译成英文："人工智能正在以前所未有的速度改变我们的生活和工作方式。"',
  },
  // 示例2：查询某客户的所有订单
  2: {
    default:      '帮我查询客户"李娜"的所有订单记录，列出每笔订单的金额和当前状态。',
    cs_master:    '帮我查询客户"李娜"的所有订单，并汇总她的总消费金额。',
    order_agent:  '查询客户ID为2（李娜）的所有订单，统计她的订单总数、总金额，并列出每笔订单的商品名和状态。',
    refund_agent: '查询所有待审核的退款申请（status=pending），列出申请人、退款金额和退款原因，并按申请时间排序。',
    general_agent: '搜一下什么是 MCP (Model Context Protocol)，并用一段话向我通俗地解释一下。',
  },
  // 示例3：多表联查 + 数据分析
  3: {
    default:      '统计一下各种订单状态（待确认、已发货、已完成等）的订单数量和总金额分布，给出业务分析。',
    cs_master:    '统计各订单状态的数量分布，并找出金额最高的前3笔已完成订单，给我一份客服业务摘要报告。',
    order_agent:  '分析所有已发货但未签收的订单（status=shipped），列出订单号、客户、商品、物流单号，并评估是否有超时风险。',
    refund_agent: '统计所有退款记录的总退款金额，按退款状态分组，并分析退款原因分布，给出降低退款率的建议。',
    general_agent: '用 Python 写一个快速排序算法，并写出一段测试代码来验证它。',
  },
}

/**
 * 根据示例编号和当前选中的 Agent 设置快捷任务输入
 */
function setExample(num: number): void {
  const agentId = selectedAgent.value?.agent_id || 'default'
  const map = EXAMPLE_MAP[num] || {}
  taskInput.value = map[agentId] || map['default'] || ''
  console.log(`[AgentView] 设置示例 ${num}，Agent: ${agentId}，内容: ${taskInput.value}`)
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
function formatAgentResult(result: Record<string, any>): string {
  if (!result) return ''
  // 如果 API 最外层提供了 final_answer
  if (result.final_answer) {
    return String(result.final_answer)
  }
  // 如果是当前最新的结构，最终回答实际上在 result.result 里 （如 user 的 logs）
  if (result.result && typeof result.result === 'string') {
    return result.result
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
.example-tag-delegate {
  color: var(--el-color-primary);
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
}
.example-tag-delegate:hover {
  background: var(--el-color-primary-light-7);
}

/* 委派子Agent 步骤专属样式 */
.delegate-error-block {
  display: flex;
  align-items: center;
  background: var(--el-color-danger-light-9);
  border: 1px solid var(--el-color-danger-light-5);
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 0.9rem;
}
.delegate-result-block {
  background: var(--el-color-primary-light-9);
  border: 1px solid var(--el-color-primary-light-5);
  padding: 12px 16px;
  border-radius: 8px;
}
.delegate-agent-badge {
  display: inline-flex;
  align-items: center;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-8);
  padding: 3px 10px;
  border-radius: 20px;
}

/* 执行结果区域 */
.result-section { display: flex; flex-direction: column; gap: 12px; }
.result-header { display: flex; align-items: center; gap: 10px; }
.result-label { font-size: 0.875rem; font-weight: 600; color: var(--color-text-primary); }
.result-iterations { font-size: 0.75rem; color: var(--color-text-muted); margin-left: auto; }

.result-content {
  padding: 20px;
}

/* 轨迹展示区 */
.trajectory-section {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.trajectory-header {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  border-bottom: 1px solid var(--color-border-light);
  padding-bottom: 8px;
}

.trajectory-content {
  padding: 16px;
  font-size: 0.85rem;
  max-width: 100%;
  overflow-x: auto;
  line-height: 1.6;
}

.trajectory-result-block :deep(p:last-child) { 
  margin-bottom: 0; 
}
.trajectory-result-block :deep(pre) {
  margin: 8px 0;
}

/* 响应式布局：小屏幕下改为上下排列 */
@media screen and (max-width: 768px) {
  .agents-layout {
    flex-direction: column;
    overflow-y: auto;
  }
  .agent-list-panel {
    width: 100%;
    min-width: 100%;
    height: 200px;
    border-right: none;
    border-bottom: 1px solid var(--color-border);
  }
  .execution-panel {
    overflow: visible;
  }
}
</style>
