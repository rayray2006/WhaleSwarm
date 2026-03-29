<template>
  <div class="step2">
    <div class="card">
      <div class="card-header">ENTITIES ({{ entities.length }})</div>

      <div class="entity-list">
        <div v-for="entity in entities" :key="entity.uuid" class="entity-item">
          <span class="tag" :style="{ borderColor: getColor(entity.type) }">
            {{ entity.type }}
          </span>
          <span class="entity-name">{{ entity.name }}</span>
          <span class="entity-summary">{{ entity.summary }}</span>
        </div>
      </div>

      <div class="actions" v-if="entities.length > 0">
        <button class="btn btn-primary" :disabled="preparing" @click="$emit('proceed')">
          {{ preparing ? 'Generating Profiles...' : 'Proceed to Simulation' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script>
const TYPE_COLORS = {
  Journalist: '#FF6B1A', Politician: '#E53E3E', CEO: '#43C165',
  Company: '#3182CE', Organization: '#805AD5', Professor: '#D69E2E',
  Student: '#38B2AC', MediaOutlet: '#ED64A6', Person: '#718096',
}

export default {
  name: 'Step2EnvSetup',
  props: {
    entities: { type: Array, default: () => [] },
    preparing: { type: Boolean, default: false },
  },
  emits: ['proceed'],
  methods: {
    getColor(type) {
      return TYPE_COLORS[type] || '#666'
    },
  },
}
</script>

<style scoped>
.step2 {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.step2 .card {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.entity-list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}
.entity-item .tag {
  flex-shrink: 0;
  white-space: nowrap;
}
.entity-item {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  padding: var(--space-1) 0;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  min-width: 0;
  overflow: hidden;
}
.entity-name { font-weight: 700; white-space: nowrap; flex-shrink: 0; max-width: 40%; overflow: hidden; text-overflow: ellipsis; }
.entity-summary {
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.actions { margin-top: var(--space-3); }
</style>
