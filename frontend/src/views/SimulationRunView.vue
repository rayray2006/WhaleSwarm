<template>
  <div class="run-view">
    <div class="warning-stripes"></div>

    <!-- Header bar -->
    <div class="run-header">
      <div class="header-left">
        <h2 class="page-title">{{ config?.name || 'Simulation' }}</h2>
        <span class="tag" :class="'status-' + runStatus">{{ runStatus }}</span>
      </div>
      <div class="header-center">
        <div class="time-display">
          <span class="time-label">SIM TIME</span>
          <span class="time-value">{{ simulatedTime }}</span>
        </div>
        <div class="round-display">
          <span class="round-label">ROUND</span>
          <span class="round-value">{{ currentRound }}<span class="round-total">/{{ totalRounds }}</span></span>
        </div>
        <div class="round-bar">
          <div class="round-bar-fill" :style="{ width: roundProgress + '%' }"></div>
        </div>
      </div>
      <div class="header-right">
        <button
          v-if="isRunning && !paused"
          class="btn btn-warn"
          @click="handlePause"
        >PAUSE</button>
        <button
          v-if="paused"
          class="btn btn-accent"
          @click="handleResume"
        >RESUME</button>
        <button
          v-if="isFinished"
          class="btn"
          @click="$router.push(`/simulation/${simId}`)"
        >BACK</button>
        <button
          v-if="isFinished"
          class="btn btn-primary"
          @click="$router.push(`/report/${simId}`)"
        >VIEW REPORT</button>
      </div>
    </div>

    <!-- Error banner -->
    <div v-if="error" class="error-banner">
      <span>{{ error }}</span>
      <button class="btn" @click="error = null">DISMISS</button>
    </div>

    <!-- Main grid -->
    <div class="run-grid">
      <!-- Action Feed (left column) -->
      <div class="panel action-feed-panel">
        <div class="panel-header">
          <span class="panel-title">Action Feed</span>
          <span class="tag">{{ actions.length }} actions</span>
        </div>
        <div class="action-list" ref="actionList">
          <div
            v-for="(action, i) in displayActions"
            :key="i"
            class="action-item"
            :style="{ animationDelay: (i % 5) * 40 + 'ms' }"
          >
            <span class="action-platform" :class="'platform-' + action.platform">
              {{ platformIcon(action.platform) }}
            </span>
            <span class="action-agent">{{ action.agent_name || action.agent_id || 'Agent' }}</span>
            <span class="action-type tag">{{ action.action_type || action.action || action.type }}</span>
            <span class="action-content">{{ truncate(action.content || action.text || '', 80) }}</span>
            <span class="action-round">R{{ action.round }}</span>
          </div>
          <div v-if="actions.length === 0" class="empty-feed">
            <span class="muted">Waiting for actions...</span>
          </div>
        </div>
      </div>

      <!-- Twitter Panel (top right) -->
      <div class="panel twitter-panel">
        <div class="panel-header">
          <span class="panel-title platform-twitter">&#120143; Twitter</span>
          <span class="tag">{{ tweets.length }} tweets</span>
        </div>
        <div class="tweet-list">
          <div v-for="(tweet, i) in tweets.slice(0, 30)" :key="i" class="tweet-item">
            <div class="tweet-top">
              <span class="tweet-author">@{{ tweet.author || tweet.agent_name || 'unknown' }}</span>
              <span class="tweet-id">#{{ tweet.post_id }}</span>
            </div>
            <p class="tweet-text">{{ tweet.content || tweet.text }}</p>
            <div class="tweet-stats">
              <span class="tweet-stat">&#9825; {{ tweet.likes || tweet.like_count || 0 }}</span>
              <span class="tweet-stat" v-if="tweet.reposts || tweet.repost_count">
                &#8634; {{ tweet.reposts || tweet.repost_count }}
              </span>
            </div>
            <div v-if="tweet.comments && tweet.comments.length" class="comment-thread">
              <div v-for="(c, j) in tweet.comments.slice(0, 3)" :key="j" class="comment-item">
                <span class="comment-author">@{{ c.author }}</span>
                <span class="comment-text">{{ c.content }}</span>
              </div>
              <span v-if="tweet.comments.length > 3" class="comment-more">+{{ tweet.comments.length - 3 }} more</span>
            </div>
          </div>
          <div v-if="tweets.length === 0" class="empty-feed">
            <span class="muted">No tweets yet.</span>
          </div>
        </div>
      </div>

      <!-- Reddit Panel (middle right) -->
      <div class="panel reddit-panel">
        <div class="panel-header">
          <span class="panel-title platform-reddit">&#9673; Reddit</span>
          <span class="tag">{{ redditPosts.length }} posts</span>
        </div>
        <div class="reddit-list">
          <div v-for="(post, i) in redditPosts.slice(0, 20)" :key="i" class="reddit-item">
            <div class="reddit-votes">
              <span class="vote-arrow up">&#9650;</span>
              <span class="vote-score" :class="{ positive: (post.score || post.upvotes || 0) > 0 }">
                {{ post.score || post.upvotes || 0 }}
              </span>
              <span class="vote-arrow down">&#9660;</span>
            </div>
            <div class="reddit-content">
              <div class="reddit-meta">
                <span class="reddit-sub">r/{{ post.subreddit || 'simulation' }}</span>
                <span class="reddit-author">u/{{ post.author || post.agent_name || 'anon' }}</span>
                <span class="reddit-id">#{{ post.post_id }}</span>
              </div>
              <p class="reddit-title">{{ post.title || post.content || post.text }}</p>
              <p class="reddit-body" v-if="post.body">{{ truncate(post.body, 120) }}</p>
              <div v-if="post.comments && post.comments.length" class="comment-thread">
                <div v-for="(c, j) in post.comments.slice(0, 4)" :key="j" class="comment-item">
                  <span class="comment-author">u/{{ c.author }}</span>
                  <span class="comment-text">{{ c.content }}</span>
                </div>
                <span v-if="post.comments.length > 4" class="comment-more">+{{ post.comments.length - 4 }} more</span>
              </div>
            </div>
          </div>
          <div v-if="redditPosts.length === 0" class="empty-feed">
            <span class="muted">No reddit posts yet.</span>
          </div>
        </div>
      </div>

      <!-- Polymarket Panel (bottom) -->
      <div class="panel polymarket-panel">
        <div class="panel-header">
          <span class="panel-title platform-polymarket">&#9830; Polymarket</span>
          <div class="price-badges">
            <span class="price-badge yes">YES ${{ currentYesPrice.toFixed(2) }}</span>
            <span class="price-badge no">NO ${{ currentNoPrice.toFixed(2) }}</span>
          </div>
        </div>
        <div class="polymarket-body">
          <div class="chart-container" ref="chartContainer">
            <svg ref="chart"></svg>
          </div>
          <div class="leaderboard">
            <div class="leaderboard-title">Top Traders (P&amp;L)</div>
            <div
              v-for="(trader, i) in topTraders"
              :key="i"
              class="trader-row"
            >
              <span class="trader-rank">#{{ i + 1 }}</span>
              <span class="trader-name">{{ trader.name || trader.agent_name || trader.agent_id }}</span>
              <span class="trader-pnl" :class="{ positive: trader.pnl > 0, negative: trader.pnl < 0 }">
                {{ trader.pnl > 0 ? '+' : '' }}{{ (trader.pnl || 0).toFixed(2) }}
              </span>
            </div>
            <div v-if="topTraders.length === 0" class="muted" style="font-size: 12px; padding: 8px;">
              No trades yet.
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Completion toast -->
    <div v-if="runStatus === 'completed' && !dismissedOverlay" class="completion-toast" @click="dismissedOverlay = true">
      <span>Simulation complete &mdash; {{ totalRounds }} rounds executed.</span>
      <span class="toast-dismiss">click to dismiss</span>
    </div>
  </div>
