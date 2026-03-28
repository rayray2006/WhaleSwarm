<template>
  <div class="step1">
    <div class="card">
      <div class="card-header">ONTOLOGY</div>

      <div v-if="ontology">
        <div class="section">
          <div class="section-label">Entity Types</div>
          <div class="tags">
            <span v-for="t in ontology.entity_types" :key="t" class="tag">{{ t }}</span>
          </div>
        </div>
        <div class="section">
          <div class="section-label">Relationship Types</div>
          <div class="tags">
            <span v-for="t in ontology.edge_types" :key="t" class="tag">{{ t }}</span>
          </div>
        </div>
        <div class="section" v-if="ontology.analysis_summary">
          <div class="section-label">Analysis</div>
          <p class="analysis">{{ ontology.analysis_summary }}</p>
        </div>
      </div>

      <div v-if="!graphBuilt" class="actions">
        <button
          class="btn btn-primary"
          :disabled="building"
          @click="$emit('buildGraph')"
        >
          {{ building ? 'Building...' : 'Build Knowledge Graph' }}
        </button>
      </div>

      <div v-if="building" class="progress-bar">
        <div class="progress-fill" :style="{ width: progress + '%' }"></div>
        <span class="progress-text">{{ progress }}%</span>
      </div>

      <div v-if="graphBuilt" class="success">
        Graph built: {{ entityCount }} entities, {{ edgeCount }} edges
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'Step1GraphBuild',
  props: {
    ontology: Object,
    building: Boolean,
    progress: { type: Number, default: 0 },
    graphBuilt: Boolean,
    entityCount: { type: Number, default: 0 },
    edgeCount: { type: Number, default: 0 },
  },
  emits: ['buildGraph'],
}
</script>

<style scoped>
.section { margin-bottom: var(--space-3); }
.section-label {
  font-size: 11px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: var(--space-1);
}
.tags { display: flex; flex-wrap: wrap; gap: var(--space-1); }
.analysis { font-size: 12px; color: var(--text-secondary); line-height: 1.5; }
.actions { margin-top: var(--space-3); }
.progress-bar {
  margin-top: var(--space-2);
  height: 24px;
  background: var(--surface-raised);
  border-radius: var(--radius-sm);
  position: relative;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: var(--primary);
  transition: width 0.3s;
  border-radius: var(--radius-sm);
}
.progress-text {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 11px;
  font-weight: 700;
}
.success {
  margin-top: var(--space-2);
  color: var(--accent);
  font-size: 13px;
}
</style>
