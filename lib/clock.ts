/* Client-side clock. Every intra-session delta is a difference of
   performance.now() values (invariant M1): 20 school devices will not have
   synchronised wall clocks and NTP can jump mid-session, but a monotonic clock
   cannot move backwards.

   There is deliberately no wall-clock function in this file. The single anchor
   comes from the server (POST /api/session/start) and the reconstruction to
   real timestamps happens server-side only (invariant M2), in /api/trial. */

export const now = (): number => performance.now();

/** Earliest of the three first-interaction signals; null if none fired (M4). */
export const earliest = (...marks: (number | null)[]): number | null => {
  const set = marks.filter((m): m is number => m !== null);
  return set.length ? Math.min(...set) : null;
};