</template>

<script>
import * as d3 from 'd3'
import { getRunStatus, getConfig, stopSimulation, pauseSimulation, resumeSimulation } from '../api/simulation'

export default {
  name: 'SimulationRunView',
  data() {
    return {
      config: null,
      runStatus: 'loading',
      currentRound: 0,
      totalRounds: 0,
      simulatedTime: '---',
      actions: [],
      tweets: [],
      redditPosts: [],
      priceHistory: [],
      currentYesPrice: 0.5,
      portfolios: [],
      paused: false,
      error: null,
      pollTimer: null,
      lastSeenRound: -1,
      dismissedOverlay: false,
    }
  },
  computed: {
    simId() {
      return this.$route.params.simId
    },
    roundProgress() {
      if (!this.totalRounds) return 0
      return Math.min(100, (this.currentRound / this.totalRounds) * 100)
    },
    currentNoPrice() {
      return Math.max(0, 1 - this.currentYesPrice)
    },
    isRunning() {
      return this.runStatus === 'running' || this.runStatus === 'loading'
    },
    isFinished() {
      return this.runStatus === 'completed' || this.runStatus === 'stopped'
    },
    displayActions() {
      return [...this.actions].reverse()
    },
    topTraders() {
      return [...this.portfolios]
        .sort((a, b) => (b.pnl || 0) - (a.pnl || 0))
        .slice(0, 8)
    },
  },
  async mounted() {
    await this.loadConfig()
    this.startPolling()
  },
  beforeUnmount() {
    if (this.pollTimer) clearInterval(this.pollTimer)
  },
  methods: {
    async loadConfig() {
      try {
        const res = await getConfig(this.simId)
        this.config = res.data
        this.totalRounds = this.config.num_rounds || 0
      } catch (e) {
        console.error('Failed to load config:', e)
      }
    },
    startPolling() {
      this.poll()
      this.pollTimer = setInterval(() => this.poll(), 2000)
    },
    async poll() {
      try {
        const res = await getRunStatus(this.simId)
        const data = res.data

        this.runStatus = data.status || 'running'
        if (data.status === 'paused') this.paused = true
        this.currentRound = data.rounds_completed || data.current_round || data.round || 0
        this.totalRounds = data.total_rounds || this.totalRounds
        this.simulatedTime = data.simulated_time || data.sim_time || this.formatSimTime(this.currentRound)

        // Merge new actions
        if (data.actions && data.actions.length > 0) {
          this.mergeActions(data.actions)
        }
        if (data.recent_actions && data.recent_actions.length > 0) {
          this.mergeActions(data.recent_actions)
        }

        // Update platform feeds
        if (data.twitter) {
          this.tweets = data.twitter.posts || data.twitter.tweets || this.tweets
        }
        if (data.tweets) {
          this.tweets = data.tweets
        }

        if (data.reddit) {
          this.redditPosts = data.reddit.posts || this.redditPosts
        }
        if (data.reddit_posts) {
          this.redditPosts = data.reddit_posts
        }

        if (data.polymarket) {
          const pm = data.polymarket
          if (pm.yes_price != null) {
            this.currentYesPrice = pm.yes_price
          }
          if (pm.price_history) {
            this.priceHistory = pm.price_history
          }
          if (pm.portfolios) {
            this.portfolios = pm.portfolios
          }
          if (pm.leaderboard) {
            this.portfolios = pm.leaderboard
          }
        }

        // Build price history incrementally from round data
        if (this.currentRound > this.lastSeenRound) {
          if (this.currentYesPrice != null) {
            // Avoid duplicates
            const existing = this.priceHistory.find(p => p.round === this.currentRound)
            if (!existing) {
              this.priceHistory.push({
                round: this.currentRound,
                price: this.currentYesPrice,
              })
            }
          }
          this.lastSeenRound = this.currentRound
        }

        // Extract tweets/reddit from actions if not provided separately
        const tweetActions = ['post', 'tweet', 'create_post', 'quote_post']
        const redditActions = ['post', 'create_post', 'create_comment']
        if (!data.twitter && !data.tweets) {
          this.tweets = this.actions
            .filter(a => a.platform === 'twitter' && tweetActions.includes(a.action_type || a.action))
            .map(a => ({ ...a, author: a.agent_name, text: a.content }))
            .slice(-30)
        }
        if (!data.reddit && !data.reddit_posts) {
          this.redditPosts = this.actions
            .filter(a => a.platform === 'reddit' && redditActions.includes(a.action_type || a.action))
            .map(a => ({ ...a, author: a.agent_name, title: a.content, text: a.content }))
            .slice(-20)
        }

        this.renderChart()

        // Stop polling on completion
        if (this.runStatus === 'completed' || this.runStatus === 'stopped' || this.runStatus === 'failed') {
          clearInterval(this.pollTimer)
          this.pollTimer = null
        }
      } catch (e) {
        console.error('Poll error:', e)
      }
    },
    mergeActions(newActions) {
      const existingIds = new Set(this.actions.map(a => a.action_id || `${a.round}-${a.agent_id}-${a.platform}-${a.action}-${a.timestamp || ''}`))
      for (const action of newActions) {
        const id = action.action_id || `${action.round}-${action.agent_id}-${action.platform}-${action.action}-${action.timestamp || ''}`
        if (!existingIds.has(id)) {
          this.actions.push(action)
          existingIds.add(id)
        }
      }
    },
    renderChart() {
      const container = this.$refs.chartContainer
      const svgEl = this.$refs.chart
      if (!container || !svgEl || this.priceHistory.length < 1) return

      const width = container.clientWidth || 400
      const height = container.clientHeight || 200
      const margin = { top: 12, right: 16, bottom: 28, left: 40 }
      const innerW = width - margin.left - margin.right
      const innerH = height - margin.top - margin.bottom
      if (innerW <= 0 || innerH <= 0) return

      const svg = d3.select(svgEl)
      svg.attr('viewBox', `0 0 ${width} ${height}`)
        .attr('preserveAspectRatio', 'xMidYMid meet')
      svg.selectAll('*').remove()

      const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)

      const xDomain = [0, Math.max(this.totalRounds, d3.max(this.priceHistory, d => d.round) || 1)]
      const x = d3.scaleLinear().domain(xDomain).range([0, innerW])
      const y = d3.scaleLinear().domain([0, 1]).range([innerH, 0])

      // Grid lines
      g.append('g')
        .attr('class', 'grid')
        .selectAll('line')
        .data([0.25, 0.5, 0.75])
        .enter()
        .append('line')
        .attr('x1', 0).attr('x2', innerW)
        .attr('y1', d => y(d)).attr('y2', d => y(d))
        .attr('stroke', '#333').attr('stroke-dasharray', '2,4')

      // 0.5 reference line
      g.append('line')
        .attr('x1', 0).attr('x2', innerW)
        .attr('y1', y(0.5)).attr('y2', y(0.5))
        .attr('stroke', '#555').attr('stroke-dasharray', '4,4')

      // X axis
      g.append('g')
        .attr('transform', `translate(0,${innerH})`)
        .call(d3.axisBottom(x).ticks(Math.min(10, this.totalRounds)).tickFormat(d => `R${d}`))
        .selectAll('text').attr('fill', '#666').style('font-size', '10px')
      g.selectAll('.domain, .tick line').attr('stroke', '#333')

      // Y axis
      g.append('g')
        .call(d3.axisLeft(y).ticks(5).tickFormat(d3.format('.2f')))
        .selectAll('text').attr('fill', '#666').style('font-size', '10px')
      g.selectAll('.domain, .tick line').attr('stroke', '#333')

      // Area under curve
      const area = d3.area()
        .x(d => x(d.round))
        .y0(innerH)
        .y1(d => y(d.price))
        .curve(d3.curveMonotoneX)

      g.append('path')
        .datum(this.priceHistory)
        .attr('d', area)
        .attr('fill', 'rgba(255, 107, 26, 0.08)')

      // Line
      const line = d3.line()
        .x(d => x(d.round))
        .y(d => y(d.price))
        .curve(d3.curveMonotoneX)

      g.append('path')
        .datum(this.priceHistory)
        .attr('d', line)
        .attr('fill', 'none')
        .attr('stroke', '#FF6B1A')
        .attr('stroke-width', 2)

      // Current price dot
      if (this.priceHistory.length > 0) {
        const last = this.priceHistory[this.priceHistory.length - 1]
        g.append('circle')
          .attr('cx', x(last.round))
          .attr('cy', y(last.price))
          .attr('r', 4)
          .attr('fill', '#FF6B1A')
          .attr('stroke', '#0A0A0A')
          .attr('stroke-width', 2)
      }

      // Y-axis label
      g.append('text')
        .attr('transform', 'rotate(-90)')
        .attr('x', -innerH / 2).attr('y', -30)
        .attr('fill', '#666').attr('text-anchor', 'middle')
        .style('font-size', '10px')
        .text('YES Price')
    },
    async handlePause() {
      try {
        await pauseSimulation({ simulation_id: this.simId })
        this.paused = true
      } catch (e) {
        this.error = e.response?.data?.error || 'Failed to pause simulation.'
      }
    },
    async handleResume() {
      try {
        await resumeSimulation({ simulation_id: this.simId })
        this.paused = false
      } catch (e) {
        this.error = e.response?.data?.error || 'Failed to resume simulation.'
      }
    },
    formatSimTime(round) {
      const base = new Date(2025, 0, 1, 8, 0)
      base.setMinutes(base.getMinutes() + round * 30)
      return base.toLocaleString('en-US', {
        month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    },
    platformIcon(platform) {
      const icons = { twitter: 'TW', reddit: 'RD', polymarket: 'PM' }
      return icons[platform] || platform?.substring(0, 2).toUpperCase() || '??'
    },
    truncate(text, max) {
      if (!text) return ''
      return text.length > max ? text.substring(0, max) + '...' : text
    },
  },
}
</script>

<style scoped>
.run-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--background);
  overflow: hidden;
}

