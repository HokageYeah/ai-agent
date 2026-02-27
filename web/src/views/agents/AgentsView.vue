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
              {{ executing ? (isStreaming ? 'Agent 正在流式执行中...' : 'Agent 执行中...') : '开始执行任务' }}
            </el-button>
            
            <!-- 流式执行状态指示 -->
            <div v-if="isStreaming" class="stream-status">
              <el-icon class="stream-status-icon"><Loading /></el-icon>
              <span class="stream-status-text">{{ getStreamStatusText() }}</span>
              <span v-if="!streamEvents.length" class="stream-status-hint">等待连接...</span>
              <span v-else class="stream-events-count">{{ streamEvents.length }} 个事件</span>
            </div>
          </div>

          <!-- 执行轨迹 (详情) -->
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
            
            <!-- 流式事件列表 -->
            <div v-if="streamEvents.length > 0" class="stream-events-container" ref="streamEventsContainer">
              <el-timeline style="margin-top: 20px;">
                <!-- 遍历流式事件 -->
                <el-timeline-item
                  v-for="(event, index) in streamEvents"
                  :key="'stream-'+index"
                  :type="getEventTimelineType(event.event)"
                  :hollow="!isImportantEvent(event.event)"
                  :size="getEventTimelineSize(event.event)"
                >
                  <div :data-event-type="event.event" class="trajectory-content" style="margin-top: 0;">
                    <!-- ① 规划开始 -->
                    <template v-if="event.event === 'plan_start'">
                      <div style="margin-bottom: 8px; font-weight: 600;">
                        <el-tag size="small" type="primary">🧠 开始规划</el-tag>
                        <span style="font-size: 0.8rem; color: var(--color-text-muted); margin-left: 8px;">
                          迭代 {{ event.iteration + 1 }}
                        </span>
                      </div>
                      <div style="font-size: 0.85rem; color: var(--color-text-secondary);">
                        {{ event.data?.message || 'Agent 正在分析任务并制定执行计划...' }}
                      </div>
                    </template>
                    
                    <!-- ② 规划完成（含推理和步骤列表） -->
                    <template v-else-if="event.event === 'plan_complete'">
                      <div style="margin-bottom: 8px; font-weight: 600;">
                        <el-tag size="small" type="success">✅ 规划完成</el-tag>
                        <span style="font-size: 0.8rem; color: var(--color-text-muted); margin-left: 8px;">
                          共 {{ event.data?.steps?.length || 0 }} 个步骤
                        </span>
                      </div>
                      <!-- 推理过程 -->
                      <div v-if="event.data?.reasoning" style="font-size: 0.85rem; background: var(--color-bg-secondary); padding: 8px 12px; border-radius: 6px; margin-bottom: 8px; border-left: 3px solid var(--el-color-primary-light-5);">
                        <div style="font-weight: 600; margin-bottom: 4px; color: var(--color-text-secondary);">推理过程：</div>
                        {{ event.data.reasoning }}
                      </div>
                      <!-- 步骤列表 -->
                      <div v-if="event.data?.steps?.length" style="margin-top: 8px;">
                        <div style="font-size: 0.78rem; font-weight: 600; color: var(--color-text-muted); margin-bottom: 6px;">执行计划：</div>
                        <div v-for="(step, sIdx) in event.data.steps" :key="sIdx" style="display: flex; align-items: flex-start; gap: 8px; margin-bottom: 10px; font-size: 0.82rem;">
                          <span style="color: var(--color-text-muted); flex-shrink: 0;">{{ sIdx + 1 }}.</span>
                          <el-tag v-if="step.action === 'tool'" size="small" type="success" effect="plain">工具: {{ step.tool_name }}</el-tag>
                          <el-tag v-else-if="step.action === 'skill'" size="small" type="warning" effect="plain">技能: {{ step.skill_id }}</el-tag>
                          <el-tag v-else-if="step.action === 'delegate'" size="small" type="primary" effect="plain">委派: {{ step.agent_id }}</el-tag>
                          <el-tag v-else-if="step.action === 'final_answer'" size="small" type="info" effect="plain">合成最终答案</el-tag>
                          <el-tag v-else size="small" effect="plain">{{ step.action }}</el-tag>
                        </div>
                      </div>
                    </template>
                    
                    <!-- ③ 执行阶段开始 -->
                    <template v-else-if="event.event === 'step_start'">
                      <div style="margin-bottom: 10px; font-weight: 600; display: flex; align-items: center; gap: 12px;">
                        <el-tag size="small" type="info" effect="dark">
                          <el-icon><Promotion /></el-icon> 开始执行
                        </el-tag>
                        <span style="font-size: 0.85rem; color: var(--color-text-secondary);">
                          共 <strong style="color: var(--color-primary);">{{ event.step_total || 0 }}</strong> 个步骤
                        </span>
                      </div>
                      <div style="font-size: 0.82rem; color: var(--color-text-muted); padding: 8px 12px; background: var(--color-bg-secondary); border-radius: 6px;">
                        {{ event.data?.message || '正在按计划逐步执行每个步骤...' }}
                      </div>
                    </template>
                    
                    <!-- ④ 工具调用完成 -->
                    <template v-else-if="event.event === 'tool_complete'">
                      <!-- 头部 -->
                      <div style="margin-bottom: 10px; font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <el-tag size="small" type="success" effect="plain">
                          <el-icon><Promotion /></el-icon> {{ event.data?.tool_name }}
                        </el-tag>
                        <span style="font-size: 0.75rem; color: var(--color-text-muted);">
                          步骤 {{ event.step_index }}/{{ event.step_total }}
                        </span>
                        <span v-if="event.data?.execution_time_ms" style="font-size: 0.7rem; color: var(--color-text-muted);">
                          {{ event.data.execution_time_ms.toFixed(2) }}ms
                        </span>
                        <el-tag v-if="event.data?.success === false" size="small" type="danger">失败</el-tag>
                      </div>
                      
                      <!-- 数据库 -->
                      <div v-if="event.data?.result?.columns && event.data?.result?.rows" style="padding: 10px; background: var(--color-bg-secondary); border-radius: 6px; border: 1px solid var(--color-border-light);">
                        <div style="font-size: 0.75rem; color: var(--color-text-muted); margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
                          <span>查询结果</span>
                          <span style="background: var(--el-color-success-light-9); padding: 2px 8px; border-radius: 10px; font-size: 0.7rem;">
                            {{ event.data.result.row_count }} 条记录
                          </span>
                        </div>
                        <div style="overflow-x: auto;">
                          <table style="width: 100%; border-collapse: collapse; font-size: 0.8rem;">
                            <thead>
                              <tr>
                                <th v-for="col in event.data.result.columns" :key="col" style="padding: 6px 8px; text-align: left; background: var(--color-bg-primary); border: 1px solid var(--color-border-light); font-weight: 600; white-space: nowrap;">
                                  {{ col }}
                                </th>
                              </tr>
                            </thead>
                            <tbody>
                              <tr v-for="(row, rIdx) in event.data.result.rows" :key="rIdx">
                                <td v-for="col in event.data.result.columns" :key="col" style="padding: 6px 8px; border: 1px solid var(--color-border-light); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                                  {{ row[col] }}
                                </td>
                              </tr>
                            </tbody>
                          </table>
                        </div>
                      </div>
                      
                      <!-- 普通文本/JSON 结果 -->
                      <div v-else-if="event.data?.error" style="font-size: 0.85rem; padding: 10px; background: var(--el-color-danger-light-9); border-radius: 6px; color: var(--el-color-danger);">
                        <strong>错误：</strong>{{ event.data.error }}
                      </div>
                      <div v-else-if="event.data?.result" style="font-size: 0.85rem;" class="trajectory-result-block">
                        <MarkdownRenderer v-if="typeof event.data.result === 'string'" :content="event.data.result" />
                        <MarkdownRenderer v-else :content="'```json\n' + JSON.stringify(event.data.result, null, 2) + '\n```'" />
                      </div>
                    </template>
                    
                    <!-- ⑤ 技能调用完成 -->
                    <template v-else-if="event.event === 'skill_complete'">
                      <div style="margin-bottom: 8px; font-weight: 600;">
                        <el-tag size="small" type="warning">✨ 调用技能</el-tag>
                        <span style="font-size: 0.8rem; color: var(--color-text-muted); margin-left: 8px;">
                          {{ event.data?.skill_id }}
                        </span>
                        <el-tag v-if="event.data?.success === false" size="small" type="danger" style="margin-left: 8px;">失败</el-tag>
                        <span style="font-size: 0.75rem; color: var(--color-text-muted); margin-left: 8px;">
                          步骤 {{ event.step_index }}/{{ event.step_total }}
                        </span>
                      </div>
                      <div style="font-size: 0.85rem;" class="trajectory-result-block">
                        <div v-if="event.data?.error" style="color: var(--el-color-danger); padding: 6px; background: var(--el-color-danger-light-9); border-radius: 4px;">
                          {{ event.data.error }}
                        </div>
                        <MarkdownRenderer v-else-if="typeof event.data?.result === 'string'" :content="event.data.result" />
                        <MarkdownRenderer v-else-if="event.data?.result" :content="'```json\n' + JSON.stringify(event.data.result, null, 2) + '\n```'" />
                      </div>
                    </template>
                    
                    <!-- ⑥ 委派子Agent完成 -->
                    <template v-else-if="event.event === 'delegate_complete'">
                      <!-- 头部信息 -->
                      <div style="margin-bottom: 10px; font-weight: 600; display: flex; align-items: center; flex-wrap: wrap; gap: 8px;">
                        <el-tag size="small" type="primary" effect="plain">
                          <el-icon><User /></el-icon> 委派子Agent
                        </el-tag>
                        <span style="font-size: 0.85rem; color: var(--color-primary); font-weight: 600;">
                          {{ event.data?.result?.agent_name || event.data?.agent_id }}
                        </span>
                        <el-tag v-if="event.data?.success === false" size="small" type="danger">执行失败</el-tag>
                        <span v-if="event.step_index" style="font-size: 0.75rem; color: var(--color-text-muted);">
                          步骤 {{ event.step_index }}/{{ event.step_total }}
                        </span>
                      </div>
                      
                      <!-- 子 Agent 内部执行步骤 -->
                      <div v-if="event.data?.result?.step_results?.length" style="margin-top: 12px;">
                        <div style="font-size: 0.75rem; font-weight: 600; color: var(--color-text-muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.05em;">
                          子Agent 执行轨迹
                        </div>
                        <div v-for="(subStep, sIdx) in event.data.result.step_results" :key="sIdx" style="margin-bottom: 12px; font-size: 0.82rem;">
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
                      <div v-else-if="event.data?.result?.result" style="margin-top: 10px; padding: 12px; background: var(--color-bg-secondary); border-radius: 6px; border-left: 3px solid var(--el-color-primary-light-5);">
                        <div style="font-size: 0.75rem; font-weight: 600; color: var(--color-text-muted); margin-bottom: 8px;">
                          执行结果
                        </div>
                        <MarkdownRenderer v-if="typeof event.data.result.result === 'string'" :content="event.data.result.result" />
                        <MarkdownRenderer v-else :content="'```json\n' + JSON.stringify(event.data.result.result, null, 2) + '\n```'" />
                      </div>
                    </template>
                    
                    <!-- ⑥.5 步骤完成（final_answer 合成步骤） -->
                    <template v-else-if="event.event === 'step_complete'">
                      <div style="margin-bottom: 10px; font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <el-tag size="small" type="info" effect="plain" style="display: inline-flex; align-items: center; gap: 4px;">
                          <el-icon style="vertical-align: middle;"><ChatDotRound /></el-icon>{{ event.data?.step_name || '步骤完成' }}
                        </el-tag>
                        <span style="font-size: 0.75rem; color: var(--color-text-muted);">
                          步骤 {{ (event.step_index || 0) }}/{{ event.step_total }}
                        </span>
                        <el-tag v-if="event.data?.success === false" size="small" type="danger">失败</el-tag>
                      </div>
                      <div v-if="event.data?.message" style="font-size: 0.82rem; color: var(--color-text-muted); padding: 8px; background: var(--color-bg-secondary); border-radius: 6px;">
                        {{ event.data.message }}
                      </div>
                    </template>
                    
                    <!-- ⑦ 执行阶段完成（进入反思前） -->
                    <template v-else-if="event.event === 'execute_complete'">
                      <div style="margin-bottom: 10px; font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <el-tag size="small" type="info" effect="dark">
                          <el-icon style="vertical-align: middle;"><Finished /></el-icon>执行阶段完成
                        </el-tag>
                        <el-tag v-if="event.data?.success" size="small" type="success">成功</el-tag>
                        <el-tag v-else size="small" type="warning">部分失败</el-tag>
                        <span style="font-size: 0.75rem; color: var(--color-text-muted);">
                          步骤 {{ (event.step_index || 0) }}/{{ event.step_total }}
                        </span>
                      </div>
                      
                      <!-- 步骤摘要列表 -->
                      <div v-if="event.data?.step_summary?.length" style="margin-top: 12px;">
                        <div style="font-size: 0.75rem; font-weight: 600; color: var(--color-text-muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.05em;">
                          执行步骤摘要
                        </div>
                        <div style="background: var(--color-bg-secondary); border-radius: 6px; padding: 10px 12px; border: 1px solid var(--color-border-light);">
                          <div v-for="(step, idx) in event.data.step_summary" :key="idx" style="font-size: 0.82rem; color: var(--color-text-secondary); padding: 4px 0; display: flex; align-items: center; gap: 8px;">
                            <el-icon style="color: var(--el-color-success);"><Check /></el-icon>
                            {{ step }}
                          </div>
                        </div>
                      </div>
                      
                      <div style="font-size: 0.82rem; color: var(--color-text-muted); margin-top: 10px; padding: 8px 12px; background: var(--color-bg-secondary); border-radius: 6px;">
                        {{ event.data?.message || '正在进入反思阶段...' }}
                      </div>
                    </template>
                    
                    <!-- ⑧ 反思开始 -->
                    <template v-else-if="event.event === 'reflection_start'">
                      <div style="margin-bottom: 6px; font-weight: 600;">
                        <el-tag size="small" type="warning">🔍 开始自我反思</el-tag>
                        <span style="font-size: 0.8rem; color: var(--color-text-muted); margin-left: 8px;">
                          迭代 {{ event.iteration + 1 }}
                        </span>
                      </div>
                      <div style="font-size: 0.85rem; color: var(--color-text-secondary);">
                        {{ event.data?.message || 'Agent 正在评估执行结果并进行自我反思...' }}
                      </div>
                    </template>
                    
                    <!-- ⑨ 反思完成 -->
                    <template v-else-if="event.event === 'reflection_complete'">
                      <div style="margin-bottom: 8px; font-weight: 600;">
                        <el-tag size="small" type="warning">💭 自我反思</el-tag>
                        <el-tag v-if="event.data?.success" size="small" type="success" style="margin-left: 8px;">✅ 任务达标</el-tag>
                        <el-tag v-else-if="event.data?.skipped" size="small" type="info" style="margin-left: 8px;">跳过</el-tag>
                        <el-tag v-else size="small" type="warning" style="margin-left: 8px;">⚠️ 需改进</el-tag>
                      </div>
                      <div v-if="event.data?.skipped" style="font-size: 0.82rem; color: var(--color-text-muted);">
                        {{ event.data.message || '无执行结果可供反思，已跳过' }}
                      </div>
                      <template v-else>
                        <div v-if="event.data?.feedback" style="font-size: 0.85rem; margin-bottom: 6px; padding: 6px 10px; background: var(--color-bg-secondary); border-radius: 4px;">
                          <strong>改进建议：</strong>{{ event.data.feedback }}
                        </div>
                        <div v-if="event.data?.summary" style="font-size: 0.85rem; color: var(--color-text-secondary);">
                          <strong>总结：</strong>{{ event.data.summary }}
                        </div>
                        <div v-if="event.data?.needs_replanning" style="font-size: 0.82rem; color: var(--el-color-warning); margin-top: 6px;">
                          🔄 Agent 将重新规划并再次执行
                        </div>
                      </template>
                    </template>
                    
                    <!-- ⑩ 最终答案 -->
                    <template v-else-if="event.event === 'final_answer'">
                      <div style="margin-bottom: 8px; font-weight: 600;">
                        <el-tag size="small" type="success" effect="dark">🎯 最终答案</el-tag>
                      </div>
                      <div style="font-size: 0.95rem;" class="trajectory-result-block">
                        <MarkdownRenderer v-if="typeof event.data?.result === 'string'" :content="event.data.result" />
                        <MarkdownRenderer v-else-if="event.data?.result" :content="'```json\n' + JSON.stringify(event.data.result, null, 2) + '\n```'" />
                        <div v-else style="color: var(--color-text-muted); font-style: italic;">暂无内容</div>
                      </div>
                    </template>
                    
                    <!-- ⑪ 执行完成 -->
                    <template v-else-if="event.event === 'complete'">
                      <div style="margin-bottom: 8px; font-weight: 600;">
                        <el-tag size="small" type="success" effect="dark">✅ 执行完成</el-tag>
                        <span style="font-size: 0.8rem; color: var(--color-text-muted); margin-left: 8px;">
                          共迭代 {{ event.data?.iterations || 0 }} 次
                        </span>
                        <el-tag v-if="event.data?.success === false" size="small" type="danger" style="margin-left: 8px;">执行失败</el-tag>
                      </div>
                    </template>
                    
                    <!-- ⑫ 步骤错误 -->
                    <template v-else-if="event.event === 'step_error'">
                      <div style="margin-bottom: 8px; font-weight: 600;">
                        <el-tag size="small" type="danger">⚠️ 步骤执行失败</el-tag>
                        <span style="font-size: 0.75rem; color: var(--color-text-muted); margin-left: 8px;">
                          步骤 {{ event.step_index }}/{{ event.step_total }}
                        </span>
                      </div>
                      <div style="font-size: 0.85rem; color: var(--el-color-danger); padding: 8px; background: var(--el-color-danger-light-9); border-radius: 4px;">
                        {{ event.error || event.data?.error || '未知错误' }}
                      </div>
                    </template>
                    
                    <!-- ⑬ 全局错误 -->
                    <template v-else-if="event.event === 'error'">
                      <div style="margin-bottom: 8px; font-weight: 600;">
                        <el-tag size="small" type="danger">❌ 执行错误</el-tag>
                      </div>
                      <div style="font-size: 0.85rem; color: var(--el-color-danger); padding: 8px; background: var(--el-color-danger-light-9); border-radius: 4px;">
                        {{ event.error || '未知错误' }}
                      </div>
                    </template>
                    
                    <!-- ⑭ 其他未知事件（兜底展示） -->
                    <template v-else>
                      <div style="font-size: 0.8rem; color: var(--color-text-muted);">
                        <el-tag size="small" type="info">{{ event.event }}</el-tag>
                        <span style="margin-left: 8px;">{{ event.data?.message || '' }}</span>
                      </div>
                    </template>
                  </div>
                </el-timeline-item>
              </el-timeline>
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
                <div :data-event-type="event.event" class="trajectory-content" style="margin-top: 0;">
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
                  <div :data-event-type="event.event" class="trajectory-content" style="margin-top: 0;">
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
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, nextTick } from 'vue'
import { Setting, Refresh, CaretRight, DataLine, WarningFilled, User, Loading,Aim, Check, Promotion, Cpu, MagicStick, ChatDotRound, Finished
, Sunrise, UserFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getAgentList, executeAgent, executeAgentStream } from '@/api/modules/agents'
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

