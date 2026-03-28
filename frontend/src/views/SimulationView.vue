<template>
  <div class="sim-view">
    <div class="warning-stripes"></div>

    <div class="toolbar">
      <div class="toolbar-left">
        <button class="btn" @click="$router.back()">&#8592; BACK</button>
        <h2 class="page-title">{{ config?.name || 'Simulation Setup' }}</h2>
        <span class="tag" :class="'status-' + status">{{ status }}</span>
      </div>
      <div class="toolbar-right">
        <button
          class="btn btn-primary"
          :disabled="!canStart"
          @click="handleStart"
        >
          {{ starting ? 'LAUNCHING...' : 'START SIMULATION' }}
        </button>
      </div>
    </div>

    <!-- Preparing overlay -->
    <div v-if="status === 'preparing'" class="preparing-banner">
      <div class="preparing-inner">
        <div class="spinner"></div>
        <span>Generating agent profiles... This may take a minute.</span>
      </div>
      <div class="prepare-bar">
        <div class="prepare-bar-fill" :style="{ width: prepareProgress + '%' }"></div>
      </div>
    </div>

    <!-- Error state -->
    <div v-if="error" class="error-banner">
      <span>{{ error }}</span>
      <button class="btn" @click="error = null">DISMISS</button>
    </div>

    <div class="content">
      <!-- Config summary -->
      <div class="card config-card" v-if="config">
        <div class="card-header">Configuration</div>
        <div class="config-grid">
          <div class="config-item">
            <span class="config-label">Topic</span>
            <span class="config-value">{{ config.topic || config.name }}</span>
          </div>
          <div class="config-item">
            <span class="config-label">Rounds</span>
            <span class="config-value">{{ config.num_rounds || '---' }}</span>
          </div>
          <div class="config-item">
            <span class="config-label">Agents</span>
            <span class="config-value">{{ profiles.length || config.num_agents || '---' }}</span>
          </div>
          <div class="config-item">
            <span class="config-label">Platforms</span>
            <span class="config-value">{{ platformList }}</span>
          </div>
        </div>
      </div>

      <!-- Loading shimmer for profiles -->
      <div v-if="loadingProfiles" class="profiles-loading">
        <div class="card-header">Agent Profiles</div>
        <div class="shimmer-list">
          <div v-for="i in 6" :key="i" class="shimmer-card loading-shimmer"></div>
        </div>
      </div>

      <!-- Agent Profiles -->
      <div v-else-if="profiles.length > 0" class="profiles-section">
        <div class="section-header">
          <span class="card-header">Agent Profiles</span>
          <span class="tag">{{ profiles.length }} agents</span>
        </div>
        <div class="profiles-grid">
          <div
            v-for="profile in profiles"
            :key="profile.agent_id || profile.name"
            class="card profile-card"
          >
            <div class="profile-top">
              <div class="profile-avatar" :style="{ background: avatarColor(profile.type) }">
                {{ avatarLetter(profile.name) }}
              </div>
              <div class="profile-info">
                <div class="profile-name">{{ profile.name }}</div>
                <span class="tag type-tag" :class="'type-' + (profile.type || 'default')">
                  {{ profile.type || 'agent' }}
                </span>
              </div>
            </div>
            <p class="profile-bio">{{ profile.bio || 'No bio available.' }}</p>
            <div class="profile-stats">
              <div class="stat">
                <span class="stat-value">{{ formatNumber(profile.follower_count) }}</span>
                <span class="stat-label">Followers</span>
              </div>
              <div class="stat">
                <span class="stat-value">{{ profile.karma || 0 }}</span>
                <span class="stat-label">Karma</span>
              </div>
              <div class="stat" v-if="profile.initial_balance != null">
                <span class="stat-value">${{ formatNumber(profile.initial_balance) }}</span>
                <span class="stat-label">Balance</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Empty state -->
      <div v-else-if="!loadingProfiles && profiles.length === 0 && status !== 'preparing'" class="empty-state">
        <div class="empty-icon">&#9673;</div>
        <p>No agent profiles generated yet.</p>
        <p class="muted">Profiles will appear once preparation is complete.</p>
      </div>
    </div>
  </div>
</template>

