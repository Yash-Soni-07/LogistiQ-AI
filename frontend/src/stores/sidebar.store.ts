import { create } from 'zustand';

interface SidebarState {
  expanded: boolean;
  toggle: () => void;
  setExpanded: (expanded: boolean) => void;
}

export const useSidebarStore = create<SidebarState>((set) => ({
  expanded: true,
  toggle: () => set((state) => ({ expanded: !state.expanded })),
  setExpanded: (expanded) => set({ expanded }),
}));
