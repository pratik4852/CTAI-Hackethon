import React from 'react'
import ReactDOM from 'react-dom/client'
import { Provider } from 'react-redux'
import { HashRouter } from 'react-router-dom'
import { store } from './store'
import App from './App'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Provider store={store}>
      {/* Hash routing keeps the SPA working on any static host without
          server-side rewrite rules. */}
      <HashRouter>
        <App />
      </HashRouter>
    </Provider>
  </React.StrictMode>
)
