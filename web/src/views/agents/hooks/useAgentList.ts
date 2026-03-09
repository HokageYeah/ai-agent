import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getAgentList } from '@/api/modules/agents'
import type { AgentInfo } from '@/types/agent'

export function useAgentList() {
  const agents = ref<AgentInfo[]>([])
  const selectedAgent = ref<AgentInfo | null>(null)
  const loadingAgents = ref<boolean>(false)

  /**
   * 加载所有可用 Agent 列表
   */
  async function loadAgents(): Promise<void> {
    loadingAgents.value = true
    try {
      agents.value = await getAgentList()
      console.log('[useAgentList] 已加载 Agent 列表，数量:', agents.value.length)
    } catch (error) {
      console.error('[useAgentList] 加载 Agent 列表失败:', error)
      ElMessage.error('加载 Agent 列表失败')
    } finally {
      loadingAgents.value = false
    }
  }

  /**
   * 选择一个 Agent (UI 逻辑重置等由外部调用者处理)
   */
  function selectAgent(agent: AgentInfo): void {
    selectedAgent.value = agent
    console.log('[useAgentList] 已选择 Agent:', agent.agent_id)
  }

  return {
    agents,
    selectedAgent,
    loadingAgents,
    loadAgents,
    selectAgent
  }
}