<script>
import { createSimulation, prepareSimulation, getConfig, getProfiles, prepareStatus, startSimulation } from '../api/simulation'

export default {
  name: 'SimulationView',
  data() {
    return {
      config: null,
      profiles: [],
      status: 'loading',
      loadingProfiles: true,
      starting: false,
      error: null,
      prepareProgress: 0,
      prepareTaskId: null,
      pollTimer: null,
      realSimId: null,  // actual simulation ID (may differ from route param)
    }
  },
  computed: {
    simId() {
      return this.$route.params.simId
    },
    canStart() {
      return (
        !this.starting &&
        this.profiles.length > 0 &&
        (this.status === 'ready' || this.status === 'configured' || this.status === 'prepared')
      )
    },
    platformList() {
      if (!this.config?.platforms) return '---'
      if (Array.isArray(this.config.platforms)) {
        return this.config.platforms.join(', ')
      }
      return Object.keys(this.config.platforms).join(', ')
    },
  },
  async mounted() {
    await this.loadData()
  },
  beforeUnmount() {
    if (this.pollTimer) clearInterval(this.pollTimer)
  },
  methods: {
    async loadData() {
      try {
        // Try loading existing simulation data first
        const [configRes, profilesRes] = await Promise.allSettled([
          getConfig(this.simId),
          getProfiles(this.simId),
        ])

        let foundExisting = false

        if (configRes.status === 'fulfilled' && configRes.value.status === 200) {
          this.config = configRes.value.data
          this.status = this.config.status || 'configured'
          foundExisting = true
        }

        if (profilesRes.status === 'fulfilled' && profilesRes.value.status === 200) {
          this.profiles = profilesRes.value.data?.profiles || profilesRes.value.data || []
          if (this.profiles.length > 0) foundExisting = true
        }

        this.loadingProfiles = false

        if (foundExisting) {
          // This simId is a valid simulation ID
          this.realSimId = this.simId
          if (this.status === 'preparing') {
            this.startPolling()
          }
          return
        }

        // No existing simulation found — simId is probably a project_id.
        // Auto-create simulation and start preparation.
        await this.autoCreateAndPrepare()
      } catch (e) {
        this.error = 'Failed to load simulation data.'
        this.loadingProfiles = false
        console.error('SimulationView load error:', e)
      }
    },
    async autoCreateAndPrepare() {
      try {
        this.status = 'preparing'
        this.loadingProfiles = true

        // Create simulation from project_id (simId might be a project_id)
        const createRes = await createSimulation({ project_id: this.simId })
        this.realSimId = createRes.data.simulation_id

        // Start preparation
        const prepRes = await prepareSimulation({ simulation_id: this.realSimId })
        this.prepareTaskId = prepRes.data.task_id

        // Poll for completion
        this.pollTimer = setInterval(async () => {
          try {
            const res = await prepareStatus({ task_id: this.prepareTaskId })
            const data = res.data
            this.prepareProgress = data.progress || 0

            if (data.status === 'completed') {
              clearInterval(this.pollTimer)
              this.pollTimer = null
              this.status = 'prepared'
              this.loadingProfiles = false
              const profilesRes = await getProfiles(this.realSimId)
              this.profiles = profilesRes.data?.profiles || profilesRes.data || []
            } else if (data.status === 'failed') {
              clearInterval(this.pollTimer)
              this.pollTimer = null
              this.status = 'failed'
              this.loadingProfiles = false
              this.error = data.error || 'Profile generation failed.'
            }
          } catch (e) {
            console.error('Prepare poll error:', e)
          }
        }, 3000)
      } catch (e) {
        this.status = 'failed'
        this.loadingProfiles = false
        this.error = e.response?.data?.error || 'Failed to create simulation.'
        console.error('Auto-create error:', e)
      }
    },
    startPolling() {
      this.pollTimer = setInterval(async () => {
        try {
          const res = await prepareStatus({ simulation_id: this.simId })
          const data = res.data
          this.prepareProgress = data.progress || 0

          if (data.status === 'ready' || data.status === 'prepared' || data.status === 'configured') {
            clearInterval(this.pollTimer)
            this.pollTimer = null
            this.status = data.status
            // Reload profiles now that preparation is done
            const profilesRes = await getProfiles(this.simId)
            this.profiles = profilesRes.data?.profiles || profilesRes.data || []
          } else if (data.status === 'failed') {
            clearInterval(this.pollTimer)
            this.pollTimer = null
            this.status = 'failed'
            this.error = data.error || 'Profile generation failed.'
          }
        } catch (e) {
          console.error('Prepare poll error:', e)
        }
      }, 3000)
    },
    async handleStart() {
      this.starting = true
      this.error = null
      const sid = this.realSimId || this.simId
      try {
        await startSimulation({ simulation_id: sid })
        this.$router.push(`/simulation/${sid}/start`)
      } catch (e) {
        this.error = e.response?.data?.error || e.response?.data?.detail || 'Failed to start simulation.'
        this.starting = false
        console.error('Start error:', e)
      }
    },
    avatarLetter(name) {
      return name ? name.charAt(0).toUpperCase() : '?'
    },
    avatarColor(type) {
      const colors = {
        whale: '#FF6B1A',
        retail: '#43C165',
        bot: '#ECC94B',
        influencer: '#9F7AEA',
        analyst: '#4299E1',
        default: '#666666',
      }
      return colors[type] || colors.default
    },
    formatNumber(n) {
      if (n == null) return '---'
      if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
      if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
      return String(n)
    },
  },
}
</script>

