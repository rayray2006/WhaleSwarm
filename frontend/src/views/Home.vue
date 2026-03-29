<template>
  <div class="home">
    <div class="warning-stripes"></div>
    <div class="split">
      <!-- Left: Branding -->
      <div class="brand-side">
        <div class="brand-content">
          <h1 class="logo">WHALE<br/>SWARM</h1>
          <div class="tagline">Prediction Market<br/>Swarm Intelligence</div>
          <p class="blurb">
            Pick a Polymarket prediction. Watch AI agents shift the market
            as they deliberate across Twitter and Reddit. Inject hypothetical
            events and see how the market adapts.
          </p>
          <div class="decorative-line"></div>
        </div>
      </div>

      <!-- Right: Experiment -->
      <div class="form-side">
        <div class="form-panel">
          <div class="panel-header">NEW EXPERIMENT</div>

          <!-- Step 1: Search -->
          <label class="field-label">Search Polymarket</label>
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

          <!-- Market Results -->
          <div v-if="marketResults.length > 0" class="market-list">
            <div
              v-for="(m, i) in marketResults"
              :key="i"
              class="market-card"
              :class="{ selected: selectedMarket === m }"
              @click="selectedMarket = m"
            >
              <div class="market-q">{{ m.question || m.title }}</div>
              <div class="market-row">
                <span class="pill yes">YES {{ formatPrice(m) }}</span>
                <span class="pill no">NO {{ formatNoPrice(m) }}</span>
                <span v-if="m.volume" class="vol">Vol ${{ formatVolume(m.volume) }}</span>
              </div>
            </div>
          </div>

          <div v-if="searchDone && marketResults.length === 0" class="empty">
            No markets found. Try a different term.
          </div>

          <template v-if="selectedMarket">
            <button
              class="btn btn-primary launch-btn"
              :disabled="loading"
              @click="launch"
            >
              {{ loading ? loadingMsg : 'LAUNCH EXPERIMENT' }}
            </button>
          </template>

          <div v-if="error" class="error-msg">{{ error }}</div>
        </div>
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

.split {
  flex: 1;
  display: flex;
  min-height: 0;
}

/* ---- Left: Brand ---- */
.brand-side {
  flex: 0 0 42%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-5);
  position: relative;
  overflow: hidden;
}

.brand-side::before {
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse at 30% 50%, rgba(255, 107, 26, 0.06) 0%, transparent 70%);
  pointer-events: none;
}

.brand-content {
  position: relative;
  max-width: 380px;
}

.logo {
  font-family: var(--font-display);
  font-size: 72px;
  line-height: 0.95;
  color: var(--primary);
  letter-spacing: 3px;
  margin-bottom: var(--space-3);
}

.tagline {
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 3px;
  color: var(--muted);
  line-height: 1.6;
  margin-bottom: var(--space-4);
}

.blurb {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.7;
}

.decorative-line {
  margin-top: var(--space-4);
  width: 48px;
  height: 2px;
  background: var(--primary);
  opacity: 0.4;
}

/* ---- Right: Form ---- */
.form-side {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
  border-left: 1px solid var(--border);
}

.form-panel {
  width: 100%;
  max-width: 520px;
}

.panel-header {
  font-family: var(--font-display);
  font-size: 20px;
  color: var(--primary);
  margin-bottom: var(--space-3);
}

.field-label {
  display: block;
  font-size: 11px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: var(--space-1);
  margin-top: var(--space-3);
}

.field-label:first-of-type {
  margin-top: 0;
}

.search-row {
  display: flex;
  gap: var(--space-1);
}

.search-row input {
  flex: 1;
}

/* ---- Market list ---- */
.market-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: var(--space-2);
  max-height: 280px;
  overflow-y: auto;
  padding-right: 4px;
}

.market-card {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.market-card:hover {
  border-color: var(--text-secondary);
}

.market-card.selected {
  border-color: var(--primary);
  background: rgba(255, 107, 26, 0.05);
}

.market-q {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.35;
  margin-bottom: 6px;
}

.market-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.pill {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 3px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.3px;
}

.pill.yes {
  background: rgba(67, 193, 101, 0.12);
  color: var(--accent);
}

.pill.no {
  background: rgba(229, 62, 62, 0.12);
  color: var(--danger);
}

.vol {
  font-size: 10px;
  color: var(--muted);
  margin-left: auto;
}

.empty {
  color: var(--muted);
  font-size: 12px;
  text-align: center;
  padding: var(--space-3) 0;
}

/* ---- Launch ---- */
.launch-btn {
  width: 100%;
  margin-top: var(--space-3);
  padding: var(--space-2);
  font-size: 13px;
}

.error-msg {
  margin-top: var(--space-2);
  color: var(--danger);
  font-size: 12px;
}

/* ---- Responsive ---- */
@media (max-width: 860px) {
  .split {
    flex-direction: column;
  }

  .brand-side {
    flex: none;
    padding: var(--space-4) var(--space-3) var(--space-3);
    text-align: center;
  }

  .brand-content {
    max-width: 100%;
  }

  .logo {
    font-size: 48px;
    display: inline;
  }

  .logo br {
    display: none;
  }

  .decorative-line {
    margin: var(--space-3) auto 0;
  }

  .form-side {
    border-left: none;
    border-top: 1px solid var(--border);
    padding: var(--space-3);
  }
}
</style>
