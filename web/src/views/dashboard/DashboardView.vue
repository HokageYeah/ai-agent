<template>
  <div class="dashboard-view">
    <!-- 欢迎标题区域 -->
    <div class="welcome-section">
      <div class="welcome-content">
        <h1 class="welcome-title">欢迎使用 <span class="text-gradient">AI Agent</span> 智能体平台</h1>
        <p class="welcome-desc">集多轮对话、Agent 执行、技能库、工作流编排于一体的通用 AI 智能体框架</p>
      </div>
      <div class="welcome-decoration">
        <div class="decoration-circle circle-1"></div>
        <div class="decoration-circle circle-2"></div>
        <div class="decoration-circle circle-3"></div>
      </div>
    </div>

    <!-- 统计数据卡片 -->
    <div class="stats-section">
      <div
        v-for="stat in stats"
        :key="stat.label"
        class="stat-card"
        :class="{ loading: stat.loading }"
      >
        <div class="stat-icon" :style="{ background: stat.iconBg }">
          <el-icon :size="22" :style="{ color: stat.iconColor }">
            <component :is="stat.icon" />
          </el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">
            <span v-if="!stat.loading">{{ stat.value }}</span>
            <span v-else class="skeleton" style="width:40px;height:24px;display:inline-block;"></span>
          </div>
          <div class="stat-label">{{ stat.label }}</div>
        </div>
      </div>
    </div>

    <!-- 快捷入口卡片 -->
    <div class="quick-access-section">
      <h2 class="section-title">快捷入口</h2>
      <div class="quick-cards">
        <router-link
          v-for="card in quickCards"
          :key="card.path"
          :to="card.path"
          class="quick-card card-base"
        >
          <div class="quick-card-icon" :style="{ background: card.gradient }">
            <el-icon :size="28" style="color:white">
              <component :is="card.icon" />
            </el-icon>
          </div>
          <div class="quick-card-content">
            <h3 class="quick-card-title">{{ card.title }}</h3>
            <p class="quick-card-desc">{{ card.desc }}</p>
          </div>
          <el-icon class="quick-card-arrow" :size="16"><ArrowRight /></el-icon>
        </router-link>
      </div>
    </div>

    <!-- 系统信息 -->
    <div class="system-info-section">
      <h2 class="section-title">系统架构</h2>
      <div class="architecture-cards">
        <div v-for="arch in architectureItems" :key="arch.title" class="arch-card card-base">
          <div class="arch-header">
            <span class="arch-badge" :style="{ background: arch.color }">{{ arch.layer }}</span>
            <h4 class="arch-title">{{ arch.title }}</h4>
          </div>
          <p class="arch-desc">{{ arch.desc }}</p>
          <div class="arch-tags">
            <span v-for="tag in arch.tags" :key="tag" class="arch-tag">{{ tag }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  ChatDotSquare, Setting, MagicStick, Connection,
  ArrowRight, DataLine, Cpu, Tools
} from '@element-plus/icons-vue'
import { getAgentList } from '@/api/modules/agents'
import { getSkillList } from '@/api/modules/skills'
import { getWorkflowList } from '@/api/modules/workflows'

// 统计数据
const stats = ref([
  { label: 'Agent 数量', value: '-', loading: true, icon: Setting, iconBg: '#ede9fe', iconColor: '#7c3aed' },
  { label: '技能数量', value: '-', loading: true, icon: MagicStick, iconBg: '#e0f2fe', iconColor: '#06b6d4' },
  { label: '工作流数量', value: '-', loading: true, icon: Connection, iconBg: '#d1fae5', iconColor: '#10b981' },
  { label: '支持模型', value: 'GPT / Qwen', loading: false, icon: Cpu, iconBg: '#fef3c7', iconColor: '#f59e0b' },
])

// 快捷入口卡片
const quickCards = [
  {
    path: '/chat',
    title: 'AI 对话',
    desc: '多轮对话，支持流式打字机输出，Markdown 渲染',
    icon: ChatDotSquare,
    gradient: 'linear-gradient(135deg, #7c3aed, #8b5cf6)',
  },
  {
    path: '/agents',
    title: 'Agent 执行',
    desc: '规划→执行→反思闭环，支持工具调用和子 Agent 协作',
    icon: Setting,
    gradient: 'linear-gradient(135deg, #06b6d4, #0891b2)',
  },
  {
    path: '/skills',
    title: '技能库',
    desc: '数据分析、代码生成、文本写作、翻译等预置技能',
    icon: MagicStick,
    gradient: 'linear-gradient(135deg, #10b981, #059669)',
  },
  {
    path: '/workflows',
    title: '工作流',
    desc: '基于拓扑图的有向确定性流程编排引擎',
    icon: Connection,
    gradient: 'linear-gradient(135deg, #f59e0b, #d97706)',
  },
]

