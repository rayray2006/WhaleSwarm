<template>
  <div class="step3">
    <div class="step-header">
      <h3 class="step-title">Step 3: Simulation</h3>
      <p class="step-desc">Configure and launch the multi-agent simulation.</p>
    </div>

    <!-- Config form -->
    <div class="form-section">
      <label class="form-label">Simulation Name</label>
      <input
        v-model="simName"
        type="text"
        placeholder="e.g. BTC Election Scenario"
        :disabled="generating"
      />
    </div>

    <div class="form-section">
      <label class="form-label">Number of Rounds</label>
      <input
        v-model.number="numRounds"
        type="number"
        min="1"
        max="200"
        placeholder="50"
        :disabled="generating"
      />
    </div>

    <div class="form-section">
      <label class="form-label">Number of Agents</label>
      <input
        v-model.number="numAgents"
        type="number"
        min="2"
        max="50"
        placeholder="10"
        :disabled="generating"
      />
    </div>

    <div class="form-section">
      <label class="form-label">Platforms</label>
      <div class="platform-checks">
        <label class="check-label" v-for="p in platformOptions" :key="p.value">
          <input
            type="checkbox"
            :value="p.value"
            v-model="platforms"
            :disabled="generating"
          />
          <span>{{ p.label }}</span>
        </label>
      </div>
    </div>

    <!-- Generate / Navigate -->
    <div class="actions">
      <button
        class="btn btn-primary"
        :disabled="!canGenerate || generating"
        @click="handleGenerate"
      >
        {{ generating ? 'GENERATING...' : 'GENERATE CONFIG' }}
      </button>
    </div>

    <!-- Status feedback -->
    <div v-if="generating" class="gen-status">
      <div class="spinner"></div>
      <span>Creating simulation and preparing agent profiles...</span>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>

    <div v-if="simulationId" class="success-section">
      <div class="success-msg">
        Simulation created successfully.
      </div>
      <button class="btn btn-primary" @click="goToSimulation">
        OPEN SIMULATION &#8594;
      </button>
    </div>
  </div>
</template>

<script>
import { createSimulation, prepareSimulation } from '../api/simulation'

export default {
  name: 'Step3Simulation',
  props: {
    projectId: { type: String, default: '' },
    entities: { type: Array, default: () => [] },
    ontology: { type: Object, default: null },
  },
  data() {
    return {
      simName: '',
      numRounds: 50,
      numAgents: 10,
      platforms: ['twitter', 'reddit', 'polymarket'],
      generating: false,
      simulationId: null,
      error: null,
      platformOptions: [
        { value: 'twitter', label: 'Twitter' },
        { value: 'reddit', label: 'Reddit' },
        { value: 'polymarket', label: 'Polymarket' },
      ],
    }
  },
  computed: {
    canGenerate() {
      return this.simName.trim().length > 0 && this.platforms.length > 0 && this.numAgents >= 2
    },
  },
  methods: {
    async handleGenerate() {
      this.generating = true
      this.error = null
      this.simulationId = null
      try {
        const payload = {
          project_id: this.projectId,
          name: this.simName,
          num_rounds: this.numRounds,
          num_agents: this.numAgents,
          platforms: this.platforms,
        }
        const res = await createSimulation(payload)
        this.simulationId = res.data.simulation_id || res.data.sim_id

        // Kick off profile preparation
        try {
          await prepareSimulation({ simulation_id: this.simulationId })
        } catch (prepErr) {
          console.warn('Prepare call failed (may already be preparing):', prepErr)
        }
      } catch (e) {
        this.error = e.response?.data?.detail || 'Failed to create simulation.'
        console.error('Create simulation error:', e)
      }
      this.generating = false
    },
    goToSimulation() {
      this.$router.push(`/simulation/${this.simulationId}`)
    },
  },
}
</script>

<style scoped>
.step3 {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.step-header {
  margin-bottom: var(--space-1);
}
.step-title {
  font-family: var(--font-display);
  color: var(--primary);
  font-size: 18px;
  margin-bottom: 4px;
}
.step-desc {
  font-size: 13px;
  color: var(--text-secondary);
}

.form-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.form-label {
  font-size: 11px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.platform-checks {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.check-label {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
}
.check-label input[type="checkbox"] {
  width: auto;
  accent-color: var(--primary);
}

.actions {
  margin-top: var(--space-1);
}

.gen-status {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 13px;
  color: var(--warning);
}

.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--border);
  border-top-color: var(--warning);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

.error-msg {
  font-size: 13px;
  color: var(--danger);
  padding: var(--space-1) var(--space-2);
  background: rgba(229, 62, 62, 0.1);
  border-radius: var(--radius-sm);
  border: 1px solid var(--danger);
}

.success-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.success-msg {
  font-size: 13px;
  color: var(--accent);
  padding: var(--space-1) var(--space-2);
  background: rgba(67, 193, 101, 0.1);
  border-radius: var(--radius-sm);
  border: 1px solid var(--accent);
}
</style>
