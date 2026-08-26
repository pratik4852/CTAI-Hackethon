import { createSlice } from '@reduxjs/toolkit'

const initialState = {
  // What is drawn on top of the sheet.
  layers: {
    detections: true,
    runs: true,
    findings: true,
    clashes: true,
    matches: true,
  },
  // Pointer mode: pan | select (marquee -> visual search) | calibrate
  mode: 'pan',
  transform: { scale: 1, x: 0, y: 0 },
  selection: null, // { x0, y0, x1, y1 } in PDF points
  calibration: { p1: null, p2: null },
  selectedDetection: null,
  selectedRun: null,
  focus: null, // bbox in points to fly to
  categoryFilter: [],
  minConfidence: 0,
  searchResult: null,
}

const viewerSlice = createSlice({
  name: 'viewer',
  initialState,
  reducers: {
    toggleLayer(state, { payload }) {
      state.layers[payload] = !state.layers[payload]
    },
    setMode(state, { payload }) {
      state.mode = payload
      state.selection = null
      if (payload !== 'calibrate') state.calibration = { p1: null, p2: null }
    },
    setTransform(state, { payload }) {
      state.transform = payload
    },
    setSelection(state, { payload }) {
      state.selection = payload
    },
    setCalibrationPoint(state, { payload }) {
      if (!state.calibration.p1 || state.calibration.p2) {
        state.calibration = { p1: payload, p2: null }
      } else {
        state.calibration = { ...state.calibration, p2: payload }
      }
    },
    resetCalibration(state) {
      state.calibration = { p1: null, p2: null }
    },
    selectDetection(state, { payload }) {
      state.selectedDetection = payload
      state.selectedRun = null
    },
    selectRun(state, { payload }) {
      state.selectedRun = payload
      state.selectedDetection = null
    },
    focusOn(state, { payload }) {
      state.focus = payload ? { bbox: payload, at: Date.now() } : null
    },
    setCategoryFilter(state, { payload }) {
      state.categoryFilter = payload
    },
    setMinConfidence(state, { payload }) {
      state.minConfidence = payload
    },
    setSearchResult(state, { payload }) {
      state.searchResult = payload
    },
    resetViewer(state) {
      state.transform = { scale: 1, x: 0, y: 0 }
      state.selection = null
      state.selectedDetection = null
      state.selectedRun = null
      state.searchResult = null
    },
  },
})

export const {
  toggleLayer,
  setMode,
  setTransform,
  setSelection,
  setCalibrationPoint,
  resetCalibration,
  selectDetection,
  selectRun,
  focusOn,
  setCategoryFilter,
  setMinConfidence,
  setSearchResult,
  resetViewer,
} = viewerSlice.actions
export default viewerSlice.reducer