// 架构说明卡片
const architectureItems = [
  {
    layer: 'LLM Hub',
    title: '推理基础设施',
    desc: '统一多模型供应商接入，支持流式输出和工具调用网关',
    tags: ['OpenAI', 'Anthropic', 'Qwen', '流式输出'],
    color: '#7c3aed'
  },
  {
    layer: 'Capability',
    title: '能力层',
    desc: '工具中心（Tools）+ 技能管理器（Skills）+ 短期记忆',
    tags: ['计算器', '日期时间', 'HTTP工具', 'Python执行'],
    color: '#06b6d4'
  },
  {
    layer: 'Orchestration',
    title: '编排层',
    desc: 'LangGraph 驱动的有状态 Agent 图状态机调度总线',
    tags: ['Planning', 'Execution', 'Reflection', 'LangGraph'],
    color: '#10b981'
  },
  {
    layer: 'API Layer',
    title: '接口层',
    desc: 'FastAPI RESTful API，提供对话、Agent、技能、工作流接口',
    tags: ['FastAPI', 'Chat API', 'Agent API', 'SSE 流式'],
    color: '#f59e0b'
  },
]

/**
 * 页面挂载时异步加载各资源数量统计
 */
onMounted(async () => {
  console.log('[仪表盘] 开始加载统计数据...')

  // 并行加载 Agent、技能、工作流数量
  const [agentsResult, skillsResult, workflowsResult] = await Promise.allSettled([
    getAgentList(),
    getSkillList(),
    getWorkflowList(),
  ])

  if (agentsResult.status === 'fulfilled') {
    stats.value[0].value = String(agentsResult.value.length)
    stats.value[0].loading = false
    console.log('[仪表盘] Agent 数量:', agentsResult.value.length)
  } else {
    stats.value[0].value = '加载失败'
    stats.value[0].loading = false
  }

  if (skillsResult.status === 'fulfilled') {
    stats.value[1].value = String(skillsResult.value.length)
    stats.value[1].loading = false
    console.log('[仪表盘] 技能数量:', skillsResult.value.length)
  } else {
    stats.value[1].value = '加载失败'
    stats.value[1].loading = false
  }

  if (workflowsResult.status === 'fulfilled') {
    stats.value[2].value = String(workflowsResult.value.length)
    stats.value[2].loading = false
    console.log('[仪表盘] 工作流数量:', workflowsResult.value.length)
  } else {
    stats.value[2].value = '加载失败'
    stats.value[2].loading = false
  }
})
</script>

<style scoped>
.dashboard-view {
  height: 100%;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

/* ====== 欢迎区域 ====== */
.welcome-section {
  position: relative;
  background: var(--gradient-primary-soft);
  border-radius: var(--radius-xl);
  padding: 36px 40px;
  overflow: hidden;
  border: 1px solid #ddd6fe;
}

.welcome-content {
  position: relative;
  z-index: 1;
}

.welcome-title {
  font-family: var(--font-heading);
  font-size: 1.8rem;
  font-weight: 700;
  color: var(--color-text-primary);
  margin-bottom: 8px;
  line-height: 1.3;
}

.welcome-desc {
  font-size: 0.9rem;
  color: var(--color-text-secondary);
  max-width: 560px;
  line-height: 1.7;
}

/* 装饰圆形气泡 */
.welcome-decoration {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 300px;
}

.decoration-circle {
  position: absolute;
  border-radius: 50%;
  opacity: 0.15;
  background: var(--gradient-primary);
}

.circle-1 { width: 200px; height: 200px; top: -60px; right: -40px; }
.circle-2 { width: 120px; height: 120px; top: 40px; right: 100px; }
.circle-3 { width: 80px; height: 80px; bottom: -20px; right: 60px; }

/* ====== 统计卡片 ====== */
.stats-section {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
}

.stat-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: var(--shadow-card);
  transition: transform var(--transition-fast), box-shadow var(--transition-fast);
  cursor: default;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.stat-icon {
  width: 50px;
  height: 50px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-value {
  font-family: var(--font-heading);
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--color-text-primary);
  line-height: 1;
  margin-bottom: 4px;
}

.stat-label {
  font-size: 0.8rem;
  color: var(--color-text-muted);
}

/* ====== 快捷入口 ====== */
.section-title {
  font-family: var(--font-heading);
  font-size: 1rem;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 16px;
}

.quick-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}

.quick-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  text-decoration: none;
  color: inherit;
  transition: transform var(--transition-fast), box-shadow var(--transition-fast);
  cursor: pointer;
}

.quick-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}

.quick-card-icon {
  width: 52px;
  height: 52px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.quick-card-content {
  flex: 1;
  min-width: 0;
}

.quick-card-title {
  font-weight: 600;
  font-size: 0.9rem;
  color: var(--color-text-primary);
  margin-bottom: 4px;
}

.quick-card-desc {
  font-size: 0.78rem;
  color: var(--color-text-muted);
  line-height: 1.5;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.quick-card-arrow {
  color: var(--color-text-muted);
  flex-shrink: 0;
  transition: transform var(--transition-fast), color var(--transition-fast);
}

.quick-card:hover .quick-card-arrow {
  transform: translateX(4px);
  color: var(--color-primary);
}

/* ====== 架构说明 ====== */
.architecture-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 16px;
}

.arch-card {
  padding: 20px;
  transition: transform var(--transition-fast);
}

.arch-card:hover {
  transform: translateY(-2px);
}

.arch-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.arch-badge {
  font-size: 0.65rem;
  font-weight: 700;
  color: white;
  padding: 2px 8px;
  border-radius: var(--radius-full);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.arch-title {
  font-weight: 600;
  font-size: 0.9rem;
  color: var(--color-text-primary);
}

.arch-desc {
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  line-height: 1.6;
  margin-bottom: 12px;
}

.arch-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.arch-tag {
  font-size: 0.7rem;
  padding: 2px 8px;
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
}
</style>
