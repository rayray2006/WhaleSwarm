<template>
  <div class="report-view">
    <div class="warning-stripes"></div>

    <div class="toolbar">
      <div class="toolbar-left">
        <button class="btn" @click="$router.back()">&#8592; BACK</button>
        <h2 class="page-title">Analysis Report</h2>
        <span class="tag" :class="'status-' + status">{{ status }}</span>
        <span v-if="counterfactualMode" class="tag tag-cf">COUNTERFACTUAL</span>
      </div>
      <div class="toolbar-right">
        <template v-if="counterfactualMode">
          <button
            class="btn btn-sm"
            :class="{ 'btn-active': activeUniverse === 'baseline' }"
            @click="activeUniverse = 'baseline'"
          >Baseline</button>
          <button
            class="btn btn-sm"
            :class="{ 'btn-active': activeUniverse === 'counterfactual' }"
            @click="activeUniverse = 'counterfactual'"
          >Counterfactual</button>
        </template>
        <button
          v-if="status === 'completed'"
          class="btn btn-primary"
          @click="$router.push(`/interaction/${reportId}`)"
        >INTERVIEW AGENTS</button>
        <button
          v-if="!reportGenerated && status !== 'processing'"
          class="btn btn-primary"
          :disabled="generating"
          @click="startGeneration"
        >{{ generating ? 'GENERATING...' : 'GENERATE REPORT' }}</button>
      </div>
    </div>

    <!-- Counterfactual comparison chart -->
    <div v-if="counterfactualMode && baselinePriceHistory.length > 0" class="cf-comparison">
      <div class="cf-comparison-header">
        <span class="cf-comparison-title">Price Comparison: Baseline vs Counterfactual</span>
        <span v-if="fictionalEvent" class="cf-event-badge">Event at R{{ eventRound }}: {{ truncate(fictionalEvent, 80) }}</span>
      </div>
      <div class="cf-chart-container" ref="cfChartContainer">
        <svg ref="cfChart"></svg>
      </div>
    </div>

    <!-- Progress bar -->
    <div v-if="status === 'processing'" class="progress-section">
      <div class="progress-bar">
        <div class="progress-fill" :style="{ width: progress + '%' }"></div>
      </div>
      <span class="progress-text">Generating report... {{ progress }}%</span>
    </div>

    <!-- Error -->
    <div v-if="error" class="error-banner">
      <span>{{ error }}</span>
      <button class="btn" @click="error = null">DISMISS</button>
    </div>

    <!-- Report content -->
    <div v-if="reportGenerated" class="report-content">
      <div class="report-body" v-html="renderedMarkdown"></div>
    </div>

    <!-- Empty state -->
    <div v-if="!reportGenerated && status !== 'processing'" class="empty-state">
      <div class="empty-icon">&#9998;</div>
      <p>No report generated yet.</p>
      <p class="muted">Click "Generate Report" to create an analytical report from the simulation.</p>
    </div>
  </div>
</template>

<script>
import * as d3 from 'd3'
import { marked } from 'marked'
import { generateReport, getReportStatus, getReport } from '../api/report'
import { getRunStatus, getConfig } from '../api/simulation'

