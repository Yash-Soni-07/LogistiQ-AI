import { create } from 'zustand';

interface AlertState {
  disruptions: any[];
  setDisruptions: (disruptions: any[]) => void;
}

export const useAlertStore = create<AlertState>((set) => ({
  disruptions: [],
  setDisruptions: (disruptions) => set({ disruptions }),
}));
