<template>
  <div class="main-view">
    <div class="warning-stripes"></div>

    <div class="toolbar">
      <div class="toolbar-left">
        <h2 class="page-title">{{ project?.name || 'Loading...' }}</h2>
        <span class="tag">{{ project?.status }}</span>
      </div>
      <div class="toolbar-right"></div>
    </div>

    <!-- Preparing overlay -->
    <div v-if="preparing" class="preparing-banner">
      <div class="preparing-inner">
        <div class="spinner"></div>
        <span>Generating agent profiles... This may take a minute.</span>
      </div>
      <div class="prepare-bar">
        <div class="prepare-bar-fill" :style="{ width: prepareProgress + '%' }"></div>
      </div>
    </div>

    <div class="layout" :class="mode">
      <div class="graph-pane" v-show="mode !== 'workbench'">
        <GraphPanel :graphData="graphData" />
      </div>
      <div class="work-pane" v-show="mode !== 'graph'">
        <Step1GraphBuild
          v-if="step === 1"
          :ontology="project?.ontology"
          :building="building"
          :progress="buildProgress"
          :graphBuilt="graphBuilt"
          :entityCount="graphData.nodes?.length || 0"
          :edgeCount="graphData.edges?.length || 0"
          @buildGraph="startBuild"
        />
        <Step2EnvSetup
          v-if="step === 2"
          :entities="entities"
          :preparing="preparing"
          @proceed="startPrepare"
        />
      </div>
    </div>
  </div>
</template>

<script>
import { getProject, getTask, getGraph, buildGraph } from '../api/graph'
import { createSimulation, prepareSimulation, prepareStatus } from '../api/simulation'
import GraphPanel from '../components/GraphPanel.vue'
import Step1GraphBuild from '../components/Step1GraphBuild.vue'
import Step2EnvSetup from '../components/Step2EnvSetup.vue'

export default {
  name: 'MainView',
  components: { GraphPanel, Step1GraphBuild, Step2EnvSetup },
  data() {
    return {
      project: null,
      mode: 'split',
      graphData: { nodes: [], edges: [] },
      entities: [],
      building: false,
      buildProgress: 0,
      buildTaskId: null,
      pollTimer: null,
      preparing: false,
      prepareProgress: 0,
      prepareTaskId: null,
      preparePollTimer: null,
    }
  },
  computed: {
    graphBuilt() {
      return this.project?.status === 'graph_built'
    },
    step() {
      if (!this.project) return 1
      if (this.project.status === 'graph_built' && this.entities.length > 0) return 2
      return 1
    },
  },
  async mounted() {
    await this.loadProject()
  },
  beforeUnmount() {
    if (this.pollTimer) clearInterval(this.pollTimer)
    if (this.preparePollTimer) clearInterval(this.preparePollTimer)
  },
  methods: {
    async loadProject() {
      try {
        const res = await getProject(this.$route.params.projectId)
        this.project = res.data
        if (this.project.graph_id) {
          await this.loadGraph()
        }
      } catch (e) {
        console.error('Failed to load project:', e)
      }
    },
    async loadGraph() {
      try {
        const res = await getGraph(this.project.graph_id)
        this.graphData = res.data
        this.entities = res.data.nodes || []
      } catch (e) {
        console.error('Failed to load graph:', e)
      }
    },
    async startBuild() {
      this.building = true
      this.buildProgress = 0
      try {
        const res = await buildGraph({
          project_id: this.project.project_id,
        })
        this.buildTaskId = res.data.task_id
        this.project.graph_id = res.data.graph_id
        this.pollBuild()
      } catch (e) {
        this.building = false
        console.error('Failed to start build:', e)
      }
    },
    pollBuild() {
      this.pollTimer = setInterval(async () => {
        try {
          const res = await getTask(this.buildTaskId)
          const task = res.data
          this.buildProgress = task.progress
          if (task.status === 'completed') {
            clearInterval(this.pollTimer)
            this.building = false
            await this.loadProject()
            await this.loadGraph()
          } else if (task.status === 'failed') {
            clearInterval(this.pollTimer)
            this.building = false
            console.error('Build failed:', task.error)
          }
        } catch (e) {
          console.error('Poll error:', e)
        }
      }, 2000)
    },
    async startPrepare() {
      this.preparing = true
      this.prepareProgress = 0
      try {
        const createRes = await createSimulation({ project_id: this.project.project_id })
        const simId = createRes.data.simulation_id

        const prepRes = await prepareSimulation({ simulation_id: simId })
        this.prepareTaskId = prepRes.data.task_id

        this.preparePollTimer = setInterval(async () => {
          try {
            const res = await prepareStatus({ task_id: this.prepareTaskId })
            const data = res.data
            this.prepareProgress = data.progress || 0

            if (data.status === 'completed') {
              clearInterval(this.preparePollTimer)
              this.$router.push(`/simulation/${simId}`)
            } else if (data.status === 'failed') {
              clearInterval(this.preparePollTimer)
              this.preparing = false
              console.error('Prepare failed:', data.error)
            }
          } catch (e) {
            console.error('Prepare poll error:', e)
          }
        }, 3000)
      } catch (e) {
        this.preparing = false
        console.error('Failed to start preparation:', e)
      }
    },
  },
}
</script>

<style scoped>
.main-view { height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
.toolbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border);
}
.toolbar-left { display: flex; align-items: center; gap: var(--space-2); }
.toolbar-right { display: flex; gap: var(--space-1); }
.page-title { font-family: var(--font-display); color: var(--primary); font-size: 18px; }

.preparing-banner {
  background: var(--surface);
  border-bottom: 1px solid var(--warning);
  padding: var(--space-2) var(--space-3);
  flex-shrink: 0;
}
.preparing-inner {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--warning);
  font-size: 13px;
  margin-bottom: var(--space-1);
}
.prepare-bar {
  height: 3px;
  background: var(--surface-raised);
  border-radius: 2px;
  overflow: hidden;
}
.prepare-bar-fill {
  height: 100%;
  background: var(--warning);
  transition: width 0.5s ease;
}
.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--border);
  border-top-color: var(--warning);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

.layout { flex: 1; display: flex; overflow: hidden; }
.layout.graph .graph-pane { flex: 1; }
.layout.split .graph-pane { flex: 1; }
.layout.split .work-pane { width: 400px; border-left: 1px solid var(--border); padding: var(--space-3); overflow: hidden; display: flex; flex-direction: column; }
.layout.workbench .work-pane { flex: 1; padding: var(--space-3); overflow-y: auto; }
.graph-pane { min-height: 400px; }
</style>
