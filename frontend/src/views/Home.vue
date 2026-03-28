<template>
  <div class="home">
    <div class="warning-stripes"></div>
    <div class="hero">
      <h1 class="title">WHALESWARM</h1>
      <p class="subtitle">Universal Swarm Intelligence Engine</p>
      <p class="description">
        Upload documents. Build knowledge graphs. Run multi-platform simulations
        with AI agents across Twitter, Reddit, and Polymarket.
      </p>

      <div class="upload-section card">
        <div class="card-header">NEW SIMULATION</div>

        <div class="form-group">
          <label>Documents (PDF / MD / TXT)</label>
          <div
            class="dropzone"
            :class="{ active: isDragging }"
            @dragover.prevent="isDragging = true"
            @dragleave="isDragging = false"
            @drop.prevent="handleDrop"
            @click="$refs.fileInput.click()"
          >
            <input
              ref="fileInput"
              type="file"
              multiple
              accept=".pdf,.md,.txt"
              @change="handleFileSelect"
              style="display: none"
            />
            <div v-if="files.length === 0">
              Drop files here or click to browse
            </div>
            <div v-else class="file-list">
              <div v-for="(file, i) in files" :key="i" class="file-item">
                {{ file.name }}
                <span class="file-size">({{ formatSize(file.size) }})</span>
                <span class="remove" @click.stop="removeFile(i)">&times;</span>
              </div>
            </div>
          </div>
        </div>

        <div class="form-group">
          <label>Simulation Requirement</label>
          <textarea
            v-model="simulationRequirement"
            rows="3"
            placeholder="e.g., Simulate public reaction to a proposed AI regulation bill..."
          ></textarea>
        </div>

        <div class="form-group">
          <label>Project Name (optional)</label>
          <input v-model="projectName" placeholder="My Project" />
        </div>

        <button
          class="btn btn-primary"
          :disabled="files.length === 0 || !simulationRequirement || loading"
          @click="startProject"
        >
          {{ loading ? 'Processing...' : 'Generate Ontology' }}
        </button>

        <div v-if="error" class="error-msg">{{ error }}</div>
      </div>
    </div>
    <div class="warning-stripes"></div>
  </div>
</template>

<script>
import { generateOntology } from '../api/graph'

export default {
  name: 'Home',
  data() {
    return {
      files: [],
      simulationRequirement: '',
      projectName: '',
      isDragging: false,
      loading: false,
      error: null,
    }
  },
  methods: {
    handleFileSelect(e) {
      this.files.push(...Array.from(e.target.files))
    },
    handleDrop(e) {
      this.isDragging = false
      this.files.push(...Array.from(e.dataTransfer.files))
    },
    removeFile(i) {
      this.files.splice(i, 1)
    },
    formatSize(bytes) {
      if (bytes < 1024) return bytes + ' B'
      if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB'
      return (bytes / 1048576).toFixed(1) + ' MB'
    },
    async startProject() {
      this.loading = true
      this.error = null
      try {
        const formData = new FormData()
        this.files.forEach(f => formData.append('files', f))
        formData.append('simulation_requirement', this.simulationRequirement)
        if (this.projectName) formData.append('project_name', this.projectName)

        const res = await generateOntology(formData)
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
  justify-content: center;
  padding: var(--space-5);
  gap: var(--space-4);
}

.title {
  font-family: var(--font-display);
  font-size: 56px;
  color: var(--primary);
  letter-spacing: 4px;
}

.subtitle {
  font-size: 14px;
  color: var(--muted);
  letter-spacing: 2px;
  text-transform: uppercase;
}

.description {
  max-width: 600px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 13px;
}

.upload-section {
  width: 100%;
  max-width: 600px;
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

.dropzone {
  border: 2px dashed var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  text-align: center;
  color: var(--muted);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.dropzone:hover,
.dropzone.active {
  border-color: var(--primary);
  color: var(--text);
}

.file-list {
  text-align: left;
}

.file-item {
  padding: var(--space-1) 0;
  font-size: 12px;
  color: var(--text);
}

.file-size {
  color: var(--muted);
}

.remove {
  color: var(--danger);
  cursor: pointer;
  margin-left: var(--space-1);
}

.error-msg {
  margin-top: var(--space-2);
  color: var(--danger);
  font-size: 12px;
}
</style>
