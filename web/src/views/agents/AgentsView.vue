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
          <!-- 选中 Agent 头部信息（含使用说明 tooltip） -->
          <div class="selected-agent-header">
            <div class="selected-agent-avatar">
              <el-icon :size="24" style="color:white"><Setting /></el-icon>
            </div>
            <div class="selected-agent-info">
              <div class="selected-agent-name">{{ selectedAgent.name }}</div>
              <div class="selected-agent-desc">{{ selectedAgent.description }}</div>
            </div>
            <!-- 使用说明 tooltip：悬停图标显示说明 -->
            <el-tooltip placement="top" effect="light">
              <template #content>
                <div class="agent-usage-guide">
                  <p><strong>Agent 角色说明：</strong>{{ selectedAgent.description }}</p>
                  <p>Agent 能够基于选定的专家角色，自主规划（Planning）→ 执行（Execution）→ 思考（Reasoning）→ 产生最终结果（Final Answer）。</p>
                  <p><strong>操作指南：</strong>在下方输入需要解决的复杂问题，点击执行即可观测大模型的自动化思维与行为闭环。</p>
                </div>
              </template>
              <el-icon :size="18" class="info-icon"><InfoFilled /></el-icon>
            </el-tooltip>
            <div class="selected-agent-meta">
              <span class="meta-item">工具: {{ selectedAgent.available_tools.length }}</span>
              <span class="meta-item">技能: {{ selectedAgent.available_skills.length }}</span>
            </div>
          </div>

          <!-- 执行轨迹 (详情) - 移动到中央自适应高度并提供滚动 -->
          <div class="trajectory-section" v-if="executeResult || isStreaming">
            <!-- 头部：标题 + 阶段进度指示器 -->
            <div class="trajectory-header">
              <div class="trajectory-title">
                <el-icon><DataLine /></el-icon>
                <span>Agent 思考与执行轨迹</span>
              </div>
              
              <!-- 阶段进度指示器 -->
              <div class="trajectory-progress">
                <div class="trajectory-progress-step" :class="{ active: currentPhase === 'planning', completed: progressPercent > 20 }">
                  <span class="step-icon"><el-icon v-if="progressPercent > 20"><Check /></el-icon><el-icon v-else><Aim /></el-icon></span>
                  <span>规划</span>
                </div>
                <div class="trajectory-progress-divider" v-if="progressPercent > 10"></div>
                
                <div class="trajectory-progress-step" :class="{ active: currentPhase === 'executing', completed: progressPercent > 50 }">
                  <span class="step-icon"><el-icon v-if="progressPercent > 50"><Check /></el-icon><el-icon v-else><Promotion /></el-icon></span>
                  <span>执行</span>
                </div>
                <div class="trajectory-progress-divider" v-if="progressPercent > 40"></div>
                
                <div class="trajectory-progress-step" :class="{ active: currentPhase === 'reflecting', completed: progressPercent > 80 }">
                  <span class="step-icon"><el-icon v-if="progressPercent > 80"><Check /></el-icon><el-icon v-else><ChatDotRound /></el-icon></span>
                  <span>反思</span>
                </div>
                <div class="trajectory-progress-divider" v-if="progressPercent > 70"></div>
                
                <div class="trajectory-progress-step" :class="{ active: currentPhase === 'completed' }">
                  <span class="step-icon"><el-icon><Finished /></el-icon></span>
                  <span>完成</span>
                </div>
              </div>
            </div>
            
            <!-- 流式事件嵌套分组展示 -->
            <div v-if="streamEvents.length > 0" class="stream-events-wrapper">
              <div
                class="stream-events-container"
                ref="streamEventsContainer"
                @scroll="onTrajectoryScroll"
              >
                <!-- 遍历迭代层 -->
                <div v-for="iterGroup in groupedIterations" :key="'iter-'+iterGroup.iteration" class="iteration-group" style="margin-bottom: 24px;">
                  <!-- 迭代标题 (可折叠) -->
                  <div
                    class="iteration-header"
                    @click="toggleExpansion(`iter-${iterGroup.iteration}`)"
                    style="cursor: pointer; display: flex; align-items: center; justify-content: space-between; background: var(--color-bg-secondary); padding: 12px 16px; border-radius: 8px; border: 1px solid var(--color-border);"
                  >
                    <div style="font-weight: 600; font-size: 1rem; color: var(--color-text-primary); display: flex; align-items: center; gap: 8px;">
                      <el-icon style="transition: transform 0.3s;" :style="{ transform: expansionState['iter-'+iterGroup.iteration] ? 'rotate(90deg)' : 'rotate(0)' }"><CaretRight /></el-icon>
                      迭代 {{ iterGroup.iteration + 1 }}
                    </div>
                    <el-tag size="small" type="info">共 {{ iterGroup.blocks.length }} 个执行块</el-tag>
                  </div>

                  <!-- 迭代内容区 -->
                  <div v-show="expansionState['iter-'+iterGroup.iteration]" class="iteration-content">
                    <!-- 遍历 Agent Block 层 -->
                    <div v-for="(block, bIdx) in iterGroup.blocks" :key="'block-'+iterGroup.iteration+'-'+block.id+'-'+bIdx" class="agent-block" style="margin-bottom: 20px;">
                      
                      <!-- 子 Agent Block 头部 -->
                      <div
                        v-if="block.type === 'sub'"
                        class="trajectory-content sub-agent-block-header"
                        :style="getSubAgentTheme(block.id)"
                        @click="toggleExpansion(`block-${iterGroup.iteration}-${block.id}`)"
                      >
                         <div class="sub-agent-block-title" style="justify-content: space-between;">
                           <div style="display: flex; align-items: center; gap: 10px;">
                             <el-icon style="transition: transform 0.3s;" :style="{ transform: expansionState['block-'+iterGroup.iteration+'-'+block.id] ? 'rotate(90deg)' : 'rotate(0)' }"><CaretRight /></el-icon>
                             <span class="sub-agent-block-icon" aria-hidden="true"><el-icon :size="18"><User /></el-icon></span>
                             <span class="sub-agent-block-label">子 Agent 委派任务</span>
                             <span class="sub-agent-block-name">{{ block.name }}</span>
                             <el-tag size="small" type="info" effect="plain" class="sub-agent-block-id">{{ block.id }}</el-tag>
                           </div>
                           <el-tag size="small" type="primary" effect="dark">{{ block.events.length }} 个事件</el-tag>
                         </div>
                         <div v-if="block.task" class="sub-agent-block-task">{{ block.task }}</div>
                      </div>
                      
                      <!-- 主 Agent Block 头部 (如果多于一个 Block，也加上小标题区分，否则可以省略) -->
                      <div
                        v-else-if="iterGroup.blocks.length > 1"
                        @click="toggleExpansion(`block-${iterGroup.iteration}-${block.id}`)"
                        style="cursor: pointer; display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 0.9rem; color: var(--color-text-secondary); margin-bottom: 12px; padding-bottom: 4px; border-bottom: 1px dashed var(--color-border);"
                      >
                         <el-icon style="transition: transform 0.3s;" :style="{ transform: expansionState['block-'+iterGroup.iteration+'-'+block.id] ? 'rotate(90deg)' : 'rotate(0)' }"><CaretRight /></el-icon>
                         主 Agent 处理阶段 ({{ block.events.length }} 个事件)
                      </div>

                      <!-- Block 内部事件列表 (时间轴) -->
                      <el-timeline v-show="expansionState['block-'+iterGroup.iteration+'-'+block.id]" class="block-timeline" :class="{ 'sub-block-timeline': block.type === 'sub' }">
                        <el-timeline-item
                          v-for="(itemEvent, eIdx) in block.events"
                          :key="'event-'+eIdx"
                          :type="getEventTimelineType(itemEvent.event)"
                          :hollow="!isImportantEvent(itemEvent.event)"
                          :size="getEventTimelineSize(itemEvent.event)"
                        >
                          <div
                            :data-event-type="itemEvent.event"
                            class="trajectory-content"
                            :class="{
                              'sub-agent-inner-content': block.type === 'sub',
                              'step-thinking': isStreaming && isLastStreamEvent(iterGroup, block, eIdx)
                            }"
                            :style="block.type === 'sub' ? { marginTop: 0, ...getSubAgentTheme(block.id) } : { marginTop: 0 }"
                          >
                            <!-- 为了保持旧版使用 item.event 结构解析模板，做一层包装 -->
                            <template v-for="(item, wIdx) in [{ event: itemEvent }]" :key="'wrapper-' + wIdx">
                    <!-- ① 规划开始 -->
                    <template v-if="item.event.event === 'plan_start'">
                      <div class="plan-start-header">
                        <div class="plan-start-icon">
                          <el-icon :size="20"><Cpu /></el-icon>
                        </div>
                        <div class="plan-start-info">
                          <div class="plan-start-title">开始规划与推理</div>
                          <div class="plan-start-desc">{{ item.event.data?.message || 'Agent 正在分析任务并制定执行计划...' }}</div>
                        </div>
                      </div>
                    </template>
                    
                    <!-- ② 规划完成（含推理和步骤列表） -->
                    <template v-else-if="item.event.event === 'plan_complete'">
                      <div class="plan-complete-header">
                        <div class="plan-complete-icon">
                          <el-icon :size="18"><Check /></el-icon>
                        </div>
                        <span class="plan-complete-title">规划完成</span>
                        <el-tag size="small" type="success" effect="plain">{{ item.event.data?.steps?.length || 0 }} 个步骤</el-tag>
                      </div>
                      <!-- 推理过程 -->
                      <div v-if="item.event.data?.reasoning" class="reasoning-block">
                        <div class="reasoning-label">推理过程</div>
                        <div class="reasoning-content">{{ item.event.data.reasoning }}</div>
                      </div>
                      <!-- 步骤列表 -->
                      <div v-if="item.event.data?.steps?.length" class="steps-list">
                        <div class="steps-label">执行计划</div>
                        <div v-for="(step, sIdx) in (item.event.data.steps || [])" :key="sIdx" class="step-item">
                          <span class="step-number">{{ Number(sIdx) + 1 }}</span>
                          <el-tag v-if="step.action === 'tool'" size="small" type="success" effect="plain">
                            <el-icon style="margin-right:4px"><Promotion /></el-icon>{{ step.tool_name }}
                          </el-tag>
                          <el-tag v-else-if="step.action === 'skill'" size="small" type="warning" effect="plain">
                            <el-icon style="margin-right:4px"><MagicStick /></el-icon>{{ step.skill_id }}
                          </el-tag>
                          <el-tag v-else-if="step.action === 'delegate'" size="small" type="primary" effect="plain">
                            <el-icon style="margin-right:4px"><User /></el-icon>{{ step.agent_id }}
                          </el-tag>
                          <el-tag v-else-if="step.action === 'final_answer'" size="small" type="info" effect="plain">合成最终答案</el-tag>
                          <el-tag v-else size="small" effect="plain">{{ step.action }}</el-tag>
                        </div>
                      </div>
                    </template>
                    
                    <!-- ③ 执行阶段开始 -->
                    <template v-else-if="item.event.event === 'step_start'">
                      <div style="margin-bottom: 10px; font-weight: 600; display: flex; align-items: center; gap: 12px;">
                        <el-tag size="small" type="info" effect="dark">
                          <el-icon><Promotion /></el-icon> 开始执行
                        </el-tag>
                        <span style="font-size: 0.85rem; color: var(--color-text-secondary);">
                          共 <strong style="color: var(--color-primary);">{{ item.event.step_total || 0 }}</strong> 个步骤
                        </span>
                      </div>
                      <div style="font-size: 0.82rem; color: var(--color-text-muted); padding: 8px 12px; background: var(--color-bg-secondary); border-radius: 6px;">
                        {{ item.event.data?.message || '正在按计划逐步执行每个步骤...' }}
                      </div>
                    </template>
                    
                    <!-- ④ 工具调用完成 -->
                    <template v-else-if="item.event.event === 'tool_complete'">
                      <!-- 头部 -->
                      <div class="tool-complete-header">
                        <div class="tool-icon">
                          <el-icon :size="16"><Promotion /></el-icon>
                        </div>
                        <span class="tool-name">{{ item.event.data?.tool_name }}</span>
                        <div class="tool-meta">
                          <span class="tool-step">步骤 {{ item.event.step_index }}/{{ item.event.step_total }}</span>
                          <span v-if="item.event.data?.execution_time_ms" class="tool-time">{{ item.event.data.execution_time_ms.toFixed(1) }}ms</span>
                        </div>
                        <el-tag v-if="item.event.data?.success === false" size="small" type="danger" effect="dark">失败</el-tag>
                      </div>
                      
                      <!-- 数据库 -->
                      <div v-if="item.event.data?.result?.columns && item.event.data?.result?.rows" class="db-result-block">
                        <div class="db-result-header">
                          <span>查询结果</span>
                          <span class="db-result-count">{{ item.event.data.result.row_count }} 条记录</span>
                        </div>
                        <div class="db-table-wrapper">
                          <table class="db-table">
                            <thead>
                              <tr>
                                <th v-for="col in item.event.data.result.columns" :key="col">{{ col }}</th>
                              </tr>
                            </thead>
                            <tbody>
                              <tr v-for="(row, rIdx) in item.event.data.result.rows" :key="rIdx">
                                <td v-for="col in item.event.data.result.columns" :key="col">{{ row[col] }}</td>
                              </tr>
                            </tbody>
                          </table>
                        </div>
                      </div>
                      
                      <!-- 普通文本/JSON 结果 -->
                      <div v-else-if="item.event.data?.error" class="error-block">
                        <strong>错误：</strong>{{ item.event.data.error }}
                      </div>
                      <div v-else-if="item.event.data?.result" class="trajectory-result-block">
                        <MarkdownRenderer v-if="typeof item.event.data.result === 'string'" :content="item.event.data.result" />
                        <MarkdownRenderer v-else :content="'```json\n' + JSON.stringify(item.event.data.result, null, 2) + '\n```'" />
                      </div>
                    </template>
                    
                    <!-- ⑤ 技能调用完成 -->
                    <template v-else-if="item.event.event === 'skill_complete'">
                      <div style="margin-bottom: 8px; font-weight: 600;">
                        <el-tag size="small" type="warning">✨ 调用技能</el-tag>
                        <span style="font-size: 0.8rem; color: var(--color-text-muted); margin-left: 8px;">
                          {{ item.event.data?.skill_id }}
                        </span>
                        <el-tag v-if="item.event.data?.success === false" size="small" type="danger" style="margin-left: 8px;">失败</el-tag>
                        <span style="font-size: 0.75rem; color: var(--color-text-muted); margin-left: 8px;">
                          步骤 {{ item.event.step_index }}/{{ item.event.step_total }}
                        </span>
                      </div>
                      <div style="font-size: 0.85rem;" class="trajectory-result-block">
                        <div v-if="item.event.data?.error" style="color: var(--el-color-danger); padding: 6px; background: var(--el-color-danger-light-9); border-radius: 4px;">
                          {{ item.event.data.error }}
                        </div>
                        <MarkdownRenderer v-else-if="typeof item.event.data?.result === 'string'" :content="item.event.data.result" />
                        <MarkdownRenderer v-else-if="item.event.data?.result" :content="'```json\n' + JSON.stringify(item.event.data.result, null, 2) + '\n```'" />
                      </div>
                    </template>
                    
                    <!-- ⑥ 委派子Agent完成 -->
                    <template v-else-if="item.event.event === 'delegate_complete'">
                      <!-- 头部信息 -->
                      <div style="margin-bottom: 10px; font-weight: 600; display: flex; align-items: center; flex-wrap: wrap; gap: 8px;">
                        <el-tag size="small" type="primary" effect="plain">
                          <el-icon><User /></el-icon> 委派子Agent
                        </el-tag>
                        <span style="font-size: 0.85rem; color: var(--color-primary); font-weight: 600;">
                          {{ item.event.data?.result?.agent_name || item.event.data?.agent_id }}
                        </span>
                        <el-tag v-if="item.event.data?.success === false" size="small" type="danger">执行失败</el-tag>
                        <span v-if="item.event.step_index" style="font-size: 0.75rem; color: var(--color-text-muted);">
                          步骤 {{ item.event.step_index }}/{{ item.event.step_total }}
                        </span>
                      </div>
                      
                      <!-- 子 Agent 内部执行步骤（非流式结果时的静态展示） -->
                      <div v-if="item.event.data?.result?.step_results?.length" style="margin-top: 12px;">
                        <div style="font-size: 0.75rem; font-weight: 600; color: var(--color-text-muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.05em;">
                          子Agent 执行轨迹
                        </div>
                        <div v-for="(subStep, sIdx) in item.event.data.result.step_results" :key="sIdx" style="margin-bottom: 12px; font-size: 0.82rem;">
                          <!-- 步骤头部 -->
                          <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-wrap: wrap;">
                            <el-tag v-if="subStep.action === 'tool'" size="small" type="success" effect="plain">
                              <el-icon><Promotion /></el-icon> {{ subStep.tool_name }}
                            </el-tag>
                            <el-tag v-else-if="subStep.action === 'skill'" size="small" type="warning" effect="plain">
                              <el-icon><MagicStick /></el-icon> {{ subStep.skill_id }}
                            </el-tag>
                            <el-tag v-else-if="subStep.action === 'delegate'" size="small" type="primary" effect="plain">
                              <el-icon><User /></el-icon> {{ subStep.agent_id }}
                            </el-tag>
                            <el-tag v-else-if="subStep.action === 'final_answer'" size="small" type="info" effect="plain">
                              <el-icon><ChatDotRound /></el-icon> 合成答案
                            </el-tag>
                            <el-tag v-else size="small" effect="plain">{{ subStep.action }}</el-tag>
                            
                            <!-- 执行时间 -->
                            <span v-if="subStep.execution_time_ms" style="font-size: 0.7rem; color: var(--color-text-muted);">
                              {{ subStep.execution_time_ms.toFixed(2) }}ms
                            </span>
                            <el-tag v-if="!subStep.success" size="small" type="danger">失败</el-tag>
                          </div>
                          
                          <!-- 数据库查询结果表格 -->
                          <div v-if="subStep.result?.columns && subStep.result?.rows" style="padding: 10px; background: var(--color-bg-secondary); border-radius: 6px; border: 1px solid var(--color-border-light);">
                            <div style="font-size: 0.75rem; color: var(--color-text-muted); margin-bottom: 8px;">
                              查询结果 · {{ subStep.result.row_count }} 条记录
                            </div>
                            <div style="overflow-x: auto;">
                              <table style="width: 100%; border-collapse: collapse; font-size: 0.8rem;">
                                <thead>
                                  <tr>
                                    <th v-for="col in subStep.result.columns" :key="col" style="padding: 6px 8px; text-align: left; background: var(--color-bg-primary); border: 1px solid var(--color-border-light); font-weight: 600; white-space: nowrap;">
                                      {{ col }}
                                    </th>
                                  </tr>
                                </thead>
                                <tbody>
                                  <tr v-for="(row, rIdx) in subStep.result.rows" :key="rIdx">
                                    <td v-for="col in subStep.result.columns" :key="col" style="padding: 6px 8px; border: 1px solid var(--color-border-light); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                                      {{ row[col] }}
                                    </td>
                                  </tr>
                                </tbody>
                              </table>
                            </div>
                          </div>
                          
                          <!-- 普通结果 -->
                          <div v-else-if="subStep.result" style="padding: 10px; background: var(--color-bg-secondary); border-radius: 6px;">
                            <MarkdownRenderer v-if="typeof subStep.result === 'string'" :content="subStep.result" />
                            <MarkdownRenderer v-else :content="'```json\n' + JSON.stringify(subStep.result, null, 2) + '\n```'" />
                          </div>
                        </div>
                      </div>
                      
                      <!-- 子 Agent 最终结果 -->
                      <div v-else-if="item.event.data?.result?.result" style="margin-top: 10px; padding: 12px; background: var(--color-bg-secondary); border-radius: 6px; border-left: 3px solid var(--el-color-primary-light-5);">
                        <div style="font-size: 0.75rem; font-weight: 600; color: var(--color-text-muted); margin-bottom: 8px;">
                          执行结果
                        </div>
                        <MarkdownRenderer v-if="typeof item.event.data.result.result === 'string'" :content="item.event.data.result.result" />
                        <MarkdownRenderer v-else :content="'```json\n' + JSON.stringify(item.event.data.result.result, null, 2) + '\n```'" />
                      </div>
                    </template>
                    
                    <!-- ⑥.5 步骤完成（final_answer 合成步骤） -->
                    <template v-else-if="item.event.event === 'step_complete'">
                      <div style="margin-bottom: 10px; font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <el-tag size="small" type="info" effect="plain" style="display: inline-flex; align-items: center; gap: 4px;">
                          <el-icon style="vertical-align: middle;"><ChatDotRound /></el-icon>{{ item.event.data?.step_name || '步骤完成' }}
                        </el-tag>
                        <span style="font-size: 0.75rem; color: var(--color-text-muted);">
                          步骤 {{ (item.event.step_index || 0) }}/{{ item.event.step_total }}
                        </span>
                        <el-tag v-if="item.event.data?.success === false" size="small" type="danger">失败</el-tag>
                      </div>
                      <div v-if="item.event.data?.message" style="font-size: 0.82rem; color: var(--color-text-muted); padding: 8px; background: var(--color-bg-secondary); border-radius: 6px;">
                        {{ item.event.data.message }}
                      </div>
                    </template>
                    
                    <!-- ⑦ 执行阶段完成（进入反思前） -->
                    <template v-else-if="item.event.event === 'execute_complete'">
                      <div style="margin-bottom: 10px; font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <el-tag size="small" type="info" effect="dark">
                          <el-icon style="vertical-align: middle;"><Finished /></el-icon>执行阶段完成
                        </el-tag>
                        <el-tag v-if="item.event.data?.success" size="small" type="success">成功</el-tag>
                        <el-tag v-else size="small" type="warning">部分失败</el-tag>
                        <span style="font-size: 0.75rem; color: var(--color-text-muted);">
                          步骤 {{ (item.event.step_index || 0) }}/{{ item.event.step_total }}
                        </span>
                      </div>
                      
                      <!-- 步骤摘要列表 -->
                      <div v-if="item.event.data?.step_summary?.length" style="margin-top: 12px;">
                        <div style="font-size: 0.75rem; font-weight: 600; color: var(--color-text-muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.05em;">
                          执行步骤摘要
                        </div>
                        <div style="background: var(--color-bg-secondary); border-radius: 6px; padding: 10px 12px; border: 1px solid var(--color-border-light);">
                          <div v-for="(step, idx) in item.event.data.step_summary" :key="idx" style="font-size: 0.82rem; color: var(--color-text-secondary); padding: 4px 0; display: flex; align-items: center; gap: 8px;">
                            <el-icon style="color: var(--el-color-success);"><Check /></el-icon>
                            {{ step }}
                          </div>
                        </div>
                      </div>
                      
                      <div style="font-size: 0.82rem; color: var(--color-text-muted); margin-top: 10px; padding: 8px 12px; background: var(--color-bg-secondary); border-radius: 6px;">
                        {{ item.event.data?.message || '正在进入反思阶段...' }}
                      </div>
                    </template>
                    
                    <!-- ⑧ 反思开始 -->
                    <template v-else-if="item.event.event === 'reflection_start'">
                      <div class="reflection-start-header">
                        <div class="reflection-icon">
                          <el-icon :size="16"><ChatDotRound /></el-icon>
                        </div>
                        <span class="reflection-title">开始自我反思</span>
                      </div>
                      <div class="reflection-desc">{{ item.event.data?.message || 'Agent 正在评估执行结果并进行自我反思...' }}</div>
                    </template>
                    
                    <!-- ⑨ 反思完成 -->
                    <template v-else-if="item.event.event === 'reflection_complete'">
                      <div class="reflection-complete-header">
                        <div class="reflection-icon">
                          <el-icon :size="16"><ChatDotRound /></el-icon>
                        </div>
                        <span class="reflection-title">自我反思</span>
                        <el-tag v-if="item.event.data?.success" size="small" type="success" effect="dark">任务达标</el-tag>
                        <el-tag v-else-if="item.event.data?.skipped" size="small" type="info" effect="plain">跳过</el-tag>
                        <el-tag v-else size="small" type="warning" effect="plain">需改进</el-tag>
                      </div>
                      <div v-if="item.event.data?.skipped" class="reflection-skipped">
                        {{ item.event.data.message || '无执行结果可供反思，已跳过' }}
                      </div>
                      <template v-else>
                        <div v-if="item.event.data?.feedback" class="reflection-feedback">
                          <span class="feedback-label">改进建议</span>
                          {{ item.event.data.feedback }}
                        </div>
                        <div v-if="item.event.data?.summary" class="reflection-summary">
                          <span class="summary-label">总结</span>
                          {{ item.event.data.summary }}
                        </div>
                        <div v-if="item.event.data?.needs_replanning" class="reflection-replan">
                          Agent 将重新规划并再次执行
                        </div>
                      </template>
                    </template>
                    
                    <!-- ⑩ 最终答案 -->
                    <template v-else-if="item.event.event === 'final_answer'">
                      <div class="final-answer-header">
                        <div class="final-answer-icon">
                          <el-icon :size="18"><Finished /></el-icon>
                        </div>
                        <span class="final-answer-title">最终答案</span>
                      </div>
                      <div class="final-answer-content">
                        <MarkdownRenderer v-if="typeof item.event.data?.result === 'string'" :content="item.event.data.result" />
                        <MarkdownRenderer v-else-if="item.event.data?.result" :content="'```json\n' + JSON.stringify(item.event.data.result, null, 2) + '\n```'" />
                        <div v-else class="empty-content">暂无内容</div>
                      </div>
                    </template>
                    
                    <!-- ⑪ 执行完成 -->
                    <template v-else-if="item.event.event === 'complete'">
                      <div class="complete-header">
                        <div class="complete-icon">
                          <el-icon :size="18"><Check /></el-icon>
                        </div>
                        <span class="complete-title">执行完成</span>
                        <span class="complete-iterations">共迭代 {{ item.event.data?.iterations || 0 }} 次</span>
                        <el-tag v-if="item.event.data?.success === false" size="small" type="danger" effect="dark" style="margin-left: 8px;">执行失败</el-tag>
                      </div>
                    </template>
                    
                    <!-- ⑫ 步骤错误 -->
                    <template v-else-if="item.event.event === 'step_error'">
                      <div style="margin-bottom: 8px; font-weight: 600;">
                        <el-tag size="small" type="danger">⚠️ 步骤执行失败</el-tag>
                        <span style="font-size: 0.75rem; color: var(--color-text-muted); margin-left: 8px;">
                          步骤 {{ item.event.step_index }}/{{ item.event.step_total }}
                        </span>
                      </div>
                      <div style="font-size: 0.85rem; color: var(--el-color-danger); padding: 8px; background: var(--el-color-danger-light-9); border-radius: 4px;">
                        {{ item.event.error || item.event.data?.error || '未知错误' }}
                      </div>
                    </template>

                    <!-- ⑬ 用户确认请求（file_write 等需要授权的危险操作） -->
                    <!--
                      后端推送的 user_confirm_required 事件 data 字段结构：
                        confirm_id: string   唯一确认 ID，点击按钮时传给 /agents/confirm 接口
                        tool_name:  string   工具名（如 file_write）
                        params:     object   工具调用参数（路径、内容等）
                        message:    string   提示文案
                      无论是主 Agent 还是子 Agent 触发的确认，都走同一条 SSE 流，
                      前端无需区分来源，统一用 confirm_id 识别并响应。
                    -->
                    <template v-else-if="item.event.event === 'user_confirm_required'">
                      <div style="margin-bottom: 10px; font-weight: 600; display: flex; align-items: center; gap: 8px;">
                        <el-tag size="small" type="warning" effect="dark">
                          ⚠️ 需要用户确认
                        </el-tag>
                        <!-- 显示工具名 -->
                        <el-tag size="small" type="info" effect="plain">
                          {{ item.event.data?.tool_name || '操作' }}
                        </el-tag>
                      </div>

                      <!-- 操作描述区域：显示后端推送的 message 和参数预览 -->
                      <div style="font-size: 0.85rem; padding: 12px; background: var(--el-color-warning-light-9); border-radius: 6px; border-left: 3px solid var(--el-color-warning); margin-bottom: 12px;">
                        <!-- 工具描述：使用后端的 message 字段 -->
                        <div style="font-weight: 600; margin-bottom: 6px;">
                          {{ item.event.data?.message || `Agent 准备执行 [${item.event.data?.tool_name || '操作'}]，需要您的授权` }}
                        </div>
                        <!-- confirm_id 小字提示，方便调试 -->
                        <div style="font-size: 0.75rem; color: var(--color-text-muted); margin-bottom: 8px;">
                          确认 ID: {{ item.event.data?.confirm_id }}
                        </div>
                        <!-- 参数预览：格式化显示 params 对象 -->
                        <div
                          v-if="item.event.data?.params && Object.keys(item.event.data.params).length > 0"
                          style="margin-top: 8px; font-size: 0.8rem; color: var(--color-text-muted); font-family: monospace; background: var(--color-bg-primary); padding: 8px; border-radius: 4px; word-break: break-all; white-space: pre-wrap;"
                        >
                          <!-- 逐行展示每个参数，方便用户阅读 -->
                          <div v-for="(val, key) in item.event.data.params" :key="String(key)" style="margin-bottom: 2px;">
                            <span style="color: var(--el-color-primary);">{{ key }}</span>: {{ typeof val === 'string' ? val : JSON.stringify(val) }}
                          </div>
                        </div>
                      </div>

                      <!-- 确认/取消按钮区域 -->
                      <!-- NOTE: confirmedIds 必须用数组而非 Set，因为 Vue 3 不追踪 Set.add() 的响应式变化 -->
                      <div v-if="!confirmedIds.includes(item.event.data?.confirm_id)" style="display: flex; gap: 8px;">
                        <el-button
                          type="primary"
                          size="small"
                          :loading="confirmLoading === item.event.data?.confirm_id"
                          :disabled="!!confirmLoading && confirmLoading !== item.event.data?.confirm_id"
                          @click="handleConfirm(item.event.data?.confirm_id, 'confirm')"
                        >
                          <el-icon><Check /></el-icon> 确认执行
                        </el-button>
                        <el-button
                          size="small"
                          :disabled="!!confirmLoading && confirmLoading !== item.event.data?.confirm_id"
                          @click="handleConfirm(item.event.data?.confirm_id, 'reject')"
                        >
                          取消
                        </el-button>
                      </div>
                      <!-- 用户已操作后展示操作结果标签，替代按钮 -->
                      <div v-else style="display: flex; align-items: center; gap: 6px; margin-top: 8px;">
                        <el-tag v-if="confirmActionMap[item.event.data?.confirm_id] === 'confirm'" type="success" size="small">
                          ✅ 已确认执行，等待后端处理...
                        </el-tag>
                        <el-tag v-else-if="confirmActionMap[item.event.data?.confirm_id] === 'reject'" type="info" size="small">
                          ❌ 已拒绝，等待后端处理...
                        </el-tag>
                        <el-tag v-else size="small" type="warning">⏳ 处理中...</el-tag>
                      </div>
                    </template>

                    <!-- ⑭ 确认结果 -->
                    <template v-else-if="item.event.event === 'user_confirm_result'">
                      <div style="margin-bottom: 8px; font-weight: 600;">
                        <el-tag v-if="item.event.data?.action === 'confirm'" size="small" type="success">✅ 用户已确认</el-tag>
                        <el-tag v-else-if="item.event.data?.action === 'reject'" size="small" type="info">❌ 用户已拒绝</el-tag>
                      </div>
                      <div style="font-size: 0.85rem; color: var(--color-text-secondary); padding: 8px; background: var(--color-bg-secondary); border-radius: 4px;">
                        {{ item.event.data?.message || (item.event.data?.action === 'confirm' ? '操作将继续执行' : '操作已取消') }}
                      </div>
                    </template>

                    <!-- ⑮ 错误分析开始（error_analysis_start） -->
                    <template v-else-if="item.event.event === 'error_analysis_start'">
                      <div style="margin-bottom: 6px; font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <el-tag size="small" type="danger" effect="plain">
                          🔴 开始错误智能分析
                        </el-tag>
                        <span style="font-size: 0.8rem; color: var(--color-text-muted);">
                          迭代 {{ item.event.iteration + 1 }}
                        </span>
                        <el-tag v-if="item.event.data?.failed_count" size="small" type="danger" effect="dark">
                          {{ item.event.data.failed_count }} 个步骤失败
                        </el-tag>
                      </div>
                      <div style="font-size: 0.85rem; color: var(--el-color-warning-dark-2); padding: 8px 12px; background: var(--el-color-warning-light-9); border-radius: 6px; border-left: 3px solid var(--el-color-warning);">
                        {{ item.event.data?.message || 'Agent 正在分析错误根因并制定修复方案...' }}
                      </div>
                    </template>

                    <!-- ⑭ 错误根因分析结果（error_analysis 核心卡片） -->
                    <template v-else-if="item.event.event === 'error_analysis'">
                      <div style="margin-bottom: 10px; font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <el-tag size="small" type="danger" effect="dark">🧠 错误根因分析</el-tag>
                        <el-tag size="small" type="warning" effect="plain">
                          {{ item.event.data?.failed_count || 0 }} 个步骤失败
                        </el-tag>
                        <span style="font-size: 0.75rem; color: var(--color-text-muted);">
                          迭代 {{ item.event.iteration + 1 }}
                        </span>
                      </div>

                      <!-- 失败步骤列表 -->
                      <div v-if="item.event.data?.errors?.length" style="margin-bottom: 12px;">
                        <div style="font-size: 0.75rem; font-weight: 600; color: var(--el-color-danger); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em;">
                          失败步骤详情
                        </div>
                        <div
                          v-for="(err, eIdx) in item.event.data.errors"
                          :key="'err-'+eIdx"
                          style="margin-bottom: 8px; padding: 8px 10px; background: var(--el-color-danger-light-9); border-radius: 6px; border-left: 3px solid var(--el-color-danger); font-size: 0.82rem;"
                        >
                          <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 4px; flex-wrap: wrap;">
                            <el-tag size="small" type="danger" effect="plain">{{ err.error_type || 'Error' }}</el-tag>
                            <span style="font-weight: 600; color: var(--color-text-primary);">{{ err.step_desc }}</span>
                          </div>
                          <div style="color: var(--el-color-danger-dark-2); margin-bottom: 4px;">
                            <strong>错误：</strong>{{ err.error_msg }}
                          </div>
                          <div v-if="err.suggestion" style="color: var(--color-text-secondary);">
                            <strong>建议：</strong>{{ err.suggestion }}
                          </div>
                        </div>
                      </div>

                      <!-- LLM 分析的根本原因 -->
                      <div v-if="item.event.data?.root_cause" style="margin-bottom: 12px; padding: 10px 12px; border-radius: 6px; background: var(--el-color-warning-light-9); border-left: 3px solid var(--el-color-warning);">
                        <div style="font-size: 0.75rem; font-weight: 600; color: var(--el-color-warning-dark-2); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em;">
                          🔍 根本原因 (LLM 分析)
                        </div>
                        <div style="font-size: 0.85rem; color: var(--color-text-primary); line-height: 1.6;">
                          {{ item.event.data.root_cause }}
                        </div>
                      </div>

                      <!-- 改进建议列表 -->
                      <div v-if="item.event.data?.suggestions?.length" style="margin-bottom: 12px;">
                        <div style="font-size: 0.75rem; font-weight: 600; color: var(--color-text-muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em;">
                          💡 改进建议
                        </div>
                        <div
                          v-for="(sug, sIdx) in (item.event.data.suggestions || [])"
                          :key="'sug-'+sIdx"
                          style="display: flex; align-items: flex-start; gap: 8px; margin-bottom: 6px; font-size: 0.83rem; padding: 6px 10px; background: var(--color-bg-secondary); border-radius: 6px;"
                        >
                          <span style="color: var(--el-color-primary); font-weight: 700; flex-shrink: 0;">{{ Number(sIdx) + 1 }}.</span>
                          <span style="color: var(--color-text-primary);">{{ sug }}</span>
                        </div>
                      </div>

                      <!-- 修正执行计划 -->
                      <div v-if="item.event.data?.corrective_plan" style="padding: 10px 12px; border-radius: 6px; background: var(--el-color-primary-light-9); border-left: 3px solid var(--el-color-primary-light-5);">
                        <div style="font-size: 0.75rem; font-weight: 600; color: var(--el-color-primary); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em;">
                          🔄 修正执行计划
                        </div>
                        <div style="font-size: 0.85rem; color: var(--color-text-primary); line-height: 1.6;">
                          {{ item.event.data.corrective_plan }}
                        </div>
                      </div>
                    </template>


                    
                    <!-- ⑬ 全局错误 -->
                    <template v-else-if="item.event.event === 'error'">
                      <div style="margin-bottom: 8px; font-weight: 600;">
                        <el-tag size="small" type="danger">❌ 执行错误</el-tag>
                      </div>
                      <div style="font-size: 0.85rem; color: var(--el-color-danger); padding: 8px; background: var(--el-color-danger-light-9); border-radius: 4px;">
                        {{ item.event.error || '未知错误' }}
                      </div>
                    </template>
                    
                    <!-- ⑭ 其他未知事件（兜底展示） -->
                    <template v-else>
                      <div style="font-size: 0.8rem; color: var(--color-text-muted);">
                        <el-tag size="small" type="info">{{ item.event.event }}</el-tag>
                        <span style="margin-left: 8px;">{{ item.event.data?.message || '' }}</span>
                      </div>
                    </template>
                            </template>
                          </div>
                        </el-timeline-item>
                      </el-timeline>
                    </div>
                  </div>
                </div>

              </div>
              <transition name="el-fade-in">
                <button
                  v-show="showScrollToBottomButton"
                  type="button"
                  class="scroll-to-bottom-btn"
                  aria-label="滚动到底部"
                  @click="scrollToLatestEvent"
                >
                  <el-icon :size="18"><ArrowDown /></el-icon>
                </button>
              </transition>
            </div>
            <!-- 流式进行中的加载状态 -->
            <div v-else-if="isStreaming" class="loading-container">
              <el-empty description="等待执行事件..." :image-size="60" />
            </div>
            
            <!-- 原有非流式展示逻辑（executeResult 存在但没有流式事件时使用） -->
            <div v-else-if="executeResult">
              <!-- Message列表 -->
              <el-timeline-item
                v-for="(msg, index) in executeResult?.messages || []"
                :key="'msg-'+index"
                type="info"
                :hollow="true"
                size="large"
              >
                <div :data-event-type="msg.type || 'system_log'" class="trajectory-content" style="margin-top: 0;">
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
                  <div :data-event-type="step.action" class="trajectory-content" style="margin-top: 0;">
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
            </div>
          </div>

          <!-- 执行错误 -->
          <div v-if="executeError" class="error-section">
            <el-alert :title="executeError" type="error" show-icon :closable="false" />
          </div>

          <!-- 底部：任务输入区（像聊天框一样固定在底部） -->
          <div class="task-section" style="margin-top: auto; padding: 16px; border-top: 1px solid var(--color-border); background: var(--color-bg-primary); z-index: 10;">
            <div style="margin-bottom: 12px; display: flex; align-items: center; gap: 12px;">
              <label class="input-label" style="margin-bottom: 0;">会话 ID</label>
              <el-input 
                v-model="conversationId" 
                placeholder="可选：输入相同会话 ID 以保持多轮任务的上下文记忆" 
                :disabled="executing"
                clearable
                style="width: 350px;" 
              >
                <template #prefix>
                  <el-icon><ChatDotRound /></el-icon>
                </template>
              </el-input>
              <el-tooltip content="相同会话 ID 下的多次任务，Agent 会记得你们之前聊过的内容；留空则表示全新会话" placement="top">
                <el-icon style="color: var(--color-text-muted); cursor: help;"><InfoFilled /></el-icon>
              </el-tooltip>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: flex-end;">
              <label class="input-label">任务指令</label>
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
              :autosize="{ minRows: 3, maxRows: 6 }"
              placeholder="描述你想要 Agent 完成的任务...&#10;例如：帮我算一下 100 * 365 并写一首庆祝的诗"
              :disabled="executing"
              @keydown.ctrl.enter="handleExecute"
              @keydown.meta.enter="handleExecute"
            />
            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 10px;">
               <span style="font-size: 0.75rem; color: var(--color-text-muted);">提示: Cmd/Ctrl + Enter 快捷执行</span>
               <el-button
                 type="primary"
                 size="large"
                 :loading="executing"
                 :disabled="!taskInput.trim()"
                 :icon="CaretRight"
                 @click="handleExecute"
                 style="width: 200px;"
               >
                 {{ executing ? (isStreaming ? 'Agent 正在流式执行中...' : 'Agent 执行中...') : '发送任务' }}
               </el-button>
            </div>
            
            <!-- 流式执行状态指示 -->
            <div v-if="isStreaming" class="stream-status" style="margin-top: 12px;">
              <el-icon class="stream-status-icon"><Loading /></el-icon>
              <span class="stream-status-text">{{ getStreamStatusText() }}</span>
              <span v-if="!streamEvents.length" class="stream-status-hint">等待连接...</span>
              <span v-else class="stream-events-count">{{ streamEvents.length }} 个事件</span>
            </div>
          </div>

        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, nextTick } from 'vue'
