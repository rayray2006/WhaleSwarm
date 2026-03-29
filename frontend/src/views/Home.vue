<template>
  <div class="home">
    <div class="warning-stripes"></div>
    <div class="hero">
      <h1 class="title">WHALESWARM</h1>
      <p class="subtitle">Prediction Market Swarm Intelligence</p>
      <p class="description">
        Pick a Polymarket prediction. Inject a fictional event. Watch how AI agents
        shift the market across Twitter, Reddit, and Polymarket.
      </p>

      <div class="setup-section card">
        <div class="card-header">NEW EXPERIMENT</div>

        <!-- Step 1: Market Search -->
        <div class="form-group">
          <label>Search Polymarket</label>
          <div class="search-row">
            <input
              v-model="marketQuery"
              placeholder="e.g., bitcoin, election, fed rate..."
              @keydown.enter="searchMarkets"
            />
            <button class="btn" :disabled="!marketQuery.trim() || searching" @click="searchMarkets">
              {{ searching ? '...' : 'SEARCH' }}
            </button>
          </div>
        </div>

        <!-- Market Results -->
        <div v-if="marketResults.length > 0" class="market-results">
          <div
            v-for="(m, i) in marketResults"
            :key="i"
            class="market-card"
            :class="{ selected: selectedMarket === m }"
            @click="selectedMarket = m"
          >
            <div class="market-question">{{ m.question || m.title }}</div>
            <div class="market-meta">
              <span class="price-tag yes">YES {{ formatPrice(m) }}</span>
              <span class="price-tag no">NO {{ formatNoPrice(m) }}</span>
              <span v-if="m.volume" class="volume">Vol: ${{ formatVolume(m.volume) }}</span>
            </div>
          </div>
        </div>

        <div v-if="searchDone && marketResults.length === 0" class="no-results">
          No markets found. Try a different search term.
        </div>

        <!-- Step 2: Fictional Event -->
        <div v-if="selectedMarket" class="form-group event-section">
          <label>Fictional Event (injected mid-simulation)</label>
          <textarea
            v-model="fictionalEvent"
            rows="3"
            placeholder="e.g., SEC announces full approval of all Bitcoin spot ETFs..."
          ></textarea>
          <div class="round-row">
            <label class="inline-label">Inject at round</label>
            <input
              v-model.number="eventRound"
              type="number"
              min="1"
              max="9"
              class="round-input"
            />
            <span class="round-hint">of 10</span>
          </div>
        </div>

        <!-- Step 3: Launch -->
        <div v-if="selectedMarket" class="form-group">
          <label>Project Name (optional)</label>
          <input v-model="projectName" placeholder="My Experiment" />
        </div>

        <button
          v-if="selectedMarket"
          class="btn btn-primary launch-btn"
          :disabled="!fictionalEvent.trim() || loading"
          @click="launch"
        >
          {{ loading ? loadingMsg : 'LAUNCH EXPERIMENT' }}
        </button>

        <div v-if="error" class="error-msg">{{ error }}</div>
      </div>
    </div>
    <div class="warning-stripes"></div>
  </div>
</template>

<script>
import { searchPolymarkets, polymarketSetup } from '../api/graph'

