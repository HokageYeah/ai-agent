<template>
  <!--
    Markdown 渲染组件
    将 AI 回复内容从 Markdown 格式渲染为 HTML，支持代码块高亮
    使用 v-html 渲染（内容来自受信任的 AI 后端，不接受用户原始输入）
  -->
  <div class="markdown-body" v-html="renderedHtml"></div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'

interface Props {
  /** 要渲染的 Markdown 文本内容 */
  content: string
}

const props = defineProps<Props>()

/**
 * 初始化 markdown-it 实例
 * - html: true 允许内联 HTML（后端内容受信任）
 * - linkify: true 自动识别 URL 为链接
 * - highlight: 使用 highlight.js 高亮代码块
 */
const md: MarkdownIt = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  highlight(str: string, lang: string): string {
    // 代码块高亮处理
    if (lang && hljs.getLanguage(lang)) {
      try {
        const highlighted = hljs.highlight(str, { language: lang }).value
        // 添加语言标签 + 高亮后的代码
        return `<pre><div class="code-lang-label">${lang}</div><code class="hljs language-${lang}">${highlighted}</code></pre>`
      } catch {
        console.warn('[Markdown] 代码高亮失败，语言:', lang)
      }
    }
    // 无语言标签时，做基础转义
    return `<pre><code class="hljs">${md.utils.escapeHtml(str)}</code></pre>`
  },
})

/**
 * 渲染 Markdown 为 HTML 字符串
 * 使用计算属性缓存，只在 content 变化时重新渲染
 */
const renderedHtml = computed<string>(() => {
  if (!props.content) return ''
  try {
    return md.render(props.content)
  } catch (error) {
    console.error('[Markdown] 渲染失败:', error)
    // 降级：原样展示文本
    return `<p>${props.content}</p>`
  }
})
</script>

<style scoped>
/* Markdown 容器：让 highlight.js 样式在此组件内生效 */
.markdown-body {
  width: 100%;
  word-break: break-word;
}

/* 代码块语言标签 */
:deep(.code-lang-label) {
  font-size: 0.7rem;
  color: var(--color-text-muted);
  font-family: var(--font-mono);
  padding: 8px 16px 0;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* 覆盖 highlight.js 代码块边距，由 pre 控制 */
:deep(pre > code) {
  padding: 8px 16px 16px !important;
}
</style>