import { Setting, Refresh, CaretRight, DataLine, WarningFilled, User, Loading, Aim, Check, Promotion, Cpu, MagicStick, ChatDotRound, Finished, Sunrise, UserFilled, ArrowDown, InfoFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getAgentList, executeAgent, executeAgentStream, confirmAgentAction } from '@/api/modules/agents'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import type { AgentInfo, AgentExecuteResponse } from '@/types/agent'

// 流式事件类型定义
interface StreamEvent {
  event: string
  iteration: number
  step_index?: number
  step_total?: number
  data?: any
  error?: string
  timestamp: number
}

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

/** 按主/子 Agent 划分的独立控制区块 */
interface AgentBlock {
  type: 'main' | 'sub';
  id: string; // 'main-xxx' 或 sub_agent_id
  name: string; // 主Agent名称或子Agent名称
  task: string | null;
  events: StreamEvent[];
}

/** 每次独立迭代的大组 */
interface IterationGroup {
  iteration: number;
  blocks: AgentBlock[];
}

const agents = ref<AgentInfo[]>([])
const selectedAgent = ref<AgentInfo | null>(null)
const loadingAgents = ref<boolean>(false)
const taskInput = ref<string>('')
const conversationId = ref<string>('')
const executing = ref<boolean>(false)
const executeResult = ref<AgentExecuteResponse | null>(null)
const executeError = ref<string>('')

