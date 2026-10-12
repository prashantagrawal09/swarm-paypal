/** Geometry for the swarm map: projection, pin de-overlap and flight paths. Pure. */

export const W = 720;
export const H = 500;
/** Room above the estate for the suppliers' depots. */
export const BAND = 56;
export const PAD = 54;
export const PIN = 15;

/** The estate's bounding box (a little wider than the shops). */
export const BOUNDS = { south: 1.2826, north: 1.2866, west: 103.8284, east: 103.8342 };

export function project(lat: number, lng: number): [number, number] {
  const x = PAD + ((lng - BOUNDS.west) / (BOUNDS.east - BOUNDS.west)) * (W - PAD * 2);
  const y =
    BAND + PAD + ((BOUNDS.north - lat) / (BOUNDS.north - BOUNDS.south)) * (H - BAND - PAD * 2 - 4);
  return [x, y];
}

/** Nudges pins that would overlap (the market stalls share a building). Deterministic. */
export function relax(points: { code: string; x: number; y: number }[], gap = PIN * 2 + 4) {
  const out = points.map((p) => ({ ...p }));
  for (let pass = 0; pass < 40; pass++) {
    for (let i = 0; i < out.length; i++) {
      for (let j = i + 1; j < out.length; j++) {
        const dx = out[j].x - out[i].x;
        const dy = out[j].y - out[i].y;
        const d = Math.hypot(dx, dy) || 0.01;
        if (d < gap) {
          const push = (gap - d) / 2;
          const ux = dx / d;
          const uy = dy / d;
          out[i].x -= ux * push;
          out[i].y -= uy * push;
          out[j].x += ux * push;
          out[j].y += uy * push;
        }
      }
    }
  }
  return Object.fromEntries(out.map((p) => [p.code, [p.x, p.y] as [number, number]]));
}

/** A gently curved path between two points (bowing to the left of travel). */
export function curve(from: [number, number], to: [number, number], bow = 0.14): string {
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  const mx = (from[0] + to[0]) / 2 - dy * bow;
  const my = (from[1] + to[1]) / 2 + dx * bow;
  return `M${from[0].toFixed(1)},${from[1].toFixed(1)} Q${mx.toFixed(1)},${my.toFixed(1)} ${to[0].toFixed(1)},${to[1].toFixed(1)}`;
}
