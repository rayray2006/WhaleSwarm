<template>
  <div id="whale-app">
    <router-view />
    <div class="bottom-stripe"></div>
  </div>
</template>

<script>
export default {
  name: 'App',
}
</script>

<style>
/* === Hyperstitions v2.0 Design System === */
:root {
  --primary: #FF6B1A;
  --primary-dim: #cc5514;
  --accent: #43C165;
  --accent-dim: #2d8a47;
  --background: #0A0A0A;
  --surface: #141414;
  --surface-raised: #1E1E1E;
  --surface-overlay: #282828;
  --text: #FAFAFA;
  --text-secondary: #BBBBBB;
  --muted: #666666;
  --border: #333333;
  --danger: #E53E3E;
  --warning: #ECC94B;

  /* Spacing scale (1.4x modular) */
  --space-1: 6px;
  --space-2: 11px;
  --space-3: 22px;
  --space-4: 34px;
  --space-5: 56px;
  --space-6: 84px;

  /* Typography */
  --font-display: 'Young Serif', serif;
  --font-mono: 'Space Mono', monospace;
  --font-body: 'Space Mono', monospace;

  /* Radius */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: var(--font-body);
  background: var(--background);
  color: var(--text);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

#whale-app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

/* Scrollbar */
::-webkit-scrollbar {
  width: 6px;
}
::-webkit-scrollbar-track {
  background: var(--background);
}
::-webkit-scrollbar-thumb {
  background: var(--muted);
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: var(--primary);
}

/* Animations */
@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

@keyframes pulse-border {
  0%, 100% { border-color: var(--primary); }
  50% { border-color: var(--primary-dim); }
}

@keyframes scan {
  0% { top: 0; }
  100% { top: 100%; }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Utility classes */
.warning-stripes {
  height: 3px;
  background: var(--primary);
  opacity: 0.3;
  flex-shrink: 0;
}
.bottom-stripe {
  height: 3px;
  background: var(--primary);
  opacity: 0.3;
  flex-shrink: 0;
}

.btn {
  font-family: var(--font-mono);
  font-size: 13px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.2s ease;
  background: var(--surface);
  color: var(--text);
}

.btn:hover {
  border-color: var(--primary);
  background: var(--surface-raised);
}

.btn-primary {
  background: var(--primary);
  border-color: var(--primary);
  color: var(--background);
  font-weight: 700;
}

.btn-primary:hover {
  background: var(--primary-dim);
  border-color: var(--primary-dim);
}

.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-3);
}

.card-header {
  font-family: var(--font-display);
  font-size: 18px;
  color: var(--primary);
  margin-bottom: var(--space-2);
}

input, textarea, select {
  font-family: var(--font-mono);
  font-size: 13px;
  background: var(--surface-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  padding: var(--space-2);
  width: 100%;
  transition: border-color 0.2s;
}

input:focus, textarea:focus, select:focus {
  outline: none;
  border-color: var(--primary);
}

.loading-shimmer {
  background: linear-gradient(
    90deg,
    var(--surface) 25%,
    var(--surface-raised) 50%,
    var(--surface) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
}

.tag {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 3px;
  background: var(--surface-raised);
  border: 1px solid var(--border);
  color: var(--text-secondary);
}
</style>