// 流式执行相关状态
const streamEvents = ref<StreamEvent[]>([])  // 流式事件列表
const isStreaming = ref<boolean>(false)      // 是否正在流式接收
const currentStreamEvent = ref<StreamEvent | null>(null)  // 当前正在处理的事件
const confirmLoading = ref<string | null>(null)  // 当前正在处理中的 confirm_id（显示 loading 状态）
// NOTE: 必须使用 string[] 数组而非 Set，因为 Vue 3 对 Set 的 .add() 操作不能触发响应式更新
//       直接替换整个 ref 数组（展开运算符）才能让模板中的 v-if 正常响应
const confirmedIds = ref<string[]>([])  // 已操作过（点击确认或取消）的 confirm_id 列表
const confirmActionMap = ref<Record<string, 'confirm' | 'reject'>>({})  // 记录每个 confirm_id 对应的操作类型

// 计算当前执行阶段（用于进度指示器）
type ExecutionPhase = 'idle' | 'planning' | 'executing' | 'reflecting' | 'completed'
const currentPhase = computed<ExecutionPhase>(() => {
  if (!currentStreamEvent.value) return 'idle'
  const event = currentStreamEvent.value.event
  
  if (event === 'complete') return 'completed'
  if (['plan_start', 'plan_complete'].includes(event)) return 'planning'
  if (['step_start', 'tool_complete', 'skill_complete', 'delegate_complete', 'step_complete', 'execute_complete'].includes(event)) return 'executing'
  if (['reflection_start', 'reflection_complete'].includes(event)) return 'reflecting'
  
  return 'planning' // 默认
})

