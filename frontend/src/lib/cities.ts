export type CoordinatePair = [longitude: number, latitude: number];

export const INDIAN_CITY_COORDS: Record<string, CoordinatePair> = {
  mumbai: [72.8777, 19.0760],
  delhi: [77.1025, 28.7041],
  "new delhi": [77.1025, 28.7041],
  bangalore: [77.5858, 12.9716],
  bengaluru: [77.5858, 12.9716],
  hyderabad: [78.4867, 17.3850],
  chennai: [80.2707, 13.0827],
  kolkata: [88.3639, 22.5726],
  ahmedabad: [72.5713, 23.0225],
  pune: [73.8567, 18.5204],
  surat: [72.8777, 21.1702],
  jaipur: [75.7139, 26.9124],
  lucknow: [80.9462, 26.8467],
  kanpur: [80.3318, 26.4499],
  nagpur: [79.0882, 21.1458],
  indore: [75.8577, 22.7196],
  thane: [72.9780, 19.2183],
  bhopal: [77.4120, 23.2599],
  visakhapatnam: [83.2185, 17.6868],
  "pimpri-chinchwad": [73.7949, 18.6332],
  patna: [85.1376, 25.5941],
  vadodara: [73.1812, 22.3072],
};

export function normalizeCityName(rawCity: string): string {
  return rawCity.toLowerCase().replace(/,/g, " ").replace(/\s+/g, " ").trim();
}

export function resolveCityCoords(city: string): CoordinatePair {
  const normalized = normalizeCityName(city);
  if (INDIAN_CITY_COORDS[normalized]) {
    return INDIAN_CITY_COORDS[normalized];
  }

  if (normalized.startsWith("new ")) {
    const stripped = normalized.replace(/^new\s+/, "");
    if (INDIAN_CITY_COORDS[stripped]) {
      return INDIAN_CITY_COORDS[stripped];
    }
  }

  return [78.9629, 20.5937];
}