const agents = ref<AgentInfo[]>([])
const selectedAgent = ref<AgentInfo | null>(null)
const loadingAgents = ref<boolean>(false)
const taskInput = ref<string>('')
const executing = ref<boolean>(false)
const executeResult = ref<AgentExecuteResponse | null>(null)
const executeError = ref<string>('')

// 流式执行相关状态
const streamEvents = ref<StreamEvent[]>([])  // 流式事件列表
const isStreaming = ref<boolean>(false)      // 是否正在流式接收
const currentStreamEvent = ref<StreamEvent | null>(null)  // 当前正在处理的事件

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

// 滚动到最新事件（流式接收时自动触发）
const streamEventsContainer = ref<HTMLElement | null>(null)
function scrollToLatestEvent() {
  nextTick(() => {
    if (streamEventsContainer.value) {
      streamEventsContainer.value.scrollTop = streamEventsContainer.value.scrollHeight
    }
  })
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
  
  // 保存事件到列表（驱动时间轴渲染）
  streamEvents.value.push(event)
  currentStreamEvent.value = event
  
  // 自动滚动到最新事件
  scrollToLatestEvent()
  
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

  try {
    console.log('[AgentView] 开始流式执行 Agent:', selectedAgent.value.agent_id)
    
    // 使用流式 API
    executeAgentStream(
      selectedAgent.value.agent_id,
      {
        task: taskInput.value,
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
      return 'primary'
    case 'reflection_start':
    case 'reflection_complete':
      return 'warning'
    case 'final_answer':
    case 'complete':
      return 'success'
    case 'step_error':
    case 'error':
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
    'step_complete',
    'tool_complete',
    'skill_complete',
    'delegate_complete',
    'reflection_complete',
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
    case 'step_complete':
    case 'tool_complete':
    case 'skill_complete':
    case 'delegate_complete':
    case 'reflection_complete':
    case 'final_answer':
    case 'complete':
      return 'large'
    case 'step_start':
    case 'execute_complete':
    case 'reflection_start':
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

/* =====================================================
 * 轨迹展示区 - Agent 执行流程可视化
 * 设计风格：Bento Grid + Glassmorphism + 阶段式进度
 * ===================================================== */

/* 整体容器 */
.trajectory-section {
  margin-top: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
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
 * 改进：使用 Bento Grid 风格的事件卡片
 * ===================================================== */
.stream-events-container {
  max-height: 550px;
  overflow-y: auto;
  padding-right: 8px;
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
  padding: 16px 18px;
  font-size: 0.85rem;
  max-width: 100%;
  overflow-x: auto;
  line-height: 1.6;
  background: var(--color-bg-card);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light);
  transition: all var(--transition-normal);
}

.trajectory-content:hover {
  border-color: var(--color-primary-light);
  box-shadow: var(--shadow-sm);
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
