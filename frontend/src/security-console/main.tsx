import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/manrope';
import { SecurityConsole } from './SecurityConsole';
import '../styles/index.css';
import './security-console.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <SecurityConsole />
  </StrictMode>,
);
