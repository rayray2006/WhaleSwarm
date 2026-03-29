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
            :class="[
              agentClass(profile),
              { expanded: expandedAgent === profile }
            ]"
            @click="toggleExpand(profile)"
          >
            <div class="profile-top">
              <div class="profile-avatar" :style="{ background: agentColor(profile) }">
                {{ avatarLetter(profile.name) }}
              </div>
              <div class="profile-info">
                <div class="profile-name">{{ profile.name }}</div>
                <div class="profile-meta-row">
                  <span class="type-pill" :style="{ background: agentColor(profile) + '20', color: agentColor(profile) }">
                    {{ agentLabel(profile) }}
                  </span>
                  <span v-if="profile.profession" class="profession">{{ profile.profession }}</span>
                </div>
              </div>
              <div class="expand-icon">{{ expandedAgent === profile ? '&#9650;' : '&#9660;' }}</div>
            </div>

            <p class="profile-bio">{{ profile.bio || 'No bio available.' }}</p>

            <div class="profile-stats">
              <div class="stat">
                <span class="stat-value">{{ formatNumber(profile.follower_count) }}</span>
                <span class="stat-label">Followers</span>
              </div>
              <div class="stat" v-if="isPerson(profile)">
                <span class="stat-value">{{ profile.karma || 0 }}</span>
                <span class="stat-label">Karma</span>
              </div>
              <div class="stat" v-if="isPerson(profile)">
                <span class="stat-value risk-val" :class="'risk-' + (profile.risk_tolerance || 'moderate')">
                  {{ profile.risk_tolerance || 'moderate' }}
                </span>
                <span class="stat-label">Risk</span>
              </div>
              <div class="stat" v-if="!isPerson(profile)">
                <span class="stat-value">Twitter only</span>
                <span class="stat-label">Platforms</span>
              </div>
              <div class="stat" v-if="profile.initial_balance != null && isPerson(profile)">
                <span class="stat-value">${{ formatNumber(profile.initial_balance) }}</span>
                <span class="stat-label">Balance</span>
              </div>
            </div>

            <!-- Expanded Detail -->
            <transition name="detail">
              <div v-if="expandedAgent === profile" class="profile-detail" @click.stop>
                <div class="detail-section">
                  <div class="detail-label">PERSONA</div>
                  <p class="detail-text">{{ profile.persona || profile.user_char || '---' }}</p>
                </div>

                <div class="detail-grid">
                  <div class="detail-cell" v-if="profile.age && isPerson(profile)">
                    <span class="detail-label">AGE</span>
                    <span class="detail-val">{{ profile.age }}</span>
                  </div>
                  <div class="detail-cell" v-if="profile.gender && isPerson(profile)">
                    <span class="detail-label">GENDER</span>
                    <span class="detail-val">{{ profile.gender }}</span>
                  </div>
                  <div class="detail-cell" v-if="profile.mbti && isPerson(profile)">
                    <span class="detail-label">MBTI</span>
                    <span class="detail-val">{{ profile.mbti }}</span>
                  </div>
                  <div class="detail-cell" v-if="profile.country">
                    <span class="detail-label">{{ isPerson(profile) ? 'COUNTRY' : 'HQ' }}</span>
                    <span class="detail-val">{{ profile.country }}</span>
                  </div>
                  <div class="detail-cell">
                    <span class="detail-label">FOLLOWING</span>
                    <span class="detail-val">{{ formatNumber(profile.friend_count) }}</span>
                  </div>
                  <div class="detail-cell">
                    <span class="detail-label">POSTS</span>
                    <span class="detail-val">{{ formatNumber(profile.statuses_count) }}</span>
                  </div>
                </div>

                <div class="detail-section" v-if="profile.interested_topics && profile.interested_topics.length">
                  <div class="detail-label">INTERESTS</div>
                  <div class="topics">
                    <span v-for="t in profile.interested_topics" :key="t" class="topic-tag">{{ t }}</span>
                  </div>
                </div>
              </div>
            </transition>
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

