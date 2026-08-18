/**
 * token-watch-core.ts — the pure, dependency-free crossing logic for the Pi token-watch extension
 * (#1577). No pi/typebox imports, so it unit-tests without loading the agent runtime.
 *
 * A Pi comrade self-monitors its context window the way a Claude comrade runs `claude-tokens watch`:
 * as usage climbs past each threshold it is nudged once, and the comrade telemetry rules (Comrade.md)
 * decide what to do (dispatch `Tokens: NN%`). This module owns only the "which thresholds did we just
 * cross" decision; the extension wires it to pi's usage feed and the nudge.
 */

/** Comrade.md telemetry thresholds (#1577), percent of the context window. */
export const DEFAULT_THRESHOLDS = [20, 50, 70, 85, 92, 95];

export class TokenWatch {
  private thresholds: number[];
  private fired = new Set<number>();

  constructor(thresholds: number[] = DEFAULT_THRESHOLDS) {
    this.thresholds = normalizeThresholds(thresholds);
  }

  /** Replace the armed thresholds; already-fired state for any surviving threshold is preserved so a
   *  reconfigure never re-fires a threshold already reported this fill. */
  arm(thresholds: number[]): void {
    this.thresholds = normalizeThresholds(thresholds);
    // Drop fired marks for thresholds no longer armed (keeps the set from growing unbounded).
    for (const t of [...this.fired]) if (!this.thresholds.includes(t)) this.fired.delete(t);
  }

  /** Context dropped (compaction) — re-arm every threshold so the climb can be reported again. */
  reset(): void {
    this.fired.clear();
  }

  armed(): number[] {
    return [...this.thresholds];
  }

  /**
   * Given the current usage percent, return the armed thresholds newly crossed by it (ascending),
   * marking them fired so each fires at most once per fill. A null/negative percent (unknown usage,
   * e.g. right after compaction) crosses nothing.
   */
  crossed(percent: number | null): number[] {
    if (percent == null || !Number.isFinite(percent) || percent < 0) return [];
    const now: number[] = [];
    for (const t of this.thresholds) {
      if (percent >= t && !this.fired.has(t)) {
        this.fired.add(t);
        now.push(t);
      }
    }
    return now;
  }
}

/** De-dupe, drop out-of-range/non-finite entries, and sort ascending. */
export function normalizeThresholds(thresholds: number[]): number[] {
  const clean = thresholds.filter((t) => Number.isFinite(t) && t > 0 && t <= 100);
  return [...new Set(clean)].sort((a, b) => a - b);
}
