import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { GoogleOAuthProvider } from '@react-oauth/google';
import { queryClient } from '@/lib/api';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Toaster } from '@/components/ui/sonner';
import App from './App.tsx';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <GoogleOAuthProvider clientId={import.meta.env.VITE_GOOGLE_CLIENT_ID as string}>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <App />
          <Toaster position="top-right" />
        </TooltipProvider>
      </QueryClientProvider>
    </GoogleOAuthProvider>
  </StrictMode>,
);
