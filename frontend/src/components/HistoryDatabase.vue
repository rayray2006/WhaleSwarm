<template>
  <div class="history-db">
    <div class="section-header">
      <h3 class="section-title">Simulation History</h3>
      <button class="btn" @click="loadHistory" :disabled="loading">
        {{ loading ? 'LOADING...' : 'REFRESH' }}
      </button>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="shimmer-list">
      <div v-for="i in 4" :key="i" class="shimmer-row loading-shimmer"></div>
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="error-msg">
      <span>{{ error }}</span>
      <button class="btn" @click="loadHistory">RETRY</button>
    </div>

    <!-- Empty state -->
    <div v-else-if="simulations.length === 0" class="empty-state">
      <p class="muted">No previous simulations found.</p>
    </div>

    <!-- Simulation list -->
    <div v-else class="sim-list">
      <div
        v-for="sim in simulations"
        :key="sim.simulation_id || sim.id"
        class="sim-row"
        @click="openSimulation(sim)"
      >
        <div class="sim-row-left">
          <div class="sim-name">{{ sim.name || sim.simulation_id || sim.id }}</div>
          <div class="sim-meta">
            <span class="tag" :class="'status-' + (sim.status || 'unknown')">
              {{ sim.status || 'unknown' }}
            </span>
            <span class="sim-detail" v-if="sim.num_rounds">{{ sim.num_rounds }} rounds</span>
            <span class="sim-detail" v-if="sim.num_agents">{{ sim.num_agents }} agents</span>
            <span class="sim-detail" v-if="sim.created_at">{{ formatDate(sim.created_at) }}</span>
          </div>
        </div>
        <div class="sim-row-right">
          <span class="sim-platforms" v-if="sim.platforms">
            {{ formatPlatforms(sim.platforms) }}
          </span>
          <span class="arrow">&#8594;</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import service from '../api/index'

export default {
  name: 'HistoryDatabase',
  data() {
    return {
      simulations: [],
      loading: false,
      error: null,
    }
  },
  mounted() {
    this.loadHistory()
  },
  methods: {
    async loadHistory() {
      this.loading = true
      this.error = null
      try {
        const res = await service.get('/simulation/history')
        this.simulations = res.data?.simulations || res.data || []
      } catch (e) {
        // Fallback: try listing from uploads
        try {
          const res = await service.get('/simulation/list')
          this.simulations = res.data?.simulations || res.data || []
        } catch (e2) {
          this.error = 'Failed to load simulation history.'
          console.error('History load error:', e2)
        }
      }
      this.loading = false
    },
    openSimulation(sim) {
      const id = sim.simulation_id || sim.id
      if (sim.status === 'running') {
        this.$router.push(`/simulation/${id}/start`)
      } else {
        this.$router.push(`/simulation/${id}`)
      }
    },
    formatDate(dateStr) {
      try {
        const d = new Date(dateStr)
        return d.toLocaleDateString('en-US', {
          month: 'short',
          day: 'numeric',
          year: 'numeric',
        })
      } catch {
        return dateStr
      }
    },
    formatPlatforms(platforms) {
      if (Array.isArray(platforms)) return platforms.join(', ')
      if (typeof platforms === 'object') return Object.keys(platforms).join(', ')
      return String(platforms)
    },
  },
}
</script>

<style scoped>
.history-db {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.section-title {
  font-family: var(--font-display);
  color: var(--primary);
  font-size: 18px;
}

.shimmer-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.shimmer-row {
  height: 56px;
  border-radius: var(--radius-sm);
}

.error-msg {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  color: var(--danger);
  padding: var(--space-2);
  background: rgba(229, 62, 62, 0.1);
  border-radius: var(--radius-sm);
  border: 1px solid var(--danger);
}

.empty-state {
  text-align: center;
  padding: var(--space-4);
}
.muted { color: var(--muted); font-size: 13px; }

.sim-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
  background: var(--border);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.sim-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-2) var(--space-3);
  background: var(--surface);
  cursor: pointer;
  transition: background 0.15s;
}
.sim-row:hover {
  background: var(--surface-raised);
}
.sim-row-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.sim-name {
  font-size: 14px;
  color: var(--text);
  font-weight: 700;
}
.sim-meta {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}
.sim-detail {
  font-size: 11px;
  color: var(--muted);
}

.sim-row-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.sim-platforms {
  font-size: 11px;
  color: var(--text-secondary);
}
.arrow {
  color: var(--muted);
  font-size: 16px;
}

.status-running { color: var(--accent); border-color: var(--accent); }
.status-completed { color: var(--primary); border-color: var(--primary); }
.status-configured, .status-ready, .status-prepared { color: var(--text-secondary); }
.status-failed { color: var(--danger); border-color: var(--danger); }
.status-unknown { color: var(--muted); }
</style>
