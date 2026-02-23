/**
 * 技能库相关 API 接口封装
 * 对接后端 /api/v1/skills 路由
 */
import { httpGet, httpPost } from '@/api/request'
import type {
  SkillInfo,
  SkillExecuteRequest,
  SkillExecuteResponse
} from '@/types/agent'

/**
 * 获取所有可用技能列表
 * GET /api/v1/skills
 */
export function getSkillList(): Promise<SkillInfo[]> {
  console.log('[Skills API] 获取技能列表')
  return httpGet<SkillInfo[]>('/skills')
}

/**
 * 执行指定技能
 * POST /api/v1/skills/{skill_id}/execute
 *
 * @param skillId - 技能 ID
 * @param data - 技能参数（根据技能 prompt_template 填写）
 */
export function executeSkill(skillId: string, data: SkillExecuteRequest): Promise<SkillExecuteResponse> {
  console.log('[Skills API] 执行技能，skillId:', skillId, '参数:', data.parameters)
  return httpPost<SkillExecuteResponse>(`/skills/${skillId}/execute`, data)
}