<style scoped>
.sim-view {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border);
}
.toolbar-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.toolbar-right {
  display: flex;
  gap: var(--space-1);
}
.page-title {
  font-family: var(--font-display);
  color: var(--primary);
  font-size: 18px;
}

.status-loading { color: var(--muted); }
.status-preparing { color: var(--warning); border-color: var(--warning); }
.status-ready, .status-prepared, .status-configured {
  color: var(--accent);
  border-color: var(--accent);
}
.status-failed { color: var(--danger); border-color: var(--danger); }

.preparing-banner {
  background: var(--surface);
  border-bottom: 1px solid var(--warning);
  padding: var(--space-2) var(--space-3);
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
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

.error-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: rgba(229, 62, 62, 0.1);
  border-bottom: 1px solid var(--danger);
  padding: var(--space-2) var(--space-3);
  color: var(--danger);
  font-size: 13px;
}

.content {
  flex: 1;
  padding: var(--space-3);
  overflow-y: auto;
}

.config-card {
  margin-bottom: var(--space-3);
}
.config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--space-2);
  margin-top: var(--space-2);
}
.config-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.config-label {
  font-size: 11px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.config-value {
  font-size: 14px;
  color: var(--text);
}

.shimmer-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-2);
  margin-top: var(--space-2);
}
.shimmer-card {
  height: 160px;
  border-radius: var(--radius-md);
}

.profiles-section {
  margin-top: var(--space-2);
}
.section-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.profiles-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-2);
}

.profile-card {
  transition: border-color 0.2s;
}
.profile-card:hover {
  border-color: var(--primary-dim);
}
.profile-top {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.profile-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 16px;
  color: var(--background);
  font-weight: 700;
  flex-shrink: 0;
}
.profile-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.profile-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
}
.type-tag {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.type-whale { color: var(--primary); border-color: var(--primary); }
.type-retail { color: var(--accent); border-color: var(--accent); }
.type-bot { color: var(--warning); border-color: var(--warning); }
.type-influencer { color: #9F7AEA; border-color: #9F7AEA; }
.type-analyst { color: #4299E1; border-color: #4299E1; }

.profile-bio {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin-bottom: var(--space-2);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.profile-stats {
  display: flex;
  gap: var(--space-3);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border);
}
.stat {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.stat-value {
  font-size: 14px;
  color: var(--text);
  font-weight: 700;
}
.stat-label {
  font-size: 10px;
  color: var(--muted);
  text-transform: uppercase;
}

.empty-state {
  text-align: center;
  padding: var(--space-6) var(--space-3);
  color: var(--text-secondary);
}
.empty-icon {
  font-size: 48px;
  color: var(--muted);
  margin-bottom: var(--space-2);
}
.muted {
  color: var(--muted);
  font-size: 13px;
}
</style>
