import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  tenant_id: string;
}

interface AuthState {
  user: User | null;
  token: string | null;
  tenant: { id: string } | null;
  login: (token: string, user: User) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      token: null,
      tenant: null,
      login: (token, user) => set({ token, user, tenant: { id: user.tenant_id } }),
      logout: () => {
        // Only clear state, api interceptors or components will handle redirects
        set({ token: null, user: null, tenant: null });
        // Clean up token from local storage or anywhere else if needed
      },
    }),
    { 
      name: 'auth-storage',
      partialize: (state) => ({ token: state.token, user: state.user, tenant: state.tenant }),
    }
  )
);
