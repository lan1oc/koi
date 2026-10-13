import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { initializeRetestSessionStore } from './modules/ai-testing/retestSessionStore';
import './styles/theme.css';
import './styles/app-shell.css';

void initializeRetestSessionStore().finally(() => createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
));
