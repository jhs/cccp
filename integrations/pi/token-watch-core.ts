/** Context-threshold crossing logic for Pi's CCCP token watch. */

/** A breakpoint: the usage percentage that trips it, and the note played back when it does. */
export type Threshold = { percent: number; reminder?: string };

export const DEFAULT_THRESHOLDS = [50, 75, 90, 95];

export class TokenWatch {
  private readonly thresholds: Threshold[];
  private fired = new Set<number>();

  constructor(thresholds: Threshold[] = DEFAULT_THRESHOLDS.map((percent) => ({ percent }))) {
    this.thresholds = normalizeThresholds(thresholds);
  }

  /** Re-arm every threshold after compaction creates a new context climb. */
  reset(): void {
    this.fired.clear();
  }

  armed(): number[] {
    return this.thresholds.map((threshold) => threshold.percent);
  }

  /** Establish a starting point without reporting thresholds already passed, and name the ones skipped. */
  prime(percent: number | null): number[] {
    if (percent === null || !Number.isFinite(percent) || percent < 0) return [];
    const passed: number[] = [];
    for (const { percent: threshold } of this.thresholds) {
      if (percent >= threshold) {
        this.fired.add(threshold);
        passed.push(threshold);
      }
    }
    return passed;
  }

  /** Return the thresholds newly reached by this usage percentage. */
  crossed(percent: number | null): Threshold[] {
    if (percent === null || !Number.isFinite(percent) || percent < 0) return [];
    const crossed: Threshold[] = [];
    for (const threshold of this.thresholds) {
      if (percent >= threshold.percent && !this.fired.has(threshold.percent)) {
        this.fired.add(threshold.percent);
        crossed.push(threshold);
      }
    }
    return crossed;
  }
}

/**
 * Thresholds in crossing order, or a throw.
 *
 * Nothing is quietly dropped or deduplicated here, which is a change of heart now that a threshold can carry a
 * reminder: collapsing a repeated percentage discards whichever reminder lost, and a discarded reminder does not
 * go wrong until the crossing it was meant to speak at, hours later. Throwing costs the caller one corrected call.
 * `bin/claude-tokens` refuses the same input for the same reason.
 */
export function normalizeThresholds(thresholds: Threshold[]): Threshold[] {
  const seen = new Set<number>();
  for (const { percent } of thresholds) {
    if (!Number.isFinite(percent) || percent <= 0 || percent > 100) throw new Error(`Threshold percent must be over 0 and at most 100: ${percent}`);
    if (seen.has(percent)) throw new Error(`Threshold percent given twice: ${percent}`);
    seen.add(percent);
  }
  return [...thresholds].sort((a, b) => a.percent - b.percent);
}
