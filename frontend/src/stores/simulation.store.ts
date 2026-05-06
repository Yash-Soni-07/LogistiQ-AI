import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type VisibleMode = 'road' | 'air' | 'sea' | 'rail' | 'multimodal';

const ALL_MODES: VisibleMode[] = ['road', 'air', 'sea', 'rail', 'multimodal'];

interface SimulationSettingsState {
  /** Transport modes rendered on the map */
  visibleModes: VisibleMode[];
  setVisibleModes: (modes: VisibleMode[]) => void;
  /** Speed multiplier for running simulation (50–2000) */
  speedMultiplier: number;
  setSpeedMultiplier: (n: number) => void;
}

export const useSimulationStore = create<SimulationSettingsState>()(
  persist(
    (set) => ({
      visibleModes: [...ALL_MODES],
      setVisibleModes: (modes) => set({ visibleModes: modes }),
      speedMultiplier: 100,
      setSpeedMultiplier: (n) => set({ speedMultiplier: n }),
    }),
    {
      name: 'lq-simulation-settings',
      version: 3,
    },
  ),
);

export { ALL_MODES };