/* Header */
.run-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  gap: var(--space-3);
}
.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}
.page-title {
  font-family: var(--font-display);
  color: var(--primary);
  font-size: 18px;
}
.header-center {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: 1;
  justify-content: center;
}
.time-display, .round-display {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.time-label, .round-label {
  font-size: 9px;
  color: var(--muted);
  letter-spacing: 1px;
}
.time-value {
  font-size: 14px;
  color: var(--text);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.round-value {
  font-size: 22px;
  color: var(--primary);
  font-weight: 700;
  font-family: var(--font-display);
  font-variant-numeric: tabular-nums;
}
.round-total {
  font-size: 14px;
  color: var(--muted);
}
.round-bar {
  width: 120px;
  height: 4px;
  background: var(--surface-raised);
  border-radius: 2px;
  overflow: hidden;
}
.round-bar-fill {
  height: 100%;
  background: var(--primary);
  transition: width 0.5s ease;
}
.header-right {
  flex-shrink: 0;
}

.status-loading { color: var(--muted); }
.status-running { color: var(--accent); border-color: var(--accent); animation: pulse-border 2s infinite; }
.status-completed { color: var(--primary); border-color: var(--primary); }
.status-stopped { color: var(--warning); border-color: var(--warning); }
.status-failed { color: var(--danger); border-color: var(--danger); }

.btn-danger {
  background: var(--danger);
  border-color: var(--danger);
  color: white;
  font-weight: 700;
}
.btn-danger:hover {
  background: #c53030;
  border-color: #c53030;
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

/* Main Grid */
.run-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: 1fr 1fr 1fr;
  gap: 1px;
  background: var(--border);
  overflow: hidden;
}

.panel {
  background: var(--surface);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-1) var(--space-2);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.panel-title {
  font-family: var(--font-display);
  font-size: 14px;
  color: var(--primary);
}

/* Action Feed */
.action-feed-panel {
  grid-row: 1 / 3;
}
.action-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-1);
}
.action-item {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1);
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  animation: fadeIn 0.3s ease both;
}
.action-platform {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
  flex-shrink: 0;
}
.platform-twitter { background: rgba(29, 161, 242, 0.15); color: #1DA1F2; }
.platform-reddit { background: rgba(255, 69, 0, 0.15); color: #FF4500; }
.platform-polymarket { background: rgba(67, 193, 101, 0.15); color: #43C165; }
.action-agent {
  color: var(--text);
  font-weight: 700;
  flex-shrink: 0;
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.action-type {
  flex-shrink: 0;
}
.action-content {
  color: var(--text-secondary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.action-round {
  color: var(--muted);
  font-size: 10px;
  flex-shrink: 0;
}

/* Twitter Panel */
.twitter-panel {
  grid-column: 2;
}
.platform-twitter { color: #1DA1F2; }
.tweet-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-1);
}
.tweet-item {
  padding: var(--space-1) var(--space-2);
  border-bottom: 1px solid var(--border);
}
.tweet-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2px;
}
.tweet-author {
  font-size: 12px;
  color: #1DA1F2;
  font-weight: 700;
}
.tweet-round, .tweet-id {
  font-size: 10px;
  color: var(--muted);
}
.tweet-text {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.4;
  margin-bottom: 4px;
}
.tweet-stats {
  display: flex;
  gap: var(--space-2);
}
.tweet-stat {
  font-size: 11px;
  color: var(--muted);
}
.repost-badge {
  font-size: 9px;
  color: var(--accent);
  font-weight: 700;
}

/* Reddit Panel */
.reddit-panel {
  grid-column: 2;
}
.platform-reddit { color: #FF4500; }
.reddit-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-1);
}
.reddit-item {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border-bottom: 1px solid var(--border);
}
.reddit-votes {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  flex-shrink: 0;
  min-width: 32px;
}
.vote-arrow {
  font-size: 10px;
  color: var(--muted);
  cursor: default;
}
.vote-arrow.up { color: var(--primary-dim); }
.vote-arrow.down { color: #4299E1; }
.vote-score {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
}
.vote-score.positive { color: var(--primary); }
.reddit-content {
  flex: 1;
  overflow: hidden;
}
.reddit-meta {
  display: flex;
  gap: var(--space-1);
  font-size: 10px;
  color: var(--muted);
  margin-bottom: 2px;
}
.reddit-sub { color: var(--text-secondary); font-weight: 700; }
.reddit-title {
  font-size: 12px;
  color: var(--text);
  font-weight: 700;
  line-height: 1.3;
}
.reddit-body {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}

/* Comment threads (shared by Twitter and Reddit panels) */
.comment-thread {
  margin-top: 4px;
  padding-left: 10px;
  border-left: 2px solid var(--border);
}
.comment-item {
  font-size: 11px;
  color: var(--text-secondary);
  padding: 2px 0;
  line-height: 1.3;
}
.comment-author {
  color: var(--muted);
  font-weight: 600;
  margin-right: 4px;
  font-size: 10px;
}
.comment-text {
  color: var(--text-secondary);
}
.comment-more {
  font-size: 10px;
  color: var(--muted);
  font-style: italic;
}

/* Polymarket Panel */
.polymarket-panel {
  grid-column: 1 / 3;
}
.platform-polymarket { color: var(--accent); }
.price-badges {
  display: flex;
  gap: var(--space-1);
}
.price-badge {
  font-size: 12px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 3px;
  font-variant-numeric: tabular-nums;
}
.price-badge.yes {
  background: rgba(67, 193, 101, 0.15);
  color: var(--accent);
}
.price-badge.no {
  background: rgba(229, 62, 62, 0.15);
  color: var(--danger);
}
.polymarket-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}
.chart-container {
  flex: 1;
  min-height: 0;
  max-height: 100%;
  padding: var(--space-1);
  overflow: hidden;
}
.chart-container svg {
  width: 100%;
  height: 100%;
  display: block;
}
.leaderboard {
  width: 220px;
  border-left: 1px solid var(--border);
  overflow-y: auto;
  flex-shrink: 0;
}
.leaderboard-title {
  font-size: 11px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: var(--space-1) var(--space-2);
  border-bottom: 1px solid var(--border);
}
.trader-row {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: 4px var(--space-2);
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}
.trader-rank {
  color: var(--muted);
  font-size: 10px;
  width: 20px;
  flex-shrink: 0;
}
.trader-name {
  flex: 1;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.trader-pnl {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}
.trader-pnl.positive { color: var(--accent); }
.trader-pnl.negative { color: var(--danger); }

/* Empty states */
.empty-feed {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
}
.muted { color: var(--muted); font-size: 13px; }

/* Completion overlay */
.btn-warn {
  background: var(--warning, #D69E2E);
  border-color: var(--warning, #D69E2E);
  color: var(--background);
  font-weight: 700;
}
.btn-warn:hover { opacity: 0.85; }
.btn-accent {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--background);
  font-weight: 700;
}
.btn-accent:hover { opacity: 0.85; }

.completion-toast {
  position: fixed;
  bottom: var(--space-3);
  left: 50%;
  transform: translateX(-50%);
  background: var(--surface-raised);
  border: 1px solid var(--accent);
  color: var(--accent);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  font-size: 13px;
  font-weight: 700;
  z-index: 100;
  cursor: pointer;
  display: flex;
  gap: var(--space-3);
  align-items: center;
  animation: fadeIn 0.3s ease;
}
.toast-dismiss {
  color: var(--muted);
  font-weight: 400;
  font-size: 11px;
}
</style>
