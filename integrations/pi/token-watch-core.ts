/** Context-threshold crossing logic for Pi's CCCP token watch. */
export const DEFAULT_THRESHOLDS = [50, 75, 90, 95];

export class TokenWatch {
  private readonly thresholds: number[];
  private fired = new Set<number>();

  constructor(thresholds: number[] = DEFAULT_THRESHOLDS) {
    this.thresholds = normalizeThresholds(thresholds);
  }

  /** Re-arm every threshold after compaction creates a new context climb. */
  reset(): void {
    this.fired.clear();
  }

  armed(): number[] {
    return [...this.thresholds];
  }

  /** Establish a starting point without reporting thresholds already passed. */
  prime(percent: number | null): void {
    if (percent === null || !Number.isFinite(percent) || percent < 0) return;
    for (const threshold of this.thresholds) {
      if (percent >= threshold) this.fired.add(threshold);
    }
  }

  /** Return the thresholds newly reached by this usage percentage. */
  crossed(percent: number | null): number[] {
    if (percent === null || !Number.isFinite(percent) || percent < 0) return [];
    const crossed: number[] = [];
    for (const threshold of this.thresholds) {
      if (percent >= threshold && !this.fired.has(threshold)) {
        this.fired.add(threshold);
        crossed.push(threshold);
      }
    }
    return crossed;
  }
}

export function normalizeThresholds(thresholds: number[]): number[] {
  return [...new Set(thresholds.filter((n) => Number.isFinite(n) && n > 0 && n <= 100))]
    .sort((a, b) => a - b);
}