export default {
  name: 'ReportView',
  data() {
    return {
      status: 'idle',
      progress: 0,
      markdown: '',
      error: null,
      generating: false,
      taskId: null,
      pollTimer: null,
      // Counterfactual
      counterfactualMode: false,
      activeUniverse: 'baseline',
      fictionalEvent: '',
      eventRound: 0,
      totalRounds: 10,
      baselinePriceHistory: [],
      cfPriceHistory: [],
    }
  },
  computed: {
    reportId() {
      return this.$route.params.reportId
    },
    reportGenerated() {
      return this.markdown.length > 0
    },
    renderedMarkdown() {
      return marked(this.markdown)
    },
  },
  async mounted() {
    await this.checkExisting()
    await this.loadCounterfactualData()
  },
  beforeUnmount() {
    if (this.pollTimer) clearInterval(this.pollTimer)
  },
  methods: {
    truncate(text, max) {
      if (!text) return ''
      return text.length > max ? text.substring(0, max) + '...' : text
    },
    async loadCounterfactualData() {
      try {
        const cfgRes = await getConfig(this.reportId)
        if (cfgRes.data?.counterfactual_mode) {
          this.counterfactualMode = true
          this.fictionalEvent = cfgRes.data.fictional_event || ''
          this.eventRound = cfgRes.data.event_round || 0
          this.totalRounds = cfgRes.data.max_rounds || 10

          // Fetch final run status to get price histories
          const statusRes = await getRunStatus(this.reportId)
          const data = statusRes.data
          if (data.polymarket?.price_history) {
            this.baselinePriceHistory = data.polymarket.price_history
          }
          if (data.cf_polymarket?.price_history) {
            this.cfPriceHistory = data.cf_polymarket.price_history
          }
          this.$nextTick(() => this.renderCfChart())
        }
      } catch {
        // Non-CF simulation or data not available
      }
    },
    renderCfChart() {
      const container = this.$refs.cfChartContainer
      const svgEl = this.$refs.cfChart
      if (!container || !svgEl) return

      const width = container.clientWidth || 600
      const height = 200
      const margin = { top: 12, right: 16, bottom: 28, left: 40 }
      const innerW = width - margin.left - margin.right
      const innerH = height - margin.top - margin.bottom
      if (innerW <= 0 || innerH <= 0) return

      const svg = d3.select(svgEl)
      svg.attr('viewBox', `0 0 ${width} ${height}`)
        .attr('preserveAspectRatio', 'xMidYMid meet')
      svg.selectAll('*').remove()

      const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)

      const allPoints = [...this.baselinePriceHistory, ...this.cfPriceHistory]
      if (allPoints.length === 0) return

      const xDomain = [0, Math.max(this.totalRounds, d3.max(allPoints, d => d.round) || 1)]
      const x = d3.scaleLinear().domain(xDomain).range([0, innerW])
      const y = d3.scaleLinear().domain([0, 1]).range([innerH, 0])

      // Grid
      g.selectAll('.grid-line')
        .data([0.25, 0.5, 0.75])
        .enter().append('line')
        .attr('x1', 0).attr('x2', innerW)
        .attr('y1', d => y(d)).attr('y2', d => y(d))
        .attr('stroke', '#333').attr('stroke-dasharray', '2,4')

      // Axes
      g.append('g')
        .attr('transform', `translate(0,${innerH})`)
        .call(d3.axisBottom(x).ticks(Math.min(10, this.totalRounds)).tickFormat(d => `R${d}`))
        .selectAll('text').attr('fill', '#666').style('font-size', '10px')
      g.selectAll('.domain, .tick line').attr('stroke', '#333')
      g.append('g')
        .call(d3.axisLeft(y).ticks(5).tickFormat(d3.format('.2f')))
        .selectAll('text').attr('fill', '#666').style('font-size', '10px')

      const line = d3.line()
        .x(d => x(d.round))
        .y(d => y(d.price))
        .curve(d3.curveMonotoneX)

      // Event marker
      if (this.eventRound > 0) {
        const ex = x(this.eventRound)
        g.append('line')
          .attr('x1', ex).attr('x2', ex)
          .attr('y1', 0).attr('y2', innerH)
          .attr('stroke', '#FFD700').attr('stroke-width', 1.5)
          .attr('stroke-dasharray', '4,4').attr('opacity', 0.7)
        g.append('text')
          .attr('x', ex + 4).attr('y', 10)
          .attr('fill', '#FFD700').style('font-size', '9px').style('font-weight', '700')
          .text('EVENT')
      }

      // Baseline (orange)
      if (this.baselinePriceHistory.length > 0) {
        g.append('path').datum(this.baselinePriceHistory)
          .attr('d', line).attr('fill', 'none')
          .attr('stroke', '#FF6B1A').attr('stroke-width', 2)
      }

      // Counterfactual (cyan dashed)
      if (this.cfPriceHistory.length > 0) {
        g.append('path').datum(this.cfPriceHistory)
          .attr('d', line).attr('fill', 'none')
          .attr('stroke', '#00D4FF').attr('stroke-width', 2)
          .attr('stroke-dasharray', '6,3')
      }

      // Legend
      const legend = g.append('g').attr('transform', `translate(${innerW - 160}, 4)`)
      legend.append('line').attr('x1', 0).attr('x2', 16).attr('y1', 6).attr('y2', 6)
        .attr('stroke', '#FF6B1A').attr('stroke-width', 2)
      legend.append('text').attr('x', 20).attr('y', 10)
        .attr('fill', '#888').style('font-size', '10px').text('Baseline')
      legend.append('line').attr('x1', 0).attr('x2', 16).attr('y1', 22).attr('y2', 22)
        .attr('stroke', '#00D4FF').attr('stroke-width', 2).attr('stroke-dasharray', '6,3')
      legend.append('text').attr('x', 20).attr('y', 26)
        .attr('fill', '#888').style('font-size', '10px').text('Counterfactual')
    },
    async checkExisting() {
      try {
        const res = await getReport(this.reportId)
        if (res.data?.markdown) {
          this.markdown = res.data.markdown
          this.status = 'completed'
        }
      } catch {
        // No existing report
      }
    },
    async startGeneration() {
      this.generating = true
      this.error = null
      this.status = 'processing'
      this.progress = 0

      try {
        const res = await generateReport({
          simulation_id: this.reportId,
          universe: this.counterfactualMode ? this.activeUniverse : undefined,
        })
        this.taskId = res.data.task_id
        this.startPolling()
      } catch (e) {
        this.error = e.response?.data?.error || e.message
        this.status = 'failed'
        this.generating = false
      }
    },
    startPolling() {
      this.pollTimer = setInterval(async () => {
        try {
          const res = await getReportStatus(this.reportId)
          this.progress = res.data.progress || 0
          this.status = res.data.status

          if (res.data.status === 'completed') {
            clearInterval(this.pollTimer)
            this.generating = false
            await this.checkExisting()
          } else if (res.data.status === 'failed') {
            clearInterval(this.pollTimer)
            this.generating = false
            this.error = res.data.error || 'Report generation failed.'
          }
        } catch (e) {
          console.error('Poll error:', e)
        }
      }, 3000)
    },
  },
}
</script>

