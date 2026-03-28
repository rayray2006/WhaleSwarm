<template>
  <div class="interaction-view">
    <div class="warning-stripes"></div>

    <div class="toolbar">
      <div class="toolbar-left">
        <button class="btn" @click="$router.push(`/report/${reportId}`)">&#8592; REPORT</button>
        <h2 class="page-title">Agent Interview</h2>
      </div>
    </div>

    <div class="chat-layout">
      <!-- Chat messages -->
      <div class="chat-messages" ref="messages">
        <div class="system-msg">
          <p>You can ask questions about the simulation, interview specific agents, or explore the knowledge graph. The report agent has access to all simulation data.</p>
        </div>

        <div
          v-for="(msg, i) in messages"
          :key="i"
          class="message"
          :class="msg.role"
        >
          <div class="message-header">
            <span class="message-role">{{ msg.role === 'user' ? 'You' : 'Report Agent' }}</span>
          </div>
          <div class="message-body" v-html="renderMessage(msg.content)"></div>
        </div>

        <div v-if="loading" class="message assistant">
          <div class="message-header">
            <span class="message-role">Report Agent</span>
          </div>
          <div class="message-body">
            <span class="thinking">Thinking...</span>
          </div>
        </div>
      </div>

      <!-- Input -->
      <div class="chat-input">
        <textarea
          v-model="input"
          placeholder="Ask about the simulation, interview an agent, or explore the graph..."
          rows="2"
          @keydown.enter.exact.prevent="send"
          :disabled="loading"
        ></textarea>
        <button
          class="btn btn-primary send-btn"
          :disabled="!input.trim() || loading"
          @click="send"
        >SEND</button>
      </div>
    </div>
  </div>
</template>

<script>
import { marked } from 'marked'
import { conversation } from '../api/report'

export default {
  name: 'InteractionView',
  data() {
    return {
      messages: [],
      input: '',
      loading: false,
      conversationId: null,
    }
  },
  computed: {
    reportId() {
      return this.$route.params.reportId
    },
  },
  methods: {
    renderMessage(content) {
      return marked(content || '')
    },
    async send() {
      const question = this.input.trim()
      if (!question) return

      this.messages.push({ role: 'user', content: question })
      this.input = ''
      this.loading = true

      this.$nextTick(() => {
        const el = this.$refs.messages
        if (el) el.scrollTop = el.scrollHeight
      })

      try {
        const res = await conversation(this.reportId, {
          question,
          conversation_id: this.conversationId,
        })
        this.conversationId = res.data.conversation_id || this.conversationId
        this.messages.push({ role: 'assistant', content: res.data.response })
      } catch (e) {
        this.messages.push({
          role: 'assistant',
          content: `Error: ${e.response?.data?.error || e.message}`,
        })
      } finally {
        this.loading = false
        this.$nextTick(() => {
          const el = this.$refs.messages
          if (el) el.scrollTop = el.scrollHeight
        })
      }
    },
  },
}
</script>

<style scoped>
.interaction-view { min-height: 100vh; display: flex; flex-direction: column; }
.toolbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border);
}
.toolbar-left { display: flex; align-items: center; gap: var(--space-2); }
.page-title { font-family: var(--font-display); color: var(--primary); font-size: 18px; }

.chat-layout { flex: 1; display: flex; flex-direction: column; max-width: 900px; margin: 0 auto; width: 100%; }

.chat-messages {
  flex: 1; overflow-y: auto; padding: var(--space-3);
  display: flex; flex-direction: column; gap: var(--space-2);
}

.system-msg {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: var(--space-2);
  color: var(--muted); font-size: 13px; line-height: 1.5;
}

.message {
  border-radius: var(--radius-md); padding: var(--space-2);
  animation: fadeIn 0.3s ease;
}
.message.user {
  background: var(--surface-raised); border: 1px solid var(--border);
  align-self: flex-end; max-width: 80%;
}
.message.assistant {
  background: var(--surface); border: 1px solid var(--border);
  align-self: flex-start; max-width: 90%;
}

.message-header { margin-bottom: var(--space-1); }
.message-role { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }
.message.assistant .message-role { color: var(--primary); }

.message-body { font-size: 14px; line-height: 1.6; }
.message-body :deep(p) { margin-bottom: var(--space-1); }
.message-body :deep(code) { background: var(--surface-overlay); padding: 2px 4px; border-radius: 3px; font-size: 12px; }
.message-body :deep(blockquote) { border-left: 2px solid var(--primary); padding-left: var(--space-2); color: var(--text-secondary); }

.thinking {
  color: var(--muted); font-style: italic;
  animation: pulse-border 1.5s infinite;
}

.chat-input {
  display: flex; gap: var(--space-2); padding: var(--space-2) var(--space-3);
  border-top: 1px solid var(--border); background: var(--surface);
}
.chat-input textarea { flex: 1; resize: none; }
.send-btn { align-self: flex-end; }
</style>
