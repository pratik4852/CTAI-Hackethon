import { configureStore } from '@reduxjs/toolkit'
import { setupListeners } from '@reduxjs/toolkit/query'
import { api } from './api'
import ui from './uiSlice'
import viewer from './viewerSlice'

export const store = configureStore({
  reducer: {
    [api.reducerPath]: api.reducer,
    ui,
    viewer,
  },
  middleware: (getDefault) =>
    getDefault({ serializableCheck: false }).concat(api.middleware),
})

setupListeners(store.dispatch)