// 计算进度百分比
const progressPercent = computed<number>(() => {
  const phase = currentPhase.value
  switch (phase) {
    case 'idle': return 0
    case 'planning': return 20
    case 'executing': return 50
    case 'reflecting': return 80
    case 'completed': return 100
    default: return 0
  }
})

// 轨迹区域滚动：仅当用户已在底部时才自动滚到底；否则显示“回到底部”按钮
const streamEventsContainer = ref<HTMLElement | null>(null)
/** 用户是否处于轨迹区域底部（用于决定新消息是否自动滚到底） */
const userAtBottom = ref(true)
const SCROLL_BOTTOM_THRESHOLD = 60

function onTrajectoryScroll(e: Event) {
  const el = e.target as HTMLElement
  if (!el || el !== streamEventsContainer.value) return
  const { scrollTop, clientHeight, scrollHeight } = el
  userAtBottom.value = scrollTop + clientHeight >= scrollHeight - SCROLL_BOTTOM_THRESHOLD
}

/** 有事件且用户已上滑（不在底部）时显示“回到底部”按钮 */
const showScrollToBottomButton = computed(() => streamEvents.value.length > 0 && !userAtBottom.value)

function scrollToLatestEvent() {
  nextTick(() => {
    if (streamEventsContainer.value) {
      streamEventsContainer.value.scrollTop = streamEventsContainer.value.scrollHeight
      userAtBottom.value = true
    }
  })
}

