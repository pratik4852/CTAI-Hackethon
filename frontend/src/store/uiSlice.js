import { createSlice } from '@reduxjs/toolkit'

const persisted = (key, fallback) => {
  try {
    const v = localStorage.getItem(key)
    return v === null ? fallback : JSON.parse(v)
  } catch {
    return fallback
  }
}

const initialState = {
  projectId: persisted('mepiq.projectId', null),
  documentId: persisted('mepiq.documentId', null),
  page: 1,
  jobId: null,
  jobProgress: null,
  theme: persisted('mepiq.theme', 'dark'),
  toast: null,
}

const uiSlice = createSlice({
  name: 'ui',
  initialState,
  reducers: {
    setProject(state, { payload }) {
      state.projectId = payload
      state.documentId = null
      state.page = 1
      try {
        localStorage.setItem('mepiq.projectId', JSON.stringify(payload))
        localStorage.removeItem('mepiq.documentId')
      } catch {}
    },
    setDocument(state, { payload }) {
      state.documentId = payload
      state.page = 1
      try {
        localStorage.setItem('mepiq.documentId', JSON.stringify(payload))
      } catch {}
    },
    setPage(state, { payload }) {
      state.page = payload
    },
    setJob(state, { payload }) {
      state.jobId = payload
      state.jobProgress = null
    },
    setJobProgress(state, { payload }) {
      state.jobProgress = payload
    },
    toggleTheme(state) {
      state.theme = state.theme === 'dark' ? 'light' : 'dark'
      try {
        localStorage.setItem('mepiq.theme', JSON.stringify(state.theme))
      } catch {}
    },
    toast(state, { payload }) {
      state.toast = payload ? { ...payload, at: Date.now() } : null
    },
  },
})

export const { setProject, setDocument, setPage, setJob, setJobProgress, toggleTheme, toast } =
  uiSlice.actions
export default uiSlice.reducer