const AGENT_CATEGORIES = [
  // Institutions (checked first — these are not "persons")
  { keywords: ['mediaoutlet', 'media outlet', 'news', 'press', 'broadcast', 'network', 'times', 'post', 'reuters', 'associated press', 'bbc', 'cnn', 'fox', 'nbc', 'abc news', 'msnbc', 'al jazeera'], color: '#FC8181', label: 'Media', isPerson: false },
  { keywords: ['governmentagency', 'government agency', 'department', 'ministry', 'bureau', 'federal', 'pentagon', 'state department', 'treasury', 'fbi', 'cia', 'nsa', 'sec ', 'fda', 'epa', 'central bank', 'reserve bank'], color: '#E53E3E', label: 'Govt Agency', isPerson: false },
  { keywords: ['company', 'corporation', 'inc', 'corp', 'ltd', 'llc', 'group', 'holdings', 'apple', 'google', 'meta', 'microsoft', 'amazon', 'tesla'], color: '#63B3ED', label: 'Company', isPerson: false },
  { keywords: ['ngo', 'non-profit', 'nonprofit', 'foundation', 'charity', 'red cross', 'amnesty', 'oxfam', 'greenpeace', 'unicef'], color: '#68D391', label: 'NGO', isPerson: false },
  { keywords: ['thinktank', 'think tank', 'institute', 'council', 'brookings', 'rand', 'heritage', 'cato'], color: '#B794F4', label: 'Think Tank', isPerson: false },
  { keywords: ['organization', 'organisation', 'union', 'association', 'nato', 'opec', 'who', 'imf', 'world bank', 'united nations'], color: '#D69E2E', label: 'Organization', isPerson: false },
  { keywords: ['studio', 'publisher', 'league', 'rockstar', 'ea ', 'ubisoft', 'nfl', 'nba', 'fifa', 'mlb'], color: '#F687B3', label: 'Entertainment', isPerson: false },
  // Individuals
  { keywords: ['politician', 'senator', 'congressman', 'representative', 'mayor', 'governor', 'president', 'minister', 'chancellor'], color: '#E53E3E', label: 'Politician', isPerson: true },
  { keywords: ['diplomat', 'ambassador', 'envoy', 'secretary-general', 'consul'], color: '#D69E2E', label: 'Diplomat', isPerson: true },
  { keywords: ['military', 'general', 'admiral', 'colonel', 'commander', 'veteran', 'officer'], color: '#A0AEC0', label: 'Military', isPerson: true },
  { keywords: ['journalist', 'reporter', 'correspondent', 'editor', 'anchor', 'columnist', 'commentator'], color: '#FC8181', label: 'Journalist', isPerson: true },
  { keywords: ['ceo', 'executive', 'founder', 'chairman', 'director', 'vp ', 'vice president', 'cto', 'cfo', 'coo'], color: '#FF6B1A', label: 'Executive', isPerson: true },
  { keywords: ['trader', 'day trader'], color: '#F6AD55', label: 'Trader', isPerson: true },
  { keywords: ['investor', 'venture', 'hedge fund', 'portfolio'], color: '#F6AD55', label: 'Investor', isPerson: true },
  { keywords: ['analyst', 'strategist', 'forecaster', 'economist'], color: '#4299E1', label: 'Analyst', isPerson: true },
  { keywords: ['lawyer', 'attorney', 'legal', 'counsel', 'judge'], color: '#B794F4', label: 'Legal', isPerson: true },
  { keywords: ['professor', 'researcher', 'scientist', 'academic', 'scholar', 'phd'], color: '#68D391', label: 'Academic', isPerson: true },
  { keywords: ['student', 'grad student', 'undergrad'], color: '#68D391', label: 'Student', isPerson: true },
  { keywords: ['engineer', 'developer', 'programmer', 'software'], color: '#63B3ED', label: 'Tech', isPerson: true },
  { keywords: ['doctor', 'nurse', 'physician', 'surgeon', 'medical', 'dentist', 'therapist'], color: '#4FD1C5', label: 'Healthcare', isPerson: true },
  { keywords: ['teacher', 'instructor', 'tutor', 'educator'], color: '#F687B3', label: 'Education', isPerson: true },
  { keywords: ['activist', 'advocate', 'organizer', 'campaigner'], color: '#FBD38D', label: 'Activist', isPerson: true },
  { keywords: ['influencer', 'creator', 'streamer', 'youtuber', 'blogger', 'tiktoker'], color: '#9F7AEA', label: 'Influencer', isPerson: true },
  { keywords: ['athlete', 'player', 'coach', 'manager'], color: '#F6AD55', label: 'Sports', isPerson: true },
  // Broad person fallbacks (checked last)
  { keywords: ['accountant', 'mechanic', 'electrician', 'plumber', 'chef', 'cook', 'bartender', 'driver', 'pilot', 'carpenter', 'baker', 'barista', 'retail', 'supervisor', 'coordinator', 'clerk', 'worker', 'owner'], color: '#A0AEC0', label: 'Civilian', isPerson: true },
]

const DEFAULT_CAT = { color: '#718096', label: 'Person', isPerson: true }

