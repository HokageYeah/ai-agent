import { ref, computed, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { executeAgentStream, confirmAgentAction } from '@/api/modules/agents'
import type { AgentInfo, AgentExecuteResponse } from '@/types/agent'
import type { StreamEvent, ExecutionPhase, ParsedExecuteResult } from '@/types/stream'

export function useAgentStream(options: { 
  selectedAgent: Ref<AgentInfo | null>
  taskInput: Ref<string>
  conversationId: Ref<string>
  onStreamEvent?: (event: StreamEvent) => void 
}) {
  const executing = ref<boolean>(false)
  const isStreaming = ref<boolean>(false)
  const executeResult = ref<AgentExecuteResponse | null>(null)
  const executeError = ref<string>('')
  
  const streamEvents = ref<StreamEvent[]>([])
  const currentStreamEvent = ref<StreamEvent | null>(null)
  
  // 危险操作确认相关的状态 (用户授权写文件等)
  const confirmLoading = ref<string | null>(null)
  const confirmedIds = ref<string[]>([])
  const confirmActionMap = ref<Record<string, 'confirm' | 'reject'>>({})

  // 进度指示器
  const currentPhase = computed<ExecutionPhase>(() => {
    if (!currentStreamEvent.value) return 'idle'
    const event = currentStreamEvent.value.event
    if (event === 'complete') return 'completed'
    if (['plan_start', 'plan_complete'].includes(event)) return 'planning'
    if (['step_start', 'tool_complete', 'skill_complete', 'delegate_complete', 'step_complete', 'execute_complete'].includes(event)) return 'executing'
    if (['reflection_start', 'reflection_complete'].includes(event)) return 'reflecting'
    return 'planning'
  })

  const progressPercent = computed<number>(() => {
    switch (currentPhase.value) {
      case 'idle': return 0
      case 'planning': return 20
      case 'executing': return 50
      case 'reflecting': return 80
      case 'completed': return 100
      default: return 0
    }
  })

  const parsedResult = computed<ParsedExecuteResult | null>(() => {
    if (!executeResult.value || !executeResult.value.result) return null
    return executeResult.value.result as ParsedExecuteResult
  })

  // 处理单个流事件的核心分发
  function handleStreamEvent(event: StreamEvent) {
    if (options.onStreamEvent) {
      options.onStreamEvent(event)
    }

    streamEvents.value.push(event)
    currentStreamEvent.value = event

    switch (event.event) {
      case 'user_confirm_result':
        confirmLoading.value = null
        break
      case 'complete': {
        executing.value = false
        isStreaming.value = false
        // 捕获 final_answer 以还原给 executeResult
        const finalAnswerEvent = streamEvents.value.find(e => e.event === 'final_answer')
        if (finalAnswerEvent) {
          const stepResultEvents = streamEvents.value
            .filter(e => ['tool_complete', 'skill_complete', 'delegate_complete', 'step_complete'].includes(e.event))
            .map(e => e.data)
          
          executeResult.value = {
             agent_id: options.selectedAgent.value?.agent_id || '',
             agent_name: options.selectedAgent.value?.name || '',
             task: options.taskInput.value,
             result: {
               ...finalAnswerEvent.data,
               step_results: stepResultEvents
             },
             iterations: event.data?.iterations ?? event.iteration,
             success: event.data?.success ?? true,
             messages: streamEvents.value.map(e => ({
               role: 'system',
               type: e.event,
               content: JSON.stringify(e.data || {})
             }))
          } as AgentExecuteResponse
        }
        ElMessage.success('Agent 执行完成！')
        break
      }
      case 'error':
        executing.value = false
        isStreaming.value = false
        executeError.value = event.error || '执行出错'
        ElMessage.error('Agent 执行出错: ' + (event.error || '未知错误'))
        break
    }
  }

  async function handleConfirm(confirmId: string | undefined, action: 'confirm' | 'reject') {
    if (!confirmId || confirmedIds.value.includes(confirmId)) return

    confirmedIds.value = [...confirmedIds.value, confirmId]
    confirmActionMap.value = { ...confirmActionMap.value, [confirmId]: action }
    confirmLoading.value = confirmId

    try {
      await confirmAgentAction(confirmId, action)
      ElMessage.success(action === 'confirm' ? '✅ 已确认操作' : '❌ 已拒绝操作')
    } catch (error) {
      ElMessage.error('确认操作失败' + (error instanceof Error ? error.message : ''))
      confirmLoading.value = null
      confirmedIds.value = confirmedIds.value.filter(id => id !== confirmId)
      delete confirmActionMap.value[confirmId]
    }
  }

  async function handleExecute() {
    if (!options.selectedAgent.value || !options.taskInput.value.trim()) return

    executing.value = true
    isStreaming.value = true
    executeResult.value = null
    executeError.value = ''
    streamEvents.value = []
    currentStreamEvent.value = null
    confirmLoading.value = null
    confirmedIds.value = []
    confirmActionMap.value = {}

    try {
      executeAgentStream(
        options.selectedAgent.value.agent_id,
        {
          task: options.taskInput.value,
          conversation_id: options.conversationId.value.trim() || undefined,
        },
        handleStreamEvent,
        (error) => {
          executing.value = false
          isStreaming.value = false
          executeError.value = error?.message || '流式执行失败'
          ElMessage.error('执行失败: ' + executeError.value)
        },
        () => {}
      )
    } catch (error) {
       executing.value = false
       isStreaming.value = false
       executeError.value = error instanceof Error ? error.message : '执行失败'
    }
  }

  function getStreamStatusText(): string {
    if (!isStreaming.value) return ''
    const event = currentStreamEvent.value
    if (!event) return '正在连接...'

    switch (event.event) {
      case 'plan_start':      return `🧠 制定计划... (迭代 ${event.iteration + 1})`
      case 'plan_complete':   return `✅ 计划制定完成`
      case 'step_start':      return `⚙️ 开始执行计划，共 ${event.step_total || 0} 个步骤`
      case 'tool_complete':   return `🔧 工具调用完成: ${event.data?.tool_name || 'unknown'}`
      case 'skill_complete':  return `✨ 技能调用完成: ${event.data?.skill_id || 'unknown'}`
      case 'delegate_complete': return `🤖 子Agent完成: ${event.data?.agent_id || 'unknown'}`
      case 'execute_complete':  return `✅ 执行阶段完成`
      case 'reflection_start':  return `🔍 正在自我反思评估...`
      case 'reflection_complete': return event.data?.needs_replanning ? '⚠️ 准备重新规划' : '💭 反思完成'
      case 'final_answer':    return '🎯 生成最终答案...'
      case 'complete':        return '✅ 执行完毕'
      case 'step_error':      return `⚠️ 步骤执行失败`
      case 'error':           return `❌ 发生错误`
      case 'error_analysis_start': return `🔍 正在分析错误...`
      case 'error_analysis': return `🔍 错误分析完成`
      case 'user_confirm_required': return `⚠️ 需要用户确认`
      case 'user_confirm_result': return `✅ 用户确认结果`
      case 'sub_agent_start': return `🤖 子Agent开始: ${event.data?.sub_agent_name || 'unknown'}`
      case 'sub_agent_end': return `🤖 子Agent完成: ${event.data?.sub_agent_name || 'unknown'}`
      default:                return `处理中...`
    }
  }

  return {
    executing,
    isStreaming,
    executeResult,
    executeError,
    streamEvents,
    currentStreamEvent,
    confirmLoading,
    confirmedIds,
    confirmActionMap,
    currentPhase,
    progressPercent,
    parsedResult,
    handleExecute,
    handleConfirm,
    getStreamStatusText
  }
}
