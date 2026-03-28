import { reactive } from 'vue'

export const pendingUpload = reactive({
  files: [],
  simulationRequirement: '',
  projectName: '',
  additionalContext: '',
})
