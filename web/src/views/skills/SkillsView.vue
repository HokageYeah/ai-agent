<template>
  <div class="skills-view page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">技能库</h2>
        <p class="page-desc">数据分析、代码生成、文本写作、翻译等预置 AI 技能，直接调用跳过规划阶段</p>
      </div>
      <el-button :icon="Refresh" @click="loadSkills" :loading="loading" text>刷新</el-button>
    </div>

    <!-- 技能卡片网格 -->
    <div v-if="loading" class="skills-grid">
      <div v-for="i in 4" :key="i" class="skeleton" style="height:220px;border-radius:16px;"></div>
    </div>

    <div v-else class="skills-grid">
      <div
        v-for="skill in skills"
        :key="skill.skill_id"
        class="skill-card card-base"
        :class="{ active: selectedSkill?.skill_id === skill.skill_id }"
        @click="selectSkill(skill)"
      >
        <div class="skill-card-top">
          <div class="skill-icon" :style="{ background: getSkillColor(skill.skill_id) }">
            <el-icon :size="22" style="color:white"><MagicStick /></el-icon>
          </div>
          <div class="skill-meta">
            <span class="skill-name">{{ skill.name }}</span>
            <span class="skill-id-badge">{{ skill.skill_id }}</span>
          </div>
        </div>
        <p class="skill-desc">{{ skill.description }}</p>
        <div class="skill-tags">
          <span v-for="tag in skill.tags" :key="tag" class="skill-tag">{{ tag }}</span>
          <span v-for="tool in skill.required_tools.slice(0,2)" :key="tool" class="tool-tag">{{ tool }}</span>
        </div>
        <div class="skill-card-footer">
          <span class="tool-count" v-if="skill.required_tools.length > 0">
            需要 {{ skill.required_tools.length }} 个工具
          </span>
          <el-button size="small" type="primary" plain @click.stop="selectSkill(skill)">
            使用技能
          </el-button>
        </div>
      </div>
    </div>

    <!-- 执行弹窗 -->
    <el-dialog
      v-model="showExecuteDialog"
      :title="`执行技能：${selectedSkill?.name}`"
      width="580px"
      :close-on-click-modal="false"
      @close="resetDialog"
    >
      <div v-if="selectedSkill" class="execute-dialog-content">
        <div class="skill-summary">
          <div class="skill-summary-icon" :style="{ background: getSkillColor(selectedSkill.skill_id) }">
            <el-icon :size="20" style="color:white"><MagicStick /></el-icon>
          </div>
          <div>
            <div class="skill-summary-name">{{ selectedSkill.name }}</div>
            <div class="skill-summary-desc">{{ selectedSkill.description }}</div>
          </div>
        </div>

        <el-divider />

        <!-- 参数输入表单 -->
        <div class="params-form">
          <p class="params-tip">
            <el-icon><InfoFilled /></el-icon>
            请填写技能所需的参数，参数名对应技能模板中的占位变量
          </p>
          <div v-for="(param, key) in paramInputs" :key="key" class="param-row">
            <label class="param-label">{{ key }}</label>
            <el-input
              v-model="paramInputs[key]"
              type="textarea"
              :autosize="{ minRows: 1, maxRows: 4 }"
              :placeholder="`请输入 ${key} 的值...`"
            />
          </div>

          <!-- 自定义参数（如果预设列表不满足） -->
          <el-button text size="small" @click="showAddParam = !showAddParam" class="add-param-btn">
            + 添加自定义参数
          </el-button>
          <div v-if="showAddParam" class="custom-param-row">
            <el-input v-model="newParamKey" placeholder="参数名" size="small" style="width:140px" />
            <el-input v-model="newParamValue" placeholder="参数值" size="small" style="flex:1" />
            <el-button size="small" type="primary" @click="addCustomParam">添加</el-button>
          </div>
        </div>

        <!-- 执行结果 -->
        <div v-if="skillResult" class="skill-result">
          <div class="result-header-row">
            <span class="result-label">执行结果</span>
            <el-tag type="success" size="small">成功</el-tag>
          </div>
          <div class="result-box card-base">
            <MarkdownRenderer :content="skillResult.result.content || '（无内容返回）'" />
          </div>
        </div>

        <div v-if="skillError" class="skill-error">
          <el-alert :title="skillError" type="error" show-icon :closable="false" />
        </div>
      </div>

      <template #footer>
        <el-button @click="showExecuteDialog = false">取消</el-button>
        <el-button
          type="primary"
          :loading="executing"
          :disabled="!hasParams"
          @click="handleExecuteSkill"
        >
          {{ executing ? '执行中...' : '执行技能' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { MagicStick, Refresh, InfoFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getSkillList, executeSkill } from '@/api/modules/skills'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import type { SkillInfo, SkillExecuteResponse } from '@/types/agent'

const skills = ref<SkillInfo[]>([])
const loading = ref<boolean>(false)
const selectedSkill = ref<SkillInfo | null>(null)
const showExecuteDialog = ref<boolean>(false)
const executing = ref<boolean>(false)
const skillResult = ref<SkillExecuteResponse | null>(null)
const skillError = ref<string>('')
const showAddParam = ref<boolean>(false)
const newParamKey = ref<string>('')
const newParamValue = ref<string>('')

// 各技能的常用参数名映射（用于预生成参数输入字段）
const skillParamDefaults: Record<string, string[]> = {
  data_analysis: ['data'],
  code_generation: ['requirements', 'language', 'framework'],
  text_writing: ['topic', 'content_type', 'style', 'word_count'],
  translation: ['text', 'target_language'],
}

/** 动态参数输入字典 */
const paramInputs = ref<Record<string, string>>({})

/** 是否有至少一个非空参数 */
const hasParams = computed(() =>
  Object.values(paramInputs.value).some(v => v.trim() !== '')
)

/** 技能卡片颜色（根据 skill_id 区分颜色） */
function getSkillColor(skillId: string): string {
  const colors: Record<string, string> = {
    data_analysis: 'linear-gradient(135deg, #7c3aed, #8b5cf6)',
    code_generation: 'linear-gradient(135deg, #06b6d4, #0891b2)',
    text_writing: 'linear-gradient(135deg, #10b981, #059669)',
    translation: 'linear-gradient(135deg, #f59e0b, #d97706)',
  }
  return colors[skillId] || 'linear-gradient(135deg, #6366f1, #8b5cf6)'
}

/** 加载技能列表 */
async function loadSkills(): Promise<void> {
  loading.value = true
  try {
    skills.value = await getSkillList()
    console.log('[SkillsView] 已加载技能列表，数量:', skills.value.length)
  } catch (error) {
    console.error('[SkillsView] 加载技能列表失败:', error)
    ElMessage.error('加载技能列表失败')
  } finally {
    loading.value = false
  }
}

/** 选中技能，打开执行弹窗 */
function selectSkill(skill: SkillInfo): void {
  selectedSkill.value = skill
  skillResult.value = null
  skillError.value = ''

  // 根据技能 ID 预置参数字段
  const predefinedParams = skillParamDefaults[skill.skill_id] || []
  paramInputs.value = {}
  predefinedParams.forEach(key => {
    paramInputs.value[key] = ''
  })

  showExecuteDialog.value = true
  console.log('[SkillsView] 已选中技能:', skill.skill_id, '预置参数:', predefinedParams)
}

/** 添加自定义参数字段 */
function addCustomParam(): void {
  if (!newParamKey.value.trim()) {
    ElMessage.warning('参数名不能为空')
    return
  }
  paramInputs.value[newParamKey.value.trim()] = newParamValue.value
  newParamKey.value = ''
  newParamValue.value = ''
  showAddParam.value = false
}

/** 执行技能 */
async function handleExecuteSkill(): Promise<void> {
  if (!selectedSkill.value || !hasParams.value) return

  // 过滤空值参数
  const filteredParams: Record<string, string> = {}
  Object.entries(paramInputs.value).forEach(([k, v]) => {
    if (v.trim()) filteredParams[k] = v.trim()
  })

  executing.value = true
  skillResult.value = null
  skillError.value = ''

  try {
    const result = await executeSkill(selectedSkill.value.skill_id, { parameters: filteredParams })
    skillResult.value = result
    ElMessage.success('技能执行成功！')
    console.log('[SkillsView] 技能执行成功')
  } catch (error) {
    skillError.value = error instanceof Error ? error.message : '执行失败'
    console.error('[SkillsView] 技能执行失败:', error)
  } finally {
    executing.value = false
  }
}

/** 关闭弹窗时重置状态 */
function resetDialog(): void {
  skillResult.value = null
  skillError.value = ''
  showAddParam.value = false
}

onMounted(() => { loadSkills() })
</script>

<style scoped>
.skills-view { height: 100%; display: flex; flex-direction: column; overflow: hidden; }

.skills-grid {
  flex: 1;
  overflow-y: auto;
  padding: 0 24px 24px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  align-content: start;
}

.skill-card {
  padding: 20px;
  cursor: pointer;
  transition: all var(--transition-fast);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skill-card:hover, .skill-card.active {
  box-shadow: var(--shadow-lg);
  transform: translateY(-2px);
  border-color: var(--color-primary);
}

.skill-card-top {
  display: flex;
  align-items: center;
  gap: 12px;
}

.skill-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.skill-name {
  display: block;
  font-weight: 600;
  font-size: 0.95rem;
  color: var(--color-text-primary);
}

.skill-id-badge {
  display: inline-block;
  font-size: 0.65rem;
  font-family: var(--font-mono);
  color: var(--color-text-muted);
  background: var(--color-bg-secondary);
  padding: 1px 6px;
  border-radius: var(--radius-full);
  border: 1px solid var(--color-border);
  margin-top: 2px;
}

.skill-desc {
  font-size: 0.82rem;
  color: var(--color-text-secondary);
  line-height: 1.6;
  flex: 1;
}

.skill-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.skill-tag {
  font-size: 0.65rem;
  padding: 2px 8px;
  background: var(--color-primary-lighter);
  color: var(--color-primary-dark);
  border-radius: var(--radius-full);
}

.tool-tag {
  font-size: 0.65rem;
  padding: 2px 8px;
  background: var(--color-bg-secondary);
  color: var(--color-text-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  font-family: var(--font-mono);
}

.skill-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
}

.tool-count {
  font-size: 0.72rem;
  color: var(--color-text-muted);
}

/* 执行弹窗样式 */
.execute-dialog-content { display: flex; flex-direction: column; gap: 16px; }

.skill-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  background: var(--gradient-primary-soft);
  border-radius: var(--radius-md);
}

.skill-summary-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.skill-summary-name { font-weight: 600; color: var(--color-text-primary); font-size: 0.9rem; }
.skill-summary-desc { font-size: 0.78rem; color: var(--color-text-secondary); margin-top: 2px; }

.params-form { display: flex; flex-direction: column; gap: 12px; }
.params-tip {
  font-size: 0.78rem;
  color: var(--color-text-muted);
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--color-bg-secondary);
  padding: 8px 12px;
  border-radius: var(--radius-md);
}

.param-row { display: flex; flex-direction: column; gap: 4px; }
.param-label { font-size: 0.8rem; font-weight: 600; color: var(--color-text-secondary); font-family: var(--font-mono); }

.add-param-btn { align-self: flex-start; color: var(--color-primary); }
.custom-param-row { display: flex; gap: 8px; align-items: center; }

.skill-result { display: flex; flex-direction: column; gap: 10px; }
.result-header-row { display: flex; align-items: center; gap: 10px; }
.result-label { font-weight: 600; font-size: 0.875rem; color: var(--color-text-primary); }
.result-box { padding: 16px; max-height: 300px; overflow-y: auto; }
</style>
