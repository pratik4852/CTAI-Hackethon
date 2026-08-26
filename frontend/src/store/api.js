import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react'

export const API_BASE = import.meta.env.VITE_API_BASE || ''

export const api = createApi({
  reducerPath: 'api',
  baseQuery: fetchBaseQuery({ baseUrl: `${API_BASE}/api` }),
  tagTypes: ['Project', 'Result', 'Library', 'Chat', 'Reviews'],
  endpoints: (b) => ({
    health: b.query({ query: () => '/health' }),
    catalogue: b.query({ query: () => '/catalogue' }),

    projects: b.query({
      query: () => '/projects',
      transformResponse: (r) => r.projects,
      providesTags: ['Project'],
    }),
    project: b.query({
      query: (id) => `/projects/${id}`,
      providesTags: ['Project'],
    }),
    createProject: b.mutation({
      query: (body) => ({ url: '/projects', method: 'POST', body }),
      invalidatesTags: ['Project'],
    }),
    deleteProject: b.mutation({
      query: (id) => ({ url: `/projects/${id}`, method: 'DELETE' }),
      invalidatesTags: ['Project'],
    }),
    uploadDocuments: b.mutation({
      query: ({ projectId, files }) => {
        const form = new FormData()
        for (const f of files) form.append('files', f)
        return { url: `/projects/${projectId}/documents`, method: 'POST', body: form }
      },
      invalidatesTags: ['Project'],
    }),

    analyse: b.mutation({
      query: ({ projectId, ...body }) => ({
        url: `/projects/${projectId}/analyse`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['Project'],
    }),
    job: b.query({ query: (id) => `/jobs/${id}` }),

    result: b.query({
      query: (documentId) => `/documents/${documentId}/result`,
      providesTags: ['Result'],
    }),
    resultFull: b.query({
      query: (documentId) => `/documents/${documentId}/result/full`,
      providesTags: ['Result'],
    }),
    sheet: b.query({
      query: ({ documentId, page }) => `/documents/${documentId}/result?sheet=${page}`,
      providesTags: ['Result'],
    }),

    visualSearch: b.mutation({
      query: (body) => ({ url: '/visual-search', method: 'POST', body }),
    }),
    review: b.mutation({
      query: ({ projectId, ...body }) => ({
        url: `/projects/${projectId}/review`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['Result', 'Reviews'],
    }),
    calibrate: b.mutation({
      query: ({ projectId, ...body }) => ({
        url: `/projects/${projectId}/calibrate`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['Result'],
    }),

    library: b.query({ query: () => '/library', providesTags: ['Library'] }),
    learnGlyph: b.mutation({
      query: (body) => ({ url: '/library', method: 'POST', body }),
      invalidatesTags: ['Library', 'Result'],
    }),
    forgetGlyph: b.mutation({
      query: (id) => ({ url: `/library/${id}`, method: 'DELETE' }),
      invalidatesTags: ['Library'],
    }),

    chatHistory: b.query({
      query: (projectId) => `/projects/${projectId}/chat`,
      providesTags: ['Chat'],
    }),
    sendChat: b.mutation({
      query: ({ projectId, ...body }) => ({
        url: `/projects/${projectId}/chat`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['Chat'],
    }),
    clearChat: b.mutation({
      query: (projectId) => ({ url: `/projects/${projectId}/chat`, method: 'DELETE' }),
      invalidatesTags: ['Chat'],
    }),

    exportsList: b.query({ query: (documentId) => `/documents/${documentId}/exports` }),
  }),
})

export const {
  useHealthQuery,
  useCatalogueQuery,
  useProjectsQuery,
  useProjectQuery,
  useCreateProjectMutation,
  useDeleteProjectMutation,
  useUploadDocumentsMutation,
  useAnalyseMutation,
  useJobQuery,
  useResultQuery,
  useResultFullQuery,
  useSheetQuery,
  useVisualSearchMutation,
  useReviewMutation,
  useCalibrateMutation,
  useLibraryQuery,
  useLearnGlyphMutation,
  useForgetGlyphMutation,
  useChatHistoryQuery,
  useSendChatMutation,
  useClearChatMutation,
  useExportsListQuery,
} = api

export const pageImageUrl = (documentId, page, dpi = 130) =>
  `${API_BASE}/api/documents/${documentId}/page/${page}/image?dpi=${dpi}`

export const cropUrl = (documentId, page, bbox, dpi = 300) => {
  const [x0, y0, x1, y1] = bbox
  return `${API_BASE}/api/documents/${documentId}/page/${page}/crop?x0=${x0}&y0=${y0}&x1=${x1}&y1=${y1}&dpi=${dpi}`
}

export const exportUrl = (documentId, kind) =>
  `${API_BASE}/api/documents/${documentId}/export/${kind}`
