import { create } from 'zustand';

interface ShipmentState {
  selectedId: string | null;
  setSelectedId: (id: string | null) => void;
}

export const useShipmentStore = create<ShipmentState>((set) => ({
  selectedId: null,
  setSelectedId: (selectedId) => set({ selectedId }),
}));
