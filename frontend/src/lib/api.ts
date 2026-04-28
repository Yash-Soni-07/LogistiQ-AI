import axios, { type AxiosError } from 'axios';
import { QueryClient } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/auth.store';

// ---------------------------------------------------------------------------
// Axios instance
// ---------------------------------------------------------------------------

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1',
  headers: { 'Content-Type': 'application/json' },
  timeout: 15_000,
});

// Request — inject auth headers
apiClient.interceptors.request.use((config) => {
  const { token, tenant } = useAuthStore.getState();
  if (token) {
    config.headers['Authorization'] = `Bearer ${token}`;
  }
  if (tenant?.id) {
    config.headers['X-Tenant-ID'] = tenant.id;
  }
  return config;
});

// Response — handle 401 globally
apiClient.interceptors.response.use(
  (res) => res,
  (err: AxiosError) => {
    if (err.response?.status === 401) {
      useAuthStore.getState().logout();
      // Hard redirect — avoids circular React Router dependency
      window.location.replace('/login');
    }
    return Promise.reject(err);
  },
);

// ---------------------------------------------------------------------------
// TanStack Query client
// ---------------------------------------------------------------------------

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});