<style scoped>
.report-view { min-height: 100vh; display: flex; flex-direction: column; }
.toolbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border);
}
.toolbar-left { display: flex; align-items: center; gap: var(--space-2); }
.toolbar-right { display: flex; gap: var(--space-2); }
.page-title { font-family: var(--font-display); color: var(--primary); font-size: 18px; }

.progress-section { padding: var(--space-2) var(--space-3); }
.progress-bar {
  height: 6px; background: var(--surface-raised); border-radius: 3px; overflow: hidden;
}
.progress-fill { height: 100%; background: var(--primary); transition: width 0.3s; }
.progress-text { font-size: 12px; color: var(--muted); margin-top: var(--space-1); display: block; }

.error-banner {
  display: flex; justify-content: space-between; align-items: center;
  padding: var(--space-2) var(--space-3); background: rgba(229, 62, 62, 0.1);
  border-bottom: 1px solid var(--danger); color: var(--danger); font-size: 13px;
}

.report-content {
  flex: 1; padding: var(--space-4); max-width: 900px; margin: 0 auto; width: 100%;
}

.report-body { color: var(--text); line-height: 1.7; font-size: 14px; }
.report-body :deep(h1) { font-family: var(--font-display); color: var(--primary); font-size: 28px; margin: var(--space-4) 0 var(--space-2); }
.report-body :deep(h2) { font-family: var(--font-display); color: var(--primary); font-size: 22px; margin: var(--space-4) 0 var(--space-2); border-bottom: 1px solid var(--border); padding-bottom: var(--space-1); }
.report-body :deep(h3) { font-family: var(--font-display); color: var(--text); font-size: 18px; margin: var(--space-3) 0 var(--space-1); }
.report-body :deep(p) { margin-bottom: var(--space-2); }
.report-body :deep(blockquote) { border-left: 3px solid var(--primary); padding-left: var(--space-2); color: var(--text-secondary); margin: var(--space-2) 0; }
.report-body :deep(code) { background: var(--surface-raised); padding: 2px 6px; border-radius: 3px; font-size: 13px; }
.report-body :deep(pre) { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: var(--space-2); overflow-x: auto; }
.report-body :deep(ul), .report-body :deep(ol) { padding-left: var(--space-3); margin-bottom: var(--space-2); }
.report-body :deep(table) { width: 100%; border-collapse: collapse; margin: var(--space-2) 0; }
.report-body :deep(th), .report-body :deep(td) { border: 1px solid var(--border); padding: var(--space-1) var(--space-2); text-align: left; font-size: 13px; }
.report-body :deep(th) { background: var(--surface-raised); color: var(--primary); }

.empty-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-2); }
.empty-icon { font-size: 48px; color: var(--muted); }
.muted { color: var(--muted); font-size: 13px; }

.status-completed { background: var(--accent); color: var(--background); }
.status-processing { background: var(--primary); color: var(--background); animation: pulse-border 2s infinite; }
.status-failed { background: var(--danger); color: white; }

.tag-cf {
  background: rgba(0, 212, 255, 0.12);
  color: #00D4FF;
  border-color: rgba(0, 212, 255, 0.3);
}
.btn-sm {
  padding: 2px 10px;
  font-size: 11px;
  min-height: auto;
}
.btn-active {
  background: var(--primary);
  border-color: var(--primary);
  color: var(--background);
}

.cf-comparison {
  border-bottom: 1px solid var(--border);
  padding: var(--space-2) var(--space-3);
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
}
.cf-comparison-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-1);
}
.cf-comparison-title {
  font-family: var(--font-display);
  font-size: 14px;
  color: var(--primary);
}
.cf-event-badge {
  font-size: 10px;
  color: #FFD700;
  background: rgba(255, 215, 0, 0.08);
  padding: 2px 8px;
  border-radius: 3px;
  max-width: 400px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cf-chart-container {
  height: 200px;
}
.cf-chart-container svg {
  width: 100%;
  height: 100%;
  display: block;
}
</style>
