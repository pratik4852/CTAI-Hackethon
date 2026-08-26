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
  // Centre of the canvas in screen px, so zoom actions keep it fixed.
  viewportCentre: { x: 0, y: 0 },
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
    /**
     * Zoom to a given scale about the centre of the current view.
     *
     * Used to lift the user out of a fit-to-page view, where a symbol is barely
     * a pixel wide and no drag can select one.
     */
    zoomTo(state, { payload }) {
      const { scale: from, x, y } = state.transform
      const to = payload
      if (!from || !to) return
      // Keep whatever is at the centre of the viewport at the centre.
      const k = to / from
      state.transform = {
        scale: to,
        x: x * k + (1 - k) * (state.viewportCentre?.x ?? 0),
        y: y * k + (1 - k) * (state.viewportCentre?.y ?? 0),
      }
    },
    setViewportCentre(state, { payload }) {
      state.viewportCentre = payload
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
  zoomTo,
  setViewportCentre,
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
