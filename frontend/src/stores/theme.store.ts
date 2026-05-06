import { create } from 'zustand';

interface ThemeState {
  isDark: boolean;
  setDark: (v: boolean) => void;
}

/**
 * Tiny reactive theme store.
 * ThemeToggle writes isDark; FreightMap reads it to pick map tile style.
 * Initialized from the <html class="dark"> applied by index.html inline script.
 */
export const useThemeStore = create<ThemeState>(() => ({
  isDark: document.documentElement.classList.contains('dark'),
  setDark: (v: boolean) => {
    useThemeStore.setState({ isDark: v });
  },
}));