/** 轨迹展开折叠状态管理 */
const expansionState = ref<Record<string, boolean>>({})

function toggleExpansion(key: string) {
  expansionState.value[key] = !expansionState.value[key]
}

/**
 * 将流式事件按迭代（Iteration）和嵌套区块（主/子 Agent）进行树状结构编排。
 * 
 * NOTE: 后端 iteration 字段的含义是"已完成的迭代次数"：
 *   - iteration: 0 表示正在进行第1次迭代
 *   - iteration: 1 表示已完成1次迭代（通常出现在 final_answer/complete）
 * 
 * 因此我们需要将 iteration > 0 的 final_answer/complete 事件归入前一个迭代组，
 * 而不是创建新的迭代组。
 */
const groupedIterations = computed<IterationGroup[]>(() => {
  const list = streamEvents.value
  const iterationsMap = new Map<number, IterationGroup>()

  for (const ev of list) {
    // 关键修复：final_answer 和 complete 的 iteration 可能比其他事件大1
    // 这表示"已完成X次迭代"，而非"新的迭代"，需要归入前一个迭代组
    let actualIteration = ev.iteration
    
    // 如果是 final_answer 或 complete 且 iteration > 0，归入 iteration-1 组
    if (['final_answer', 'complete'].includes(ev.event) && ev.iteration > 0) {
      actualIteration = ev.iteration - 1
    }
    
    if (!iterationsMap.has(actualIteration)) {
      iterationsMap.set(actualIteration, {
        iteration: actualIteration,
        blocks: []
      })
      // 默认展开最新的迭代
      if (expansionState.value[`iter-${actualIteration}`] === undefined) {
        expansionState.value[`iter-${actualIteration}`] = true
      }
    }
    const iterGroup = iterationsMap.get(actualIteration)!
    
    // 把事件塞进对应的 Agent Block 里
    if (ev.event === 'sub_agent_start') {
       const subId = ev.data?.sub_agent_id || 'sub'
       iterGroup.blocks.push({
         type: 'sub',
         id: subId,
         name: ev.data?.sub_agent_name || subId,
         task: ev.data?.task || null,
         events: [ev]
       })
       // 子 Agent 默认展开
       if (expansionState.value[`block-${actualIteration}-${subId}`] === undefined) {
         expansionState.value[`block-${actualIteration}-${subId}`] = true
       }
    } else if (ev.event === 'sub_agent_end') {
       const lastBlock = iterGroup.blocks[iterGroup.blocks.length - 1]
       if (lastBlock && lastBlock.type === 'sub') {
         lastBlock.events.push(ev)
       }
    } else if (ev.data?.is_sub_agent) {
       const lastBlock = iterGroup.blocks[iterGroup.blocks.length - 1]
       if (lastBlock && lastBlock.type === 'sub') {
         lastBlock.events.push(ev)
       } else {
         iterGroup.blocks.push({
           type: 'sub',
           id: 'unknown',
           name: '未知子Agent',
           task: null,
           events: [ev]
         })
       }
    } else {
       // 主 Agent 事件
       const lastBlock = iterGroup.blocks[iterGroup.blocks.length - 1]
       if (lastBlock && lastBlock.type === 'main') {
         lastBlock.events.push(ev)
       } else {
           const blockId = 'main-' + iterGroup.blocks.length
           iterGroup.blocks.push({
             type: 'main',
             id: blockId,
             name: selectedAgent.value?.name || '主Agent',
             task: null,
             events: [ev]
           })
           // 主 Agent 块默认展开
           if (expansionState.value[`block-${actualIteration}-${blockId}`] === undefined) {
              expansionState.value[`block-${actualIteration}-${blockId}`] = true
           }
       }
    }
  }
  return Array.from(iterationsMap.values())
})

/** 子 Agent 内单条事件的阶段标签（用于区块内紧凑展示） */
function getSubEventPhaseLabel(event: StreamEvent): string {
  const e = event.event
  if (e === 'plan_start') return '规划开始'
  if (e === 'plan_complete') return '规划完成'
  if (e === 'step_start') return '开始执行'
  if (e === 'tool_complete') return `${event.data?.tool_name ?? '工具'}`
  if (e === 'skill_complete') return `${event.data?.skill_id ?? '技能'}`
  if (e === 'user_confirm_required') return `用户确认 · ${event.data?.tool_name ?? '操作'}`
  if (e === 'user_confirm_result') return '确认结果'
  if (e === 'step_complete') return '步骤完成'
  if (e === 'execute_complete') return '执行阶段完成'
  if (e === 'reflection_start') return '反思开始'
  if (e === 'reflection_complete') return '反思完成'
  return e
}

/**
 * 按子 Agent ID 返回主题 CSS 变量，用于区块标题与内联事件的配色区分。
 * 与现有主题兼容，使用区分度高的色相：通用助手(青绿)、订单(蓝)、退款(橙)、其他(紫)。
 */
const SUB_AGENT_THEMES: Record<string, { accent: string; rgb: string }> = {
  general_agent: { accent: '#0d9488', rgb: '13, 148, 136' },   /* teal-600 通用助手 */
  order_agent: { accent: '#2563eb', rgb: '37, 99, 235' },       /* blue-600 订单专员 */
  refund_agent: { accent: '#ea580c', rgb: '234, 88, 12' },     /* orange-600 退款专员 */
}

const SUB_AGENT_FALLBACK_PALETTE = [
  { accent: '#7c3aed', rgb: '124, 58, 237' },  /* violet-600 */
  { accent: '#059669', rgb: '5, 150, 105' },   /* emerald-600 */
  { accent: '#dc2626', rgb: '220, 38, 38' },  /* red-600 */
]

function getSubAgentTheme(agentId: string | null): Record<string, string> {
  if (!agentId) return {}
  const theme = SUB_AGENT_THEMES[agentId] ?? SUB_AGENT_FALLBACK_PALETTE[Math.abs(agentId.split('').reduce((a, c) => a + c.charCodeAt(0), 0)) % SUB_AGENT_FALLBACK_PALETTE.length]
  return {
    '--sub-agent-accent': theme.accent,
    '--sub-agent-accent-rgb': theme.rgb,
    '--sub-agent-bg-light': `rgba(${theme.rgb}, 0.08)`,
    '--sub-agent-bg-medium': `rgba(${theme.rgb}, 0.14)`,
    '--sub-agent-border': `rgba(${theme.rgb}, 0.35)`,
    '--sub-agent-shadow': `0 2px 8px rgba(${theme.rgb}, 0.12)`,
  }
}

/**
 * 判断当前事件是否为流式轨迹中的「最后一条」。
 * 当下一步尚未执行时，最后一条的标题与文字会加上律动动画，提示用户大模型正在思考/回复。
 */
function isLastStreamEvent(iterGroup: IterationGroup, block: AgentBlock, eIdx: number): boolean {
  const groups = groupedIterations.value
  if (!groups.length) return false
  const lastIter = groups[groups.length - 1]
  if (iterGroup !== lastIter) return false
  if (!lastIter.blocks.length) return false
  const lastBlock = lastIter.blocks[lastIter.blocks.length - 1]
  if (block !== lastBlock) return false
  return eIdx === block.events.length - 1
}

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
  streamEvents.value = []
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
  streamEvents.value = []
  currentStreamEvent.value = null
  console.log('[AgentView] 已选择 Agent:', agent.agent_id)
}

/**
 * 处理流式事件
 * 将流式事件转换为展示所需的数据格式
 * 
 * 事件类型（按执行顺序）：
 *   plan_start → plan_complete → step_start
 *   → tool_complete/skill_complete/delegate_complete (多次)
 *   → execute_complete → reflection_start → reflection_complete
 *   → (如需重规划，回到 plan_start)
 *   → final_answer → complete
 */
