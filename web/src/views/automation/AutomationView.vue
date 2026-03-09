<template>
  <div class="automation-view page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">自动化服务</h2>
        <p class="page-desc">选择自动化服务类型，输入任务参数后启动 AI 自动化处理流程</p>
      </div>
      <div class="header-actions">
        <el-button v-if="selectedService" :icon="ArrowLeft" @click="selectedService = null" text>返回</el-button>
        <el-button :icon="Refresh" @click="loadServices" :loading="loadingServices" text>刷新</el-button>
      </div>
    </div>

    <!-- 服务卡片网格（未选择服务时显示） -->
    <div v-if="!selectedService">
      <div v-if="loadingServices" class="services-grid">
        <div v-for="i in 3" :key="i" class="skeleton" style="height:200px;border-radius:16px;"></div>
      </div>

      <div v-else class="services-grid">
        <div
          v-for="service in services"
          :key="service.type"
          class="service-card card-base"
          :class="{ active: isServiceSelected(service) }"
          @click="selectService(service)"
        >
          <div class="service-card-top">
            <div class="service-icon" :style="{ background: service.color }">
              <el-icon :size="22" style="color:white">
                <component :is="getServiceIcon(service.icon)" />
              </el-icon>
            </div>
            <div class="service-meta">
              <span class="service-name">{{ service.name }}</span>
              <span class="service-type-badge">{{ service.type }}</span>
            </div>
          </div>
          <p class="service-desc">{{ service.description }}</p>
          <div class="service-card-footer">
            <span class="param-count">
              {{ Object.keys(service.param_schemas || {}).length }} 个参数
            </span>
            <el-button size="small" type="primary" plain @click.stop="selectService(service)">
              使用服务
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 执行面板（选择服务后显示） -->
    <div v-else class="execution-panel">
      <!-- 服务详情头部 -->
      <div class="selected-service-header">
        <div class="selected-service-icon" :style="{ background: selectedService.color }">
          <el-icon :size="24" style="color:white">
            <component :is="getServiceIcon(selectedService.icon)" />
          </el-icon>
        </div>
        <div>
          <div class="selected-service-name">{{ selectedService.name }}</div>
          <div class="selected-service-desc">{{ selectedService.description }}</div>
        </div>
      </div>

      <!-- 参数输入区 -->
      <div class="params-section">
        <p class="params-tip">
          <el-icon><InfoFilled /></el-icon>
          请填写服务所需的参数，点击示例可快速填入
        </p>

        <!-- 动态渲染参数表单 -->
        <div v-for="(schema, key) in selectedService.param_schemas" :key="key" class="param-row">
          <!-- 参数标签 -->
          <div class="param-label-row">
            <label class="param-label">
              {{ schema.label }}
              <span class="param-key-badge">{{ key }}</span>
            </label>
            <span v-if="schema.required" class="param-required-badge">必填</span>
          </div>

          <!-- 根据参数名渲染不同类型的输入框 -->
          <template v-if="key === 'processing_config' || key === 'report_config' || key === 'code_config'">
            <el-input
              v-model="paramInputs[key]"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              :placeholder="getParamPlaceholder(key, schema)"
              :disabled="executing"
            />
          </template>
          <template v-else-if="key === 'language'">
            <el-select
              v-model="paramInputs[key]"
              placeholder="选择编程语言"
              :disabled="executing"
              style="width: 100%"
            >
              <el-option label="Python" value="Python" />
              <el-option label="JavaScript" value="JavaScript" />
              <el-option label="TypeScript" value="TypeScript" />
              <el-option label="Java" value="Java" />
              <el-option label="Go" value="Go" />
              <el-option label="Rust" value="Rust" />
              <el-option label="C++" value="C++" />
            </el-select>
          </template>
          <template v-else>
            <el-input
              v-model="paramInputs[key]"
              type="textarea"
              :autosize="{ minRows: 3, maxRows: 8 }"
              :placeholder="getParamPlaceholder(key, schema)"
              :disabled="executing"
            />
          </template>

          <!-- 参数说明 -->
          <p class="param-desc">
            <el-icon style="font-size:12px"><QuestionFilled /></el-icon>
            {{ schema.description }}
          </p>

          <!-- 示例 pill -->
          <div v-if="schema.examples?.length" class="param-examples">
            <span class="param-examples-label">示例：</span>
            <span
              v-for="(example, idx) in schema.examples"
              :key="key + '-' + idx"
              class="param-example-pill"
              :title="example"
              @click="fillExample(key, example)"
            >
              {{ truncateExample(example) }}
            </span>
          </div>
        </div>

        <!-- 执行按钮 -->
        <el-button
          type="primary"
          size="large"
          :loading="executing"
          :disabled="!canExecute"
          :icon="CaretRight"
          @click="handleExecute"
          style="margin-top: 16px; width: 100%"
        >
          {{ executing ? '处理中...' : '开始执行' }}
        </el-button>
      </div>

      <!-- 执行结果展示 -->
      <div class="result-section" v-if="executeResult || executeError">
        <div class="result-header">
          <el-icon><Document /></el-icon>
          <span>执行结果</span>
        </div>

        <!-- 成功结果 -->
        <div v-if="executeResult" class="result-content card-base">
          <el-alert
            title="执行成功"
            type="success"
            show-icon
            :closable="false"
            style="margin-bottom: 12px;"
          />

          <!-- 返回的元数据信息 -->
          <div class="result-metadata">
            <el-descriptions :column="3" border size="small">
              <el-descriptions-item label="执行状态">
                <el-tag :type="executeResult.success ? 'success' : 'danger'" size="small">
                  {{ executeResult.success ? '成功' : '失败' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="处理时间" v-if="executeResult.processing_time">
                {{ executeResult.processing_time }}ms
              </el-descriptions-item>
              <el-descriptions-item label="模型" v-if="getResultField('model')">
                {{ getResultField('model') }}
              </el-descriptions-item>
              <el-descriptions-item label="错误信息" v-if="executeResult.error">
                <span style="color: var(--el-color-danger);">{{ executeResult.error }}</span>
              </el-descriptions-item>
            </el-descriptions>
          </div>

          <!-- 代码生成结果 -->
          <template v-if="selectedService?.type === 'code_generation'">
            <div class="result-info-cards">
              <el-card shadow="never" class="info-card">
                <template #header>
                  <span class="info-card-title">代码信息</span>
                </template>
                <el-descriptions :column="2" border size="small">
                  <el-descriptions-item label="语言">
                    <el-tag size="small">{{ getResultField('language') || '未指定' }}</el-tag>
                  </el-descriptions-item>
                  <el-descriptions-item label="框架">
                    {{ getResultField('framework') || '未指定' }}
                  </el-descriptions-item>
                </el-descriptions>
              </el-card>
              <el-card shadow="never" class="info-card" v-if="getResultField('usage')">
                <template #header>
                  <span class="info-card-title">Token 使用量</span>
                </template>
                <el-descriptions :column="3" border size="small">
                  <el-descriptions-item label="Prompt">{{ getResultField('usage.prompt_tokens') || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="Completion">{{ getResultField('usage.completion_tokens') || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="Total">{{ getResultField('usage.total_tokens') || '-' }}</el-descriptions-item>
                </el-descriptions>
              </el-card>
            </div>
            <div v-if="getResultField('code')" class="result-data">
              <MarkdownRenderer :content="getResultField('code')" />
            </div>
          </template>

          <!-- 报告生成结果 -->
          <template v-else-if="selectedService?.type === 'report_generation'">
            <div class="result-info-cards">
              <el-card shadow="never" class="info-card">
                <template #header>
                  <span class="info-card-title">报告信息</span>
                </template>
                <el-descriptions :column="2" border size="small">
                  <el-descriptions-item label="标题">{{ getResultField('title') || '未指定' }}</el-descriptions-item>
                  <el-descriptions-item label="格式">{{ getResultField('format') || 'markdown' }}</el-descriptions-item>
                </el-descriptions>
              </el-card>
              <el-card shadow="never" class="info-card" v-if="getResultField('usage')">
                <template #header>
                  <span class="info-card-title">Token 使用量</span>
                </template>
                <el-descriptions :column="3" border size="small">
                  <el-descriptions-item label="Prompt">{{ getResultField('usage.prompt_tokens') || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="Completion">{{ getResultField('usage.completion_tokens') || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="Total">{{ getResultField('usage.total_tokens') || '-' }}</el-descriptions-item>
                </el-descriptions>
              </el-card>
            </div>
            <div v-if="getResultField('report')" class="result-data">
              <MarkdownRenderer :content="getResultField('report')" />
            </div>
          </template>

          <!-- 数据处理结果 -->
          <template v-else-if="selectedService?.type === 'data_processing'">
            <el-card shadow="never" class="info-card" v-if="getResultField('usage')">
              <template #header>
                <span class="info-card-title">Token 使用量</span>
              </template>
              <el-descriptions :column="3" border size="small">
                <el-descriptions-item label="Prompt">{{ getResultField('usage.prompt_tokens') || '-' }}</el-descriptions-item>
                <el-descriptions-item label="Completion">{{ getResultField('usage.completion_tokens') || '-' }}</el-descriptions-item>
                <el-descriptions-item label="Total">{{ getResultField('usage.total_tokens') || '-' }}</el-descriptions-item>
              </el-descriptions>
            </el-card>
            <div v-if="getResultField('result')" class="result-data">
              <MarkdownRenderer :content="formatJsonResult(getResultField('result'))" />
            </div>
          </template>
        </div>

        <!-- 错误结果 -->
        <div v-if="executeError" class="error-content card-base">
          <el-alert
            :title="executeError"
            type="error"
            show-icon
            :closable="false"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, markRaw } from 'vue'
import { Refresh, CaretRight, Document, InfoFilled, QuestionFilled, DataAnalysis, Reading, Notebook, ArrowLeft } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getAutomationServices, dataProcessing, reportGeneration, codeGeneration } from '@/api/modules/automation'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import type { AutomationServiceInfo, AutomationResponse } from '@/types/automation'

// 图标组件映射
const iconMap: Record<string, any> = {
  DataAnalysis: markRaw(DataAnalysis),
  Reading: markRaw(Reading),
  Notebook: markRaw(Notebook),
}

// 获取服务图标
function getServiceIcon(iconName: string): any {
  return iconMap[iconName] || DataAnalysis
}

const services = ref<AutomationServiceInfo[]>([])
const loadingServices = ref(false)
const selectedService = ref<AutomationServiceInfo | null>(null)
const executing = ref(false)
const executeResult = ref<AutomationResponse | null>(null)
const executeError = ref('')

// 参数输入字典
const paramInputs = ref<Record<string, string>>({})

// 判断是否可以执行
const canExecute = computed(() => {
  if (!selectedService.value) return false

  // 检查必填参数
  const schemas = selectedService.value.param_schemas || {}
  for (const [key, schema] of Object.entries(schemas)) {
    if (schema.required && !paramInputs.value[key]?.trim()) {
      return false
    }
  }
  return true
})

/**
 * 加载服务列表
 */
async function loadServices(): Promise<void> {
  loadingServices.value = true
  try {
    services.value = await getAutomationServices()
    console.log('[AutomationView] 已加载服务列表，数量:', services.value.length)
  } catch (error) {
    console.error('[AutomationView] 加载服务列表失败:', error)
    ElMessage.error('加载服务列表失败')
  } finally {
    loadingServices.value = false
  }
}

/**
 * 选择服务类型
 */
function selectService(service: AutomationServiceInfo): void {
  selectedService.value = service
  executeResult.value = null
  executeError.value = ''

  // 初始化参数输入
  paramInputs.value = {}
  const schemas = service.param_schemas || {}
  for (const key of Object.keys(schemas)) {
    paramInputs.value[key] = ''
  }

  console.log('[AutomationView] 已选择服务:', service.type, '参数:', Object.keys(schemas))
}

/**
 * 判断服务是否处在激活状态
 */
function isServiceSelected(service: AutomationServiceInfo): boolean {
  return selectedService.value !== null && (selectedService.value as AutomationServiceInfo).type === service.type
}

/**
 * 获取参数占位符
 */
function getParamPlaceholder(key: string, schema: any): string {
  if (schema.examples?.length) {
    return `例：${schema.examples[0].slice(0, 40)}${schema.examples[0].length > 40 ? '...' : ''}`
  }
  return `请输入 ${schema.label}...`
}

/**
 * 截断超长示例文本
 */
function truncateExample(text: string): string {
  return text.length > 20 ? text.slice(0, 20) + '…' : text
}

/**
 * 点击示例填充
 */
function fillExample(key: string, example: string): void {
  paramInputs.value[key] = example
  console.log(`[AutomationView] 已填入示例 - 参数: ${key}, 值: ${example.slice(0, 30)}...`)
}

/**
 * 执行自动化服务
 */
async function handleExecute(): Promise<void> {
  if (!selectedService.value || !canExecute.value) return

  executing.value = true
  executeResult.value = null
  executeError.value = ''

  try {
    console.log('[AutomationView] 开始执行服务:', selectedService.value.type)

    let result: AutomationResponse
    const serviceType = selectedService.value.type

    // 根据服务类型调用不同接口
    switch (serviceType) {
      case 'data_processing': {
        const configStr = paramInputs.value.processing_config
        const processingConfig = configStr ? JSON.parse(configStr) : {}
        result = await dataProcessing({
          data: paramInputs.value.data,
          processing_config: processingConfig,
        })
        break
      }
      case 'report_generation': {
        const configStr = paramInputs.value.report_config
        const reportConfig = configStr ? JSON.parse(configStr) : {}
        result = await reportGeneration({
          data_source: paramInputs.value.data_source,
          template: paramInputs.value.template || undefined,
          report_config: reportConfig,
        })
        break
      }
      case 'code_generation': {
        const configStr = paramInputs.value.code_config
        const codeConfig = configStr ? JSON.parse(configStr) : {}
        result = await codeGeneration({
          requirements: paramInputs.value.requirements,
          language: paramInputs.value.language || 'Python',
          framework: paramInputs.value.framework || undefined,
          code_config: codeConfig,
        })
        break
      }
      default:
        throw new Error('未知的服务类型')
    }

    executeResult.value = result
    ElMessage.success('执行成功！')
    console.log('[AutomationView] 执行成功，结果:', result)
  } catch (error) {
    const errMsg = error instanceof Error ? error.message : '执行失败'
    executeError.value = errMsg
    console.error('[AutomationView] 执行失败:', error)
  } finally {
    executing.value = false
  }
}

/**
 * 获取结果中的嵌套字段
 * @param path 字段路径，支持点号分隔，如 'usage.prompt_tokens'
 */
function getResultField(path: string): any {
  if (!executeResult.value) return undefined
  debugger

  // 返回的数据直接在 executeResult.value 中，不需要再取 result
  const result = executeResult.value
  const keys = path.split('.')
  let value: any = result

  for (const key of keys) {
    if (value && typeof value === 'object' && key in value) {
      value = value[key]
    } else {
      return undefined
    }
  }

  return value
}

/**
 * 格式化 JSON 结果为 Markdown 代码块
 */
function formatJsonResult(result: any): string {
  if (!result) return ''

  let parsed: any = result
  if (typeof result === 'string') {
    try {
      parsed = JSON.parse(result)
    } catch {
      return result
    }
  }

  if (typeof parsed === 'object') {
    return '```json\n' + JSON.stringify(parsed, null, 2) + '\n```'
  }

  return String(result)
}

onMounted(() => {
  loadServices()
})
</script>

<style scoped>
.automation-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.page-header {
  flex-shrink: 0;
  padding: 20px 24px;
  border-bottom: 1px solid var(--color-border-light);
  background: var(--color-bg-primary);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.services-grid {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  align-content: start;
}

.service-card {
  padding: 20px;
  cursor: pointer;
  transition: all var(--transition-fast);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.service-card:hover, .service-card.active {
  box-shadow: var(--shadow-lg);
  transform: translateY(-2px);
  border-color: var(--color-primary);
}

.service-card-top {
  display: flex;
  align-items: center;
  gap: 12px;
}

.service-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.service-name {
  display: block;
  font-weight: 600;
  font-size: 0.95rem;
  color: var(--color-text-primary);
}

.service-type-badge {
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

.service-desc {
  font-size: 0.82rem;
  color: var(--color-text-secondary);
  line-height: 1.6;
  flex: 1;
}

.service-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
}

.param-count {
  font-size: 0.72rem;
  color: var(--color-text-muted);
}

/* 执行面板 */
.execution-panel {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* 选中服务头部 */
.selected-service-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  background: var(--gradient-primary-soft);
  border-radius: var(--radius-lg);
  border: 1px solid #ddd6fe;
}

.selected-service-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.selected-service-name {
  font-weight: 700;
  font-size: 1rem;
  color: var(--color-text-primary);
}

.selected-service-desc {
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  margin-top: 2px;
}

/* 参数输入区 */
.params-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

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

/* 单个参数行容器 */
.param-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px;
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  transition: border-color var(--transition-fast);
}

.param-row:focus-within {
  border-color: var(--color-primary);
}

/* 参数标签行 */
.param-label-row {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: space-between;
}

.param-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--color-text-primary);
  display: flex;
  align-items: center;
  gap: 6px;
}

.param-key-badge {
  font-size: 0.65rem;
  font-family: var(--font-mono);
  color: var(--color-text-muted);
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  padding: 1px 6px;
  border-radius: var(--radius-full);
  font-weight: 400;
}

.param-required-badge {
  font-size: 0.62rem;
  font-weight: 500;
  color: var(--color-primary);
  background: var(--color-primary-lighter);
  padding: 1px 7px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

/* 参数说明文字 */
.param-desc {
  font-size: 0.75rem;
  color: var(--color-text-muted);
  display: flex;
  align-items: flex-start;
  gap: 4px;
  line-height: 1.5;
  margin: 0;
}

/* 示例区域 */
.param-examples {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}

.param-examples-label {
  font-size: 0.7rem;
  color: var(--color-text-muted);
  flex-shrink: 0;
}

/* 示例 pill */
.param-example-pill {
  font-size: 0.7rem;
  padding: 3px 10px;
  background: var(--color-bg-primary);
  color: var(--color-primary);
  border: 1px solid var(--color-primary);
  border-radius: var(--radius-full);
  cursor: pointer;
  transition: all var(--transition-fast);
  white-space: nowrap;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  user-select: none;
}

.param-example-pill:hover {
  background: var(--color-primary);
  color: #fff;
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
}

.param-example-pill:active {
  transform: translateY(0);
}

/* 结果展示区 */
.result-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.result-header {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  border-bottom: 1px solid var(--color-border-light);
  padding-bottom: 8px;
}

.result-content {
  padding: 20px;
  background: var(--color-success-light-9);
  border: 1px solid var(--color-success-light-5);
}

.result-metadata {
  margin-bottom: 16px;
}

.result-info-cards {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
}

.info-card {
  font-size: 0.85rem;
}

.info-card :deep(.el-card__header) {
  padding: 10px 14px;
  background: var(--color-bg-secondary);
}

.info-card-title {
  font-weight: 600;
  font-size: 0.85rem;
  color: var(--color-text-primary);
}

.result-data {
  font-size: 0.9rem;
  line-height: 1.6;
}

.error-content {
  padding: 20px;
}
</style>
