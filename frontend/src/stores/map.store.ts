import { create } from 'zustand';

interface MapState {
  viewport: { longitude: number; latitude: number; zoom: number; pitch: number; bearing: number };
  setViewport: (vp: any) => void;
}

export const useMapStore = create<MapState>((set) => ({
  viewport: { longitude: 0, latitude: 0, zoom: 2, pitch: 0, bearing: 0 },
  setViewport: (viewport) => set({ viewport }),
}));