function classifyAgent(profile) {
  const haystack = [
    profile.profession,
    profile.type,
    profile.source_entity_type,
    profile.bio,
  ].filter(Boolean).join(' ').toLowerCase()

  for (const cat of AGENT_CATEGORIES) {
    for (const kw of cat.keywords) {
      if (haystack.includes(kw)) return cat
    }
  }
  return DEFAULT_CAT
}

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
      realSimId: null,
      expandedAgent: null,
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
    toggleExpand(profile) {
      this.expandedAgent = this.expandedAgent === profile ? null : profile
    },
    agentColor(profile) {
      return classifyAgent(profile).color
    },
    agentLabel(profile) {
      return classifyAgent(profile).label
    },
    agentClass(profile) {
      return 'agent-' + classifyAgent(profile).label.toLowerCase().replace(/\s+/g, '-')
    },
    isPerson(profile) {
      return classifyAgent(profile).isPerson
    },
    async loadData() {
      try {
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
          this.realSimId = this.simId
          if (this.status === 'preparing') {
            this.startPolling()
          }
          return
        }

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

        const createRes = await createSimulation({ project_id: this.simId })
        this.realSimId = createRes.data.simulation_id

        const prepRes = await prepareSimulation({ simulation_id: this.realSimId })
        this.prepareTaskId = prepRes.data.task_id

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
            const profilesRes = await getProfiles(this.simId)
            this.profiles = profilesRes.value.data?.profiles || profilesRes.data || []
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
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--space-2);
}

/* ---- Profile Card ---- */
.profile-card {
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
  border-left: 3px solid var(--border);
}
.profile-card:hover {
  border-color: var(--text-secondary);
}
.profile-card.expanded {
  border-color: var(--primary);
  box-shadow: 0 0 0 1px var(--primary) inset;
}

/* Color-coded left borders by agent type */
.profile-card.agent-trader { border-left-color: #F6AD55; }
.profile-card.agent-investor { border-left-color: #F6AD55; }
.profile-card.agent-analyst { border-left-color: #4299E1; }
.profile-card.agent-media { border-left-color: #FC8181; }
.profile-card.agent-journalist { border-left-color: #FC8181; }
.profile-card.agent-politician { border-left-color: #E53E3E; }
.profile-card.agent-govt-agency { border-left-color: #E53E3E; }
.profile-card.agent-diplomat { border-left-color: #D69E2E; }
.profile-card.agent-legal { border-left-color: #B794F4; }
.profile-card.agent-tech { border-left-color: #63B3ED; }
.profile-card.agent-company { border-left-color: #63B3ED; }
.profile-card.agent-academic { border-left-color: #68D391; }
.profile-card.agent-student { border-left-color: #68D391; }
.profile-card.agent-ngo { border-left-color: #68D391; }
.profile-card.agent-healthcare { border-left-color: #4FD1C5; }
.profile-card.agent-education { border-left-color: #F687B3; }
.profile-card.agent-entertainment { border-left-color: #F687B3; }
.profile-card.agent-military { border-left-color: #A0AEC0; }
.profile-card.agent-civilian { border-left-color: #A0AEC0; }
.profile-card.agent-activist { border-left-color: #FBD38D; }
.profile-card.agent-executive { border-left-color: #FF6B1A; }
.profile-card.agent-influencer { border-left-color: #9F7AEA; }
.profile-card.agent-think-tank { border-left-color: #B794F4; }
.profile-card.agent-organization { border-left-color: #D69E2E; }
.profile-card.agent-sports { border-left-color: #F6AD55; }
.profile-card.agent-person { border-left-color: #718096; }

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
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.profile-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.profile-meta-row {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}
.type-pill {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  white-space: nowrap;
}
.profession {
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.expand-icon {
  font-size: 10px;
  color: var(--muted);
  flex-shrink: 0;
  margin-left: auto;
}

.profile-bio {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin-bottom: var(--space-2);
}
.profile-card:not(.expanded) .profile-bio {
  display: -webkit-box;
  -webkit-line-clamp: 2;
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
  font-size: 13px;
  color: var(--text);
  font-weight: 700;
}
.stat-label {
  font-size: 10px;
  color: var(--muted);
  text-transform: uppercase;
}
.risk-val {
  text-transform: capitalize;
  font-size: 12px;
}
.risk-aggressive { color: var(--danger); }
.risk-moderate { color: var(--warning); }
.risk-conservative { color: var(--accent); }

/* ---- Expanded Detail ---- */
.profile-detail {
  margin-top: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border);
  animation: fadeIn 0.2s ease;
}

.detail-section {
  margin-bottom: var(--space-2);
}
.detail-label {
  font-size: 10px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}
.detail-text {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
  white-space: pre-wrap;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-1);
  margin-bottom: var(--space-2);
}
.detail-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 8px;
  background: var(--surface-raised);
  border-radius: var(--radius-sm);
}
.detail-val {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  text-transform: capitalize;
}

.topics {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.topic-tag {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 3px;
  background: var(--surface-raised);
  border: 1px solid var(--border);
  color: var(--text-secondary);
}

.detail-enter-active,
.detail-leave-active {
  transition: opacity 0.2s, max-height 0.3s;
}
.detail-enter-from,
.detail-leave-to {
  opacity: 0;
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