export default {
  name: 'Home',
  data() {
    return {
      marketQuery: '',
      marketResults: [],
      selectedMarket: null,
      searching: false,
      searchDone: false,
      fictionalEvent: '',
      eventRound: 5,
      projectName: '',
      loading: false,
      loadingMsg: 'Processing...',
      error: null,
    }
  },
  methods: {
    async searchMarkets() {
      if (!this.marketQuery.trim()) return
      this.searching = true
      this.searchDone = false
      this.selectedMarket = null
      this.error = null
      try {
        const res = await searchPolymarkets(this.marketQuery.trim())
        this.marketResults = res.data.markets || []
        this.searchDone = true
      } catch (e) {
        this.error = e.response?.data?.error || 'Search failed'
      } finally {
        this.searching = false
      }
    },
    formatPrice(m) {
      const prices = m.outcomePrices || m.outcome_prices
      if (prices && prices.length > 0) {
        return '$' + parseFloat(prices[0]).toFixed(2)
      }
      return '---'
    },
    formatNoPrice(m) {
      const prices = m.outcomePrices || m.outcome_prices
      if (prices && prices.length > 1) {
        return '$' + parseFloat(prices[1]).toFixed(2)
      }
      if (prices && prices.length > 0) {
        return '$' + (1 - parseFloat(prices[0])).toFixed(2)
      }
      return '---'
    },
    formatVolume(v) {
      const n = parseFloat(v)
      if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'
      if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K'
      return n.toFixed(0)
    },
    async launch() {
      this.loading = true
      this.error = null
      this.loadingMsg = 'Researching topic...'
      try {
        const res = await polymarketSetup({
          market: this.selectedMarket,
          fictional_event: this.fictionalEvent,
          event_round: this.eventRound,
          project_name: this.projectName || undefined,
        })
        this.$router.push(`/process/${res.data.project_id}`)
      } catch (e) {
        this.error = e.response?.data?.error || e.message
      } finally {
        this.loading = false
      }
    },
  },
}
</script>

<style scoped>
.home {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.hero {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--space-5) var(--space-3);
  gap: var(--space-3);
}

.title {
  font-family: var(--font-display);
  font-size: 56px;
  color: var(--primary);
  letter-spacing: 4px;
  margin-top: var(--space-4);
}

.subtitle {
  font-size: 14px;
  color: var(--muted);
  letter-spacing: 2px;
  text-transform: uppercase;
}

.description {
  max-width: 550px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 13px;
  margin-bottom: var(--space-2);
}

.setup-section {
  width: 100%;
  max-width: 640px;
}

.form-group {
  margin-bottom: var(--space-3);
}

.form-group label {
  display: block;
  font-size: 11px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: var(--space-1);
}

.search-row {
  display: flex;
  gap: var(--space-1);
}

.search-row input {
  flex: 1;
}

/* Market results */
.market-results {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin-bottom: var(--space-3);
  max-height: 320px;
  overflow-y: auto;
}

.market-card {
  padding: var(--space-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.15s;
}

.market-card:hover {
  border-color: var(--text-secondary);
}

.market-card.selected {
  border-color: var(--primary);
  background: rgba(255, 107, 26, 0.06);
}

.market-question {
  font-size: 13px;
  color: var(--text);
  font-weight: 600;
  margin-bottom: 4px;
  line-height: 1.3;
}

.market-meta {
  display: flex;
  gap: var(--space-2);
  align-items: center;
}

.price-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 3px;
  font-variant-numeric: tabular-nums;
}

.price-tag.yes {
  background: rgba(67, 193, 101, 0.15);
  color: var(--accent);
}

.price-tag.no {
  background: rgba(229, 62, 62, 0.15);
  color: var(--danger);
}

.volume {
  font-size: 11px;
  color: var(--muted);
}

.no-results {
  color: var(--muted);
  font-size: 12px;
  text-align: center;
  padding: var(--space-3);
}

/* Event section */
.event-section {
  border-top: 1px solid var(--border);
  padding-top: var(--space-3);
}

.round-row {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  margin-top: var(--space-1);
}

.inline-label {
  font-size: 12px !important;
  color: var(--text-secondary) !important;
  text-transform: none !important;
  letter-spacing: 0 !important;
  margin-bottom: 0 !important;
}

.round-input {
  width: 60px;
  text-align: center;
}

.round-hint {
  font-size: 12px;
  color: var(--muted);
}

.launch-btn {
  width: 100%;
  font-size: 14px;
  padding: var(--space-2);
}

.error-msg {
  margin-top: var(--space-2);
  color: var(--danger);
  font-size: 12px;
}
</style>
