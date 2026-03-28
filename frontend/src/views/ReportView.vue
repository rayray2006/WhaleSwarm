<template>
  <div class="report-view">
    <div class="warning-stripes"></div>

    <div class="toolbar">
      <div class="toolbar-left">
        <button class="btn" @click="$router.back()">&#8592; BACK</button>
        <h2 class="page-title">Analysis Report</h2>
        <span class="tag" :class="'status-' + status">{{ status }}</span>
      </div>
      <div class="toolbar-right">
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
import { marked } from 'marked'
import { generateReport, getReportStatus, getReport } from '../api/report'

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
  },
  beforeUnmount() {
    if (this.pollTimer) clearInterval(this.pollTimer)
  },
  methods: {
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
        const res = await generateReport({ simulation_id: this.reportId })
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
</style>
