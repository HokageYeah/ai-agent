import { ref, computed, nextTick, type Ref } from 'vue'
import type { StreamEvent, TrajectoryNode } from '@/types/stream'
import type { AgentInfo } from '@/types/agent'

export function useTrajectory(options: {
  streamEvents: Ref<StreamEvent[]>
  selectedAgent: Ref<AgentInfo | null>
}) {
  const streamEventsContainer = ref<HTMLElement | null>(null)
  const userAtBottom = ref(true)
  const SCROLL_BOTTOM_THRESHOLD = 60

  function onTrajectoryScroll(e: Event) {
    const el = e.target as HTMLElement
    if (!el || el !== streamEventsContainer.value) return
    const { scrollTop, clientHeight, scrollHeight } = el
    userAtBottom.value = scrollTop + clientHeight >= scrollHeight - SCROLL_BOTTOM_THRESHOLD
  }

  const showScrollToBottomButton = computed(() => options.streamEvents.value.length > 0 && !userAtBottom.value)

  function scrollToLatestEvent() {
    nextTick(() => {
      if (streamEventsContainer.value) {
        streamEventsContainer.value.scrollTop = streamEventsContainer.value.scrollHeight
        userAtBottom.value = true
      }
    })
  }

  function autoScroll() {
    if (userAtBottom.value) {
      scrollToLatestEvent()
    }
  }

  const expansionState = ref<Record<string, boolean>>({})

  function toggleExpansion(key: string) {
    expansionState.value[key] = !expansionState.value[key]
  }

  // 辅助函数：为一个节点本身及其所属迭代组自动设置展开
  function ensureExpanded(id: string) {
    if (expansionState.value[id] === undefined) {
      expansionState.value[id] = true
    }
  }

  /**
   * 将流式事件直接转换为一棵纯缩进的 TrajectoryNode 树。
   * Level 0: 迭代 (Iteration)
   * Level 1: 核心阶段 (Phases: planning, executing, reflecting)
   * Level 2: 动作层 (Events/Actions: tools, delegates, configs)
   * Level 3+: 子 Agent 内部
   */
  const trajectoryTree = computed<TrajectoryNode[]>(() => {
    const list = options.streamEvents.value
    const tree: TrajectoryNode[] = []
    
    // 用于快速通过 Iteration 获取父节点
    const iterNodes = new Map<number, TrajectoryNode>()
    
    // 状态机记录
    let currentPhaseNode: TrajectoryNode | null = null
    let currentSubAgentNodeStack: TrajectoryNode[] = [] // 允许子Agent嵌套
    let lastMasterIteration = 0

    const getPhaseTitle = (eventPhase: string) => {
      if (eventPhase.includes('plan')) return '🤔 规划与推理'
      if (eventPhase.includes('reflect')) return '💡 反思与总结'
      return '⚡️ 执行阶段'
    }

    const getPhaseId = (iter: number, phase: string) => {
      if (phase.includes('plan')) return `phase-${iter}-plan`
      if (phase.includes('reflect')) return `phase-${iter}-reflect`
      return `phase-${iter}-execute`
    }

    for (let i = 0; i < list.length; i++) {
        const ev = list[i]
        
        // 修正 Iteration 偏移
        let actualIteration = ev.iteration ?? lastMasterIteration ?? 0
        if (ev.event === 'sub_agent_start' || ev.event === 'sub_agent_end' || ev.data?.is_sub_agent) {
          actualIteration = lastMasterIteration
        } else {
          if (['final_answer', 'complete'].includes(ev.event) && actualIteration > 0) {
            actualIteration = actualIteration - 1
          } else {
            lastMasterIteration = actualIteration
          }
        }

        // 1. 确保 Iteration (Level 0) 存在
        if (!iterNodes.has(actualIteration)) {
            const iterId = `iter-${actualIteration}`
            const iterNode: TrajectoryNode = {
               id: iterId,
               level: 0,
               type: 'iteration',
               title: `> 迭代回合 ${actualIteration + 1} (Iteration ${actualIteration})`,
               isParent: true,
               isExpanded: true,
               children: [] as TrajectoryNode[]
            }
            ensureExpanded(iterId)
            iterNodes.set(actualIteration, iterNode)
            tree.push(iterNode)
            currentPhaseNode = null // 换迭代了清除阶段
            currentSubAgentNodeStack = [] // 清除栈
        }

        const iterParent = iterNodes.get(actualIteration)!

        // 计算基础 Level 偏移 (主 Agent 的动作在 Level 2，子 Agent 则逐级加深)
        const baseLevel = 1 + currentSubAgentNodeStack.length * 2
        
        // --- 处理各种事件类型 ---

        // 如果是一个阶段的开始或结束，创建 Phase (Level 1)
        if (['plan_start', 'step_start', 'reflection_start'].includes(ev.event) && currentSubAgentNodeStack.length === 0) {
            const phaseId = getPhaseId(actualIteration, ev.event)
            // 避免重复阶段
            if (!currentPhaseNode || currentPhaseNode.id !== phaseId) {
                currentPhaseNode = {
                    id: phaseId,
                    level: 1,
                    type: 'phase',
                    title: `> ${getPhaseTitle(ev.event)}`,
                    isParent: true,
                    isExpanded: true,
                    children: [] as TrajectoryNode[]
                }
                ensureExpanded(phaseId)
                iterParent.children!.push(currentPhaseNode)
            }
            continue // 阶段开始节点本身不需要作为一个叶子展示，除非需要展示描述，这里作为父节点
        }

        // 决定这一项事件要被放到哪个父节点的 children 里
        const targetParentList = currentSubAgentNodeStack.length > 0 
                               ? currentSubAgentNodeStack[currentSubAgentNodeStack.length - 1].children!
                               : (currentPhaseNode ? currentPhaseNode.children! : iterParent.children!)
                               
        const actionLevel = currentSubAgentNodeStack.length > 0 ? baseLevel + 1 : 2

        // 子 Agent 开始
        if (ev.event === 'sub_agent_start') {
            const subId = `sub-${actualIteration}-${ev.data?.sub_agent_id || i}`
            const subNode: TrajectoryNode = {
                id: subId,
                level: actionLevel,
                type: 'sub_agent',
                title: ev.data?.sub_agent_name || '子Agent',
                isParent: true,
                isExpanded: true,
                event: ev,
                children: [] as TrajectoryNode[]
            }
            ensureExpanded(subId)
            targetParentList.push(subNode)
            currentSubAgentNodeStack.push(subNode) // 入栈
            continue
        }

        // 子 Agent 结束
        if (ev.event === 'sub_agent_end') {
            if (currentSubAgentNodeStack.length > 0) {
                currentSubAgentNodeStack.pop() // 出栈
            }
            continue
        }

        // 推理文本长块: Plan Complete 带来推理文本 和 步骤
        if (ev.event === 'plan_complete') {
            if (ev.data?.reasoning) {
               targetParentList.push({
                   id: `reasoning-${actualIteration}-${i}`,
                   level: actionLevel,
                   type: 'reasoning',
                   isParent: false,
                   isExpanded: false,
                   event: ev
               })
            }
            continue
        }

        // 遇到需要重试的 reflection 失败报错 (生成一个飘红错误块，无需放入栈中改变流)
        if (ev.event === 'reflection_complete') {
             targetParentList.push({
                 id: `reflect-${actualIteration}-${i}`,
                 level: actionLevel,
                 type: ev.data?.needs_replanning ? 'error_replan' : 'reflection',
                 isParent: false,
                 isExpanded: false,
                 event: ev
             })
             continue
        }

        // 需要用户确认
        if (ev.event === 'user_confirm_required') {
            targetParentList.push({
                 id: `confirm-${actualIteration}-${i}`,
                 level: actionLevel,
                 type: 'confirm',
                 isParent: false,
                 isExpanded: false,
                 event: ev
            })
            continue
        }

        // 需要用户提供额外信息（如 SMTP 配置）
        if (ev.event === 'await_user_input') {
            targetParentList.push({
                 id: `user-input-${actualIteration}-${i}`,
                 level: actionLevel,
                 type: 'user_input',
                 isParent: false,
                 isExpanded: false,
                 event: ev
            })
            continue
        }

        // 默认将工具调用、子节点调用、最终答案作为 Action 叶子节点
        if (['tool_complete', 'skill_complete', 'delegate_complete', 'final_answer', 'step_error', 'error'].includes(ev.event)) {
             targetParentList.push({
                 id: `action-${actualIteration}-${i}`,
                 level: actionLevel,
                 type: 'action',
                 isParent: false,
                 isExpanded: false,
                 event: ev
             })
        }
        
        // 步骤完成：展示步骤执行结果
        if (ev.event === 'step_complete') {
             targetParentList.push({
                 id: `step-${actualIteration}-${i}`,
                 level: actionLevel,
                 type: 'action',
                 isParent: false,
                 isExpanded: false,
                 event: ev
             })
        }
    }

    return tree
  })

  // 将深林展开成一个单层的列表，配合 expansionState 决定 visible
  const visibleNodes = computed<TrajectoryNode[]>(() => {
    const result: TrajectoryNode[] = []
    
    // 递归拍平
    const traverse = (nodes: TrajectoryNode[]) => {
      for (const node of nodes) {
         // 同步最新折叠状态到 node 上
         const expanded = expansionState.value[node.id] ?? true
         node.isExpanded = expanded
         result.push(node)
         
         if (node.isParent && node.children && expanded) {
            traverse(node.children)
         }
      }
    }

    traverse(trajectoryTree.value)
    return result
  })

  return {
    streamEventsContainer,
    userAtBottom,
    showScrollToBottomButton,
    onTrajectoryScroll,
    scrollToLatestEvent,
    autoScroll,
    expansionState,
    toggleExpansion,
    visibleNodes // <- 前端页面将只遍历这个列表
  }
}