function handleStreamEvent(event: StreamEvent): void {
  console.log(
    `[AgentView] 收到流式事件: ${event.event}`,
    `| 迭代: ${event.iteration}`,
    event.step_index !== undefined ? `| 步骤: ${event.step_index}/${event.step_total}` : '',
    event.data ? `| data:` : '',
    event.data
  )
  
  // 新一轮执行的首条事件时视为“在底部”，保证会滚到底
  if (streamEvents.value.length === 0) userAtBottom.value = true
  streamEvents.value.push(event)
  currentStreamEvent.value = event

  // 仅当用户当前在底部时才自动滚到底，避免打断用户查看历史轨迹
  if (userAtBottom.value) scrollToLatestEvent()
  
  // 根据事件类型更新 UI 状态
  switch (event.event) {
    case 'plan_start':
      console.log(`[AgentView] ① 规划开始，迭代 ${event.iteration + 1}`)
      break
      
    case 'plan_complete':
      console.log(`[AgentView] ② 规划完成，步骤数: ${event.data?.steps?.length ?? 0}`)
      break
      
    case 'step_start':
      console.log(`[AgentView] ③ 执行阶段开始，共 ${event.step_total} 个步骤`)
      break
      
    case 'tool_complete':
      console.log(`[AgentView] ④ 工具调用完成: ${event.data?.tool_name}，成功: ${event.data?.success}`)
      break
      
    case 'step_complete':
      console.log(`[AgentView] ⑤ 步骤完成: ${event.data?.step_name || event.data?.action}，成功: ${event.data?.success}`)
      break
      
    case 'skill_complete':
      console.log(`[AgentView] ⑤ 技能调用完成: ${event.data?.skill_id}，成功: ${event.data?.success}`)
      break
      
    case 'delegate_complete':
      console.log(`[AgentView] ⑥ 子Agent委派完成: ${event.data?.agent_id}，成功: ${event.data?.success}`)
      break
      
    case 'execute_complete':
      console.log(`[AgentView] ⑦ 执行阶段完成，成功: ${event.data?.success}`)
      break

    case 'user_confirm_required':
      // 后端推送字段：tool_name（工具名）、confirm_id（唯一确认ID）、params（参数）、message（描述）
      // 无论是主 Agent 还是子 Agent 触发的确认，都通过同一 SSE 流传来
      console.log(
        `[AgentView] ⚠️ 需要用户确认 — tool: ${event.data?.tool_name}，confirm_id: ${event.data?.confirm_id}`,
        '\nparams:', event.data?.params
      )
      // 注意：不要在这里设置 confirmLoading，否则按钮一开始就会被禁用
      // confirmLoading 只在用户点击按钮后设置为 loading 状态，防止重复提交
      break

    case 'user_confirm_result':
      console.log(`[AgentView] 用户确认结果: ${event.data?.action}，message: ${event.data?.message}，设置 confirmLoading = null`)
      confirmLoading.value = null
      console.log(`[AgentView] confirmLoading 重置后: ${confirmLoading.value}`)
      break

    case 'sub_agent_start':
      // 子 Agent 开始执行，记录日志
      console.log(
        `[AgentView] 🤖 子 Agent 开始 — id: ${event.data?.sub_agent_id}，name: ${event.data?.sub_agent_name}，task: ${event.data?.task}`
      )
      break

    case 'sub_agent_end':
      // 子 Agent 执行结束，记录日志（不在 timeline 中渲染）
      console.log(
        `[AgentView] ✅ 子 Agent 完成 — id: ${event.data?.sub_agent_id}，success: ${event.data?.success}`
      )
      break

    case 'reflection_start':
      console.log(`[AgentView] ⑧ 反思开始，迭代 ${event.iteration + 1}`)
      break
      
    case 'reflection_complete':
      console.log(`[AgentView] ⑨ 反思完成，成功: ${event.data?.success}，需重规划: ${event.data?.needs_replanning}`)
      break
      
    case 'final_answer':
      console.log('[AgentView] ⑩ 收到最终答案，结果长度:', JSON.stringify(event.data?.result || '').length)
      break
      
    case 'complete': {
      // 执行完成：更新状态并构建 executeResult
      console.log(`[AgentView] ⑪ 执行完成，成功: ${event.data?.success}，共迭代 ${event.data?.iterations} 次`)
      executing.value = false
      isStreaming.value = false
      
      // 从事件流中找到 final_answer 事件，构建最终展示结构
      const finalAnswerEvent = streamEvents.value.find(e => e.event === 'final_answer')
      if (finalAnswerEvent) {
        // 收集所有工具/技能/委派执行结果（用于非流式展示区的回退）
        const stepResultEvents = streamEvents.value
          .filter(e => ['tool_complete', 'skill_complete', 'delegate_complete', 'step_complete'].includes(e.event))
          .map(e => e.data)
        
        executeResult.value = {
          agent_id: selectedAgent.value?.agent_id || '',
          agent_name: selectedAgent.value?.name || '',
          task: taskInput.value,
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
        }
        console.log('[AgentView] executeResult 构建完成，step_results:', stepResultEvents.length)
      }
      ElMessage.success('Agent 执行完成！')
      break
    }
      
    case 'step_error':
      console.warn(`[AgentView] 步骤执行失败，步骤 ${event.step_index}/${event.step_total}:`, event.error)
      break
      
    case 'error':
      // 全局错误：停止执行并显示错误
      console.error('[AgentView] 执行出错:', event.error)
      executing.value = false
      isStreaming.value = false
      executeError.value = event.error || '执行出错'
      ElMessage.error('Agent 执行出错: ' + (event.error || '未知错误'))
      break
      
    default:
      console.log(`[AgentView] 未知事件类型: ${event.event}`, event.data)
  }
}

/**
 * 处理用户确认/拒绝操作
 */
/**
 * 处理用户确认/拒绝操作
 * 
 * 关键设计：
 * 1. 立即将 confirmId 加入 confirmedIds（通过展开运算符替换整个数组，触发 Vue 响应式）
 * 2. 记录用户选择的操作到 confirmActionMap（用于替换按钮区域显示操作结果标签）
 * 3. 设置 confirmLoading 阻止重复点击（加载状态）
 * 4. 等待 user_confirm_result 流式事件回来后才清空 confirmLoading
 */
async function handleConfirm(confirmId: string | undefined, action: 'confirm' | 'reject'): Promise<void> {
  if (!confirmId) {
    console.warn('[handleConfirm] confirmId 无效，忽略此次点击')
    ElMessage.warning('确认 ID 无效')
    return
  }

  // 防止重复点击：检查是否已经操作过
  if (confirmedIds.value.includes(confirmId)) {
    console.warn(`[handleConfirm] confirm_id=${confirmId} 已操作过，忽略重复点击`)
    return
  }

  console.log(`[handleConfirm] 用户${action === 'confirm' ? '点击确认' : '点击取消'}，confirm_id=${confirmId}`)

  // NOTE: 必须用展开运算符创建新数组，才能触发 Vue 响应式更新
  //       直接 confirmedIds.value.push(confirmId) 可以触发响应式（Vue 3 对数组方法有追踪）
  //       但为了代码清晰，使用展开运算符确保创建新引用
  confirmedIds.value = [...confirmedIds.value, confirmId]
  console.log(`[handleConfirm] confirmedIds 更新后:`, confirmedIds.value)

  // 记录用户操作类型，用于替换按钮区域展示操作结果标签
  confirmActionMap.value = { ...confirmActionMap.value, [confirmId]: action }
  console.log(`[handleConfirm] confirmActionMap 更新后:`, confirmActionMap.value)

  // 设置加载状态（显示 loading spinner），防止网络延迟期间误操作
  confirmLoading.value = confirmId
  console.log(`[handleConfirm] confirmLoading 设置为: ${confirmLoading.value}`)

  try {
    console.log(`[AgentView] 正在发送确认请求到后端 — confirmId: ${confirmId}, action: ${action}`)
    const result = await confirmAgentAction(confirmId, action)
    console.log('[AgentView] 后端确认响应:', result)
    ElMessage.success(action === 'confirm' ? '✅ 已确认，Agent 将继续执行' : '❌ 已拒绝，Agent 将跳过该操作')
    // NOTE: 不在这里重置 confirmLoading，等待流式事件 user_confirm_result 回来后再重置
    //       这样在网络往返过程中按钮保持 loading 状态，避免用户再次点击
  } catch (error) {
    console.error('[AgentView] 发送确认请求失败:', error)
    ElMessage.error('确认操作失败: ' + (error instanceof Error ? error.message : '未知错误'))
    // API 调用失败时重置状态，但不从 confirmedIds 中移除（让用户可以重试）
    confirmLoading.value = null
    // 移除刚才加入的 confirmId（恢复按钮显示）
    confirmedIds.value = confirmedIds.value.filter(id => id !== confirmId)
    delete confirmActionMap.value[confirmId]
    confirmActionMap.value = { ...confirmActionMap.value }
  }
}

/**
 * 执行选中的 Agent（使用流式）
 */
async function handleExecute(): Promise<void> {
  if (!selectedAgent.value || !taskInput.value.trim()) return

  // 重置状态
  executing.value = true
  isStreaming.value = true
  executeResult.value = null
  executeError.value = ''
  streamEvents.value = []
  currentStreamEvent.value = null
  confirmLoading.value = null
  confirmedIds.value = []  // NOTE: 重置时直接赋值新数组，触发响应式
  confirmActionMap.value = {}  // 同步清空操作记录 Map

  try {
    console.log('[AgentView] 开始流式执行 Agent:', selectedAgent.value.agent_id)
    
    // 使用流式 API
    executeAgentStream(
      selectedAgent.value.agent_id,
      {
        task: taskInput.value,
        conversation_id: conversationId.value.trim() || undefined,
      },
      // 消息回调
      (event) => {
        handleStreamEvent(event)
      },
      // 错误回调
      (error) => {
        console.error('[AgentView] 流式执行错误:', error)
        executing.value = false
        isStreaming.value = false
        executeError.value = error?.message || '流式执行失败'
        ElMessage.error('流式执行失败: ' + error?.message)
      },
      // 完成回调
      (data) => {
        console.log('[AgentView] 流式执行完成，数据:', data)
      }
    )
    
  } catch (error) {
    const errMsg = error instanceof Error ? error.message : '执行失败'
    executeError.value = errMsg
    executing.value = false
    isStreaming.value = false
    console.error('[AgentView] Agent 执行失败:', error)
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

/**
 * 获取当前流式执行状态的描述文字
 * 在执行按钮下方的状态条中显示
 */
function getStreamStatusText(): string {
  if (!isStreaming.value) return ''
  
  const event = currentStreamEvent.value
  if (!event) return '正在启动连接...'
  
  switch (event.event) {
    case 'plan_start':      return `🧠 正在分析任务，制定计划... (迭代 ${event.iteration + 1})`
    case 'plan_complete':   return `✅ 计划制定完成，共 ${event.data?.steps?.length ?? 0} 个步骤`
    case 'step_start':      return `⚙️ 开始执行计划，共 ${event.step_total} 个步骤`
    case 'tool_complete':   return `🔧 工具调用完成: ${event.data?.tool_name || 'unknown'} (${event.step_index}/${event.step_total})`
    case 'skill_complete':  return `✨ 技能调用完成: ${event.data?.skill_id || 'unknown'} (${(event.step_index || 0)}/${event.step_total})`
    case 'delegate_complete': return `🤖 子Agent完成: ${event.data?.agent_id || 'unknown'} (${(event.step_index || 0)}/${event.step_total})`
    case 'execute_complete':  return `✅ 执行阶段完成，共 ${event.step_total} 个步骤 (${(event.step_index || 0)}/${event.step_total})`
    case 'reflection_start':  return `🔍 正在自我反思，评估执行质量... (迭代 ${event.iteration + 1})`
    case 'reflection_complete': return event.data?.needs_replanning ? '⚠️ 反思发现问题，准备重新规划' : '💭 反思完成'
    case 'final_answer':    return '🎯 生成最终答案...'
    case 'complete':        return '✅ 执行完成'
    case 'step_error':      return `⚠️ 步骤 ${event.step_index} 执行失败，继续...`
    case 'error':           return `❌ 执行出错`
    default:                return `处理中: ${event.event}`
  }
}

/**
 * 根据事件类型获取时间线颜色类型
 * 对应 Element Plus el-timeline-item 的 type 属性
 */
function getEventTimelineType(eventType: string): string {
  switch (eventType) {
    case 'plan_start':
    case 'plan_complete':
      return 'primary'
    case 'step_start':
    case 'execute_complete':
      return 'info'
    case 'tool_complete':
    case 'skill_complete':
      return 'success'
    case 'delegate_complete':
    case 'sub_agent_start':
      return 'primary'
    case 'reflection_start':
    case 'reflection_complete':
      return 'warning'
    case 'final_answer':
    case 'complete':
      return 'success'
    case 'step_error':
    case 'error':
    // NOTE: 错误分析事件统一使用 danger 类型，与整体异常风格一致
    case 'error_analysis_start':
    case 'error_analysis':
      return 'danger'
    default:
      return 'info'
  }
}

/**
 * 判断事件是否为重要事件（应该显示为实心点）
 * 重要事件包括：plan_start, plan_complete, step_complete, tool_complete, skill_complete, delegate_complete, reflection_complete, final_answer, complete
 */
function isImportantEvent(eventType: string): boolean {
  return [
    'plan_start',
    'plan_complete',
    'sub_agent_start',
    'step_complete',
    'tool_complete',
    'skill_complete',
    'delegate_complete',
    'reflection_complete',
    'error_analysis',
    'final_answer',
    'complete'
  ].includes(eventType)
}

/**
 * 根据事件重要程度获取时间线节点大小
 * 重要事件（规划开始、规划完成、步骤完成、最终答案、完成）使用 large 尺寸突出显示
 * 这样可以保证时间线节点与连接线对齐
 */
function getEventTimelineSize(eventType: string): 'normal' | 'large' | 'small' {
  switch (eventType) {
    case 'plan_start':
    case 'plan_complete':
    case 'sub_agent_start':
    case 'step_complete':
    case 'tool_complete':
    case 'skill_complete':
    case 'delegate_complete':
    case 'reflection_complete':
    case 'error_analysis':
    case 'final_answer':
    case 'complete':
      return 'large'
    case 'step_start':
    case 'execute_complete':
    case 'reflection_start':
    case 'error_analysis_start':
      return 'normal'
    default:
      return 'normal'
  }
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

/* 右侧执行面板 - 改为 flex 列布局，使轨迹区可滚动，输入栏固定底部 */
.execution-panel {
  flex: 1;
  overflow: hidden; /* 不在面板级别滚动，内部子区域自己控制滚动 */
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 0; /* 让 flex 子项能够正确压缩 */
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

/* ── Agent 使用说明 tooltip 样式 ── */
.info-icon {
  cursor: pointer;
  transition: color 0.2s ease;
}

.info-icon:hover {
  color: var(--color-primary);
}

.agent-usage-guide {
  padding: 12px 16px;
}

.agent-usage-guide p {
  margin: 0 0 8px 0;
  line-height: 1.6;
}

.agent-usage-guide p:last-child {
  margin-bottom: 0;
}

/* 选中 Agent 的头部信息（重新设计） */
.selected-agent-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 20px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08) 0%, rgba(139, 92, 246, 0.06) 100%);
  border-radius: 12px;
  border: 1px solid rgba(99, 102, 241, 0.2);
  box-shadow: 0 2px 12px rgba(99, 102, 241, 0.08);
}

.selected-agent-info {
  flex: 1;
  min-width: 0;
}

.selected-agent-avatar {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.25);
}

.selected-agent-name {
  font-weight: 700;
  font-size: 1.05rem;
  color: var(--color-text-primary);
  margin-bottom: 4px;
}

.selected-agent-desc {
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  line-height: 1.4;
}

.selected-agent-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}

.meta-item {
  font-size: 0.72rem;
  color: var(--color-text-muted);
  background: rgba(255, 255, 255, 0.8);
  padding: 3px 10px;
  border-radius: var(--radius-full);
  border: 1px solid rgba(99, 102, 241, 0.15);
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

/* =====================================================
 * 轨迹展示区 - Agent 执行流程可视化
 * 设计风格：Bento Grid + Glassmorphism + 阶段式进度
 * ===================================================== */

/* 整体容器 - 增加高度占比 */
.trajectory-section {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* 头部：标题 + 流程进度指示器 */
.trajectory-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: var(--gradient-primary-soft);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
}

.trajectory-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--color-text-primary);
}

/* 流程进度指示器（4个阶段） */
.trajectory-progress {
  display: flex;
  align-items: center;
  gap: 4px;
}

.trajectory-progress-step {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: var(--radius-full);
  font-size: 0.7rem;
  font-weight: 500;
  color: var(--color-text-muted);
  background: var(--color-bg-secondary);
  transition: all var(--transition-normal);
  white-space: nowrap;
}

.trajectory-progress-step.active {
  color: white;
  background: var(--color-primary);
  box-shadow: var(--shadow-sm);
}

.trajectory-progress-step.completed {
  color: var(--color-success);
  background: var(--el-color-success-light-9);
}

.trajectory-progress-step .step-icon {
  width: 14px;
  height: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.trajectory-progress-divider {
  width: 16px;
  height: 2px;
  background: var(--color-border);
  border-radius: 1px;
}

:deep(.el-tag__content) {
  display: flex;
  gap: 4px;
  align-items: center;
  justify-content: center;
}

/* =====================================================
 * 流式执行状态条
 * ===================================================== */
.stream-status {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  background: linear-gradient(135deg, rgba(124, 58, 237, 0.08) 0%, rgba(6, 182, 212, 0.08) 100%);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: 0.85rem;
  color: var(--color-primary);
}

.stream-status .stream-status-icon {
  font-size: 18px;
  animation: spin 1s linear infinite;
  color: var(--color-primary);
}

.stream-status-text {
  flex: 1;
  font-weight: 500;
  color: var(--color-text-primary);
}

.stream-status-hint {
  font-size: 0.8rem;
  color: var(--color-text-muted);
  font-style: italic;
}

.stream-events-count {
  font-size: 0.75rem;
  padding: 2px 8px;
  background: var(--color-bg-secondary);
  border-radius: var(--radius-full);
  color: var(--color-text-muted);
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 实时更新标记 */
.streaming-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  background: linear-gradient(135deg, var(--el-color-success-light-9) 0%, #ecfdf5 100%);
  border: 1px solid var(--el-color-success-light-5);
  border-radius: var(--radius-full);
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--el-color-success);
}

.streaming-dot {
  width: 8px;
  height: 8px;
  background: var(--el-color-success);
  border-radius: 50%;
  animation: pulse 1.5s ease-in-out infinite;
  box-shadow: 0 0 8px var(--el-color-success);
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); box-shadow: 0 0 8px var(--el-color-success); }
  50% { opacity: 0.6; transform: scale(1.2); box-shadow: 0 0 12px var(--el-color-success); }
}

/* =====================================================
 * 流式事件容器
 * 改进：使用 Bento Grid 风格的事件卡片，增加高度
 * ===================================================== */
.stream-events-wrapper {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.stream-events-container {
  /* 增加高度：从 calc(100vh - 380px) 改为更大的值 */
  flex: 1;
  overflow-y: auto;
  padding: 8px 8px 32px 8px;
  min-height: 200px;
}

/* “回到底部”浮动按钮：用户上滑查看轨迹时显示，点击滚到底部 */
.scroll-to-bottom-btn {
  position: absolute;
  right: 16px;
  bottom: 16px;
  width: 40px;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 50%;
  background: var(--el-color-primary);
  color: #fff;
  cursor: pointer;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.15);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  z-index: 10;
}
.scroll-to-bottom-btn:hover {
  transform: scale(1.05);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
}
.scroll-to-bottom-btn:active {
  transform: scale(0.98);
}

/* 自定义滚动条 */
.stream-events-container::-webkit-scrollbar {
  width: 6px;
}

.stream-events-container::-webkit-scrollbar-track {
  background: var(--color-bg-secondary);
  border-radius: 3px;
}

.stream-events-container::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: 3px;
}

.stream-events-container::-webkit-scrollbar-thumb:hover {
  background: var(--color-primary-light);
}

/* =====================================================
 * 迭代分组区块 & Agent 块 — 新版嵌套 UI
 * 美化：Glassmorphism + Bento Grid 风格
 * ===================================================== */
.iteration-group {
  border-radius: 12px;
  overflow: hidden;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.7) 0%, rgba(248, 250, 252, 0.9) 100%);
  border: 1px solid rgba(229, 231, 235, 0.6);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.iteration-header {
  background: linear-gradient(
    135deg,
    rgba(99, 102, 241, 0.06) 0%,
    rgba(139, 92, 246, 0.04) 50%,
    rgba(236, 72, 153, 0.03) 100%
  ) !important;
  border: 1px solid rgba(99, 102, 241, 0.15) !important;
  border-radius: 10px !important;
  transition: all 0.25s ease;
  backdrop-filter: blur(8px);
}
.iteration-header:hover {
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.12);
  border-color: rgba(99, 102, 241, 0.25) !important;
}

/* 迭代内容区 */
.iteration-content {
  padding: 16px 8px 8px 8px;
}

/* Agent 块容器 */
.agent-block {
  border-left: 3px solid transparent;
  transition: border-color 0.2s ease;
  padding-left: 4px;
  padding-top: 4px;
}

/* 时间轴样式 */
.block-timeline {
  padding-left: 12px;
  padding-top: 16px;
}

/* 子 Agent 区块内时间轴增加额外上边距 */
.sub-block-timeline {
  padding-top: 20px;
  margin-top: 4px;
}

/* 加载容器 */
.loading-container {
  padding: 40px 0;
  text-align: center;
}

.loading-container .el-empty__description {
  color: var(--color-text-muted);
}

/* =====================================================
 * 事件时间轴卡片样式
 * 改进：Bento Grid 风格 + Glassmorphism 效果
 * ===================================================== */
.trajectory-content {
  padding: 16px 18px !important;
  font-size: 0.85rem;
  max-width: 100%;
  overflow-x: auto;
  line-height: 1.6;
  background: var(--color-bg-card);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light);
  transition: all var(--transition-normal);
  margin-top: 0;
}

.trajectory-content:hover {
  border-color: var(--color-primary-light);
  box-shadow: var(--shadow-sm);
}

/* ── Plan Start 规划开始卡片 ── */
.plan-start-header {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 16px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08) 0%, rgba(139, 92, 246, 0.06) 100%);
  border-radius: 10px;
  border: 1px solid rgba(99, 102, 241, 0.2);
}

.plan-start-icon {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  border-radius: 12px;
  color: white;
  flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.25);
}

.plan-start-info {
  flex: 1;
  min-width: 0;
}

.plan-start-title {
  font-size: 1rem;
  font-weight: 700;
  color: var(--color-text-primary);
  margin-bottom: 4px;
}

.plan-start-desc {
  font-size: 0.85rem;
  color: var(--color-text-secondary);
  line-height: 1.5;
}

/* ── Plan Complete 规划完成卡片 ── */
.plan-complete-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--color-border-light);
}

.plan-complete-icon {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  border-radius: 8px;
  color: white;
}

.plan-complete-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--color-text-primary);
}

/* 推理过程区块 */
.reasoning-block {
  padding: 14px 16px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.05) 0%, rgba(139, 92, 246, 0.03) 100%);
  border-radius: 8px;
  border-left: 4px solid #6366f1;
  margin-bottom: 14px;
}

.reasoning-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #6366f1;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 6px;
}

.reasoning-content {
  font-size: 0.88rem;
  color: var(--color-text-primary);
  line-height: 1.6;
}

/* 执行步骤列表 */
.steps-list {
  margin-top: 8px;
}

.steps-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 10px;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  padding: 8px 12px;
  background: var(--color-bg-secondary);
  border-radius: 6px;
  transition: background 0.2s ease;
}

.step-item:hover {
  background: var(--color-bg-card);
}

.step-number {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-primary);
  color: white;
  border-radius: 50%;
  font-size: 0.75rem;
  font-weight: 600;
  flex-shrink: 0;
}

@media (prefers-reduced-motion: reduce) {
  .trajectory-content,
  .sub-agent-block-header,
  .sub-agent-inner-content {
    transition: none;
  }
  .plan-start-icon,
  .tool-icon,
  .reflection-icon,
  .plan-complete-icon,
  .final-answer-icon,
  .complete-icon {
    animation: none;
  }
  .trajectory-content.step-thinking {
    animation: fade-in-up 0.3s ease-out;
  }
}

/* ── 动画效果 ── */
@keyframes pulse-glow {
  0%, 100% { 
    box-shadow: 0 4px 12px rgba(99, 102, 241, 0.25);
    transform: scale(1);
  }
  50% { 
    box-shadow: 0 6px 20px rgba(99, 102, 241, 0.4);
    transform: scale(1.02);
  }
}

@keyframes spin-slow {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes bounce-subtle {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-3px); }
}

/* 大模型正在思考时的律动：下一步未执行时，上一步卡片标题与文字轻微律动，提示用户等待回复 */
@keyframes thinking-pulse {
  0%, 100% {
    opacity: 1;
    box-shadow: 0 0 0 0 rgba(99, 102, 241, 0.12);
  }
  50% {
    opacity: 0.96;
    box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.08);
  }
}

@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

@keyframes fade-in-up {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 规划开始动画 */
.plan-start-icon {
  animation: pulse-glow 2s ease-in-out infinite;
}

/* 工具调用动画 */
.tool-icon {
  animation: bounce-subtle 1.5s ease-in-out infinite;
}

/* 反思图标：已去掉旋转动画，仅使用下方 ── Reflection 反思卡片 ── 中的静态样式 */

/* 规划完成动画 */
.plan-complete-icon {
  animation: pulse-glow 2.5s ease-in-out infinite;
}

/* 最终答案动画 */
.final-answer-icon {
  animation: pulse-glow 2s ease-in-out infinite;
}

/* 完成动画 */
.complete-icon {
  animation: pulse-glow 2s ease-in-out infinite;
}

/* 轨迹内容入场动画 */
.trajectory-content {
  animation: fade-in-up 0.3s ease-out;
}

/* 当前为流式最后一条事件（下一步未执行）时：整卡标题与文字一起律动，提示大模型正在思考/回复 */
.trajectory-content.step-thinking {
  animation: fade-in-up 0.3s ease-out, thinking-pulse 2s ease-in-out infinite;
}

/* 加载状态闪烁效果 */
.loading-shimmer {
  background: linear-gradient(90deg, 
    var(--color-bg-secondary) 0%, 
    var(--color-bg-card) 50%, 
    var(--color-bg-secondary) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
}

/* 事件类型特定的边框颜色 */
.trajectory-content[data-event-type="plan_start"],
.trajectory-content[data-event-type="plan_complete"] {
  border-left: 3px solid var(--el-color-primary);
}

.trajectory-content[data-event-type="step_start"],
.trajectory-content[data-event-type="tool_complete"],
.trajectory-content[data-event-type="skill_complete"] {
  border-left: 3px solid var(--el-color-success);
}

.trajectory-content[data-event-type="delegate_complete"] {
  border-left: 3px solid var(--el-color-primary);
}

.trajectory-content[data-event-type="execute_complete"],
.trajectory-content[data-event-type="reflection_start"] {
  border-left: 3px solid var(--el-color-warning);
}

.trajectory-content[data-event-type="reflection_complete"] {
  border-left: 3px solid var(--el-color-warning);
}

.trajectory-content[data-event-type="final_answer"],
.trajectory-content[data-event-type="complete"] {
  border-left: 3px solid var(--el-color-success);
  background: linear-gradient(135deg, var(--color-bg-card) 0%, var(--el-color-success-light-9) 100%);
}

.trajectory-content[data-event-type="error"],
.trajectory-content[data-event-type="step_error"] {
  border-left: 3px solid var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}

/* 结果块的样式 */
.trajectory-result-block {
  margin-top: 10px;
  padding: 12px 14px;
  background: var(--color-bg-secondary);
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border-light);
}

.trajectory-result-block :deep(p:last-child) { 
  margin-bottom: 0; 
}
.trajectory-result-block :deep(pre) {
  margin: 8px 0;
  padding: 12px;
  background: var(--color-bg-primary);
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border);
}

/* ── Tool Complete 工具调用卡片 ── */
.tool-complete-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.tool-icon {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  border-radius: 6px;
  color: white;
}

.tool-name {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--color-text-primary);
}

.tool-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.tool-step {
  font-size: 0.75rem;
  color: var(--color-text-muted);
  background: var(--color-bg-secondary);
  padding: 2px 8px;
  border-radius: 4px;
}

.tool-time {
  font-size: 0.7rem;
  color: #6366f1;
  background: rgba(99, 102, 241, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: ui-monospace, monospace;
}

/* 数据库结果表格 */
.db-result-block {
  padding: 12px;
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid rgba(229, 231, 235, 0.3);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.db-result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  font-size: 0.75rem;
  color: var(--color-text-muted);
}

.db-result-count {
  background: rgba(16, 185, 129, 0.1);
  color: #059669;
  padding: 2px 10px;
  border-radius: 12px;
  font-weight: 500;
}

.db-table-wrapper {
  overflow-x: auto;
}

.db-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
  background: #ffffff;
}

.db-table th {
  padding: 10px 12px;
  text-align: left;
  background: #f8fafc;
  border-bottom: 2px solid rgba(16, 185, 129, 0.2);
  font-weight: 600;
  color: var(--color-text-primary);
  white-space: nowrap;
}

.db-table td {
  padding: 10px 12px;
  border-bottom: 1px solid #e5e7eb;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-primary);
}

.db-table tr:hover td {
  background: rgba(99, 102, 241, 0.04);
}

/* 错误块样式 */
.error-block {
  font-size: 0.85rem;
  padding: 12px 14px;
  background: rgba(239, 68, 68, 0.08);
  border-radius: 6px;
  color: #dc2626;
  border-left: 3px solid #ef4444;
}

/* ── Final Answer 最终答案卡片 ── */
.final-answer-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.final-answer-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  border-radius: 8px;
  color: white;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.final-answer-title {
  font-size: 1rem;
  font-weight: 700;
  color: var(--color-text-primary);
}

.final-answer-content {
  padding: 16px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.04) 0%, rgba(139, 92, 246, 0.02) 100%);
  border-radius: 10px;
  border: 1px solid rgba(99, 102, 241, 0.15);
  font-size: 0.95rem;
  line-height: 1.7;
}

.empty-content {
  color: var(--color-text-muted);
  font-style: italic;
}

/* ── Complete 执行完成卡片 ── */
.complete-header {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.complete-icon {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  border-radius: 8px;
  color: white;
}

.complete-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--color-text-primary);
}

.complete-iterations {
  font-size: 0.8rem;
  color: var(--color-text-muted);
  background: var(--color-bg-secondary);
  padding: 2px 10px;
  border-radius: 12px;
}

/* ── Reflection 反思卡片 ── */
.reflection-start-header,
.reflection-complete-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.reflection-icon {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
  border-radius: 8px;
  color: white;
}

.reflection-title {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--color-text-primary);
}

.reflection-desc {
  font-size: 0.85rem;
  color: var(--color-text-secondary);
  line-height: 1.5;
}

.reflection-skipped {
  font-size: 0.82rem;
  color: var(--color-text-muted);
  font-style: italic;
}

.reflection-feedback,
.reflection-summary {
  font-size: 0.85rem;
  padding: 10px 14px;
  background: var(--color-bg-secondary);
  border-radius: 6px;
  margin-bottom: 8px;
  line-height: 1.5;
}

.feedback-label,
.summary-label {
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-right: 6px;
}

.reflection-replan {
  font-size: 0.82rem;
  color: #f59e0b;
  padding: 8px 12px;
  background: rgba(245, 158, 11, 0.08);
  border-radius: 6px;
  border-left: 3px solid #f59e0b;
}

/* ── 子 Agent 区块样式：按类型区分颜色，保留现有主题，符合 ui-ux-pro-max ─────────── */

/* 子 Agent 区块标题：使用 --sub-agent-* 变量（由 getSubAgentTheme 注入），fallback 为主色 */
.sub-agent-block-header {
  --sub-agent-accent: var(--el-color-primary);
  --sub-agent-accent-rgb: var(--el-color-primary-rgb, 64, 158, 255);
  --sub-agent-bg-light: var(--el-color-primary-light-9);
  --sub-agent-bg-medium: var(--el-color-primary-light-8);
  --sub-agent-border: var(--el-color-primary-light-5);
  --sub-agent-shadow: 0 2px 8px rgba(var(--el-color-primary-rgb, 64, 158, 255), 0.12);

  background: linear-gradient(135deg, var(--sub-agent-bg-light) 0%, var(--sub-agent-bg-medium) 50%, var(--color-bg-card) 100%);
  border: 2px solid var(--sub-agent-border);
  border-left: 5px solid var(--sub-agent-accent);
  box-shadow: var(--sub-agent-shadow);
  transition: border-color 0.2s ease, background-color 0.2s ease, box-shadow 0.2s ease;
  cursor: pointer;
  margin-bottom: 8px;
}

.sub-agent-block-header:hover {
  box-shadow: var(--sub-agent-shadow), 0 0 0 1px var(--sub-agent-border);
}

.sub-agent-block-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 8px;
}

.sub-agent-block-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--sub-agent-accent);
  line-height: 1;
}

.sub-agent-block-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--sub-agent-accent);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 2px 8px;
  background: var(--sub-agent-bg-light);
  border-radius: 4px;
}

.sub-agent-block-name {
  font-size: 1rem;
  font-weight: 700;
  color: var(--sub-agent-accent);
}

.sub-agent-block-id {
  font-family: ui-monospace, monospace;
  font-size: 0.72rem;
}

.sub-agent-block-task {
  font-size: 0.88rem;
  color: var(--color-text-secondary);
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.6);
  border-radius: 6px;
  border-left: 3px solid var(--sub-agent-border);
  margin-bottom: 8px;
}

.sub-agent-block-hint {
  font-size: 0.78rem;
  color: var(--color-text-muted);
  font-style: italic;
}

/* 子 Agent 内单条事件：左侧色条与 ribbon 使用同主题色，过渡避免布局抖动 */
.sub-agent-inner-content {
  --sub-agent-accent: var(--el-color-primary);
  --sub-agent-accent-rgb: var(--el-color-primary-rgb, 64, 158, 255);
  --sub-agent-bg-light: var(--el-color-primary-light-9);
  --sub-agent-bg-medium: var(--el-color-primary-light-8);
  --sub-agent-border: var(--el-color-primary-light-5);

  border-left: 4px solid var(--sub-agent-border) !important;
  background: var(--sub-agent-bg-light);
  position: relative;
  padding-top: 0;
  transition: border-color 0.2s ease, background-color 0.2s ease;
}

.sub-agent-event-ribbon {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
  padding: 6px 10px;
  background: var(--sub-agent-bg-medium);
  border-radius: 6px;
  border-left: 3px solid var(--sub-agent-accent);
}

.sub-agent-event-agent {
  font-size: 0.8rem;
  font-weight: 700;
  color: var(--sub-agent-accent);
}

.sub-agent-event-phase {
  font-size: 0.78rem;
  color: var(--color-text-secondary);
  font-weight: 500;
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
  
  /* 移动端：进度指示器改为紧凑模式 */
  .trajectory-header {
    flex-direction: column;
    gap: 12px;
    align-items: flex-start;
  }
  
  .trajectory-progress {
    width: 100%;
    justify-content: space-between;
  }
  
  .trajectory-progress-step span:not(.step-icon) {
    display: none;
  }
  
  .trajectory-progress-step {
    padding: 6px;
  }
  
  .trajectory-progress-divider {
    flex: 1;
  }
}
</style>
