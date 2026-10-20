// The dekatron page's shared state model (how-it-works/dekatron.md). Every view (ring, scope,
// unrolled strip) draws from these functions, so the figures and captions cannot disagree.
//
// A stage s in 0..39: n = floor(s / 4) is the main cathode the step starts from, and the phase
// s % 4 is the drive state, following the bench test's button sequence (docs/bringup.md): rest,
// G1 grounded, G1 and G2 grounded, G2 grounded, then rest on K(n+1). Walking the stages backwards
// is exactly the reverse sequence (G2 first). A qualitative state model, not a plasma simulation.
export const CATHODES = 10;
export const PHASES = 4;
export const STAGES = CATHODES * PHASES;
export const ELECTRODES = CATHODES * 3; // K_n, G1_n, G2_n in counting order

// The model's two thresholds, held fixed (docs/bringup.md bench test): the maintaining voltage,
// measured at the bench's operating point, and the striking voltage of fresh gas, estimated from
// the first strike (289 V supply, ~256 V across the tube with a calculated RTN). How much
// lower a primed gap strikes was not measured, so no figure is given for it.
export const V = {
  maintaining: 147,
  strikeUnprimed: 256,
};

// Node voltages from ground in the bench circuit (docs/bringup.md: 400 V supply, R_A 660k,
// R1 340k, R2 38.1k, R3 47k, R_G 470k), calculated with the tube modelled to first order as
// "anode = glowing electrode + 147 V". At rest the calculation gives RTN 57 V and anode 204 V;
// the bench measured 63 V and 210 V. G+ was not measured.
export const BENCH = {
  supply: 400,
  measured: { rtn: 63, anode: 210 },
  // No button pressed, glow on a main cathode.
  rest: { gplus: 91, rtn: 57, anode: 204 },
  // The instant a guide is grounded, before the glow has moved off the cathode.
  grounding: { gplus: 80, rtn: 51, anode: 198 },
  // One guide grounded and glowing.
  oneLow: { gplus: 70, rtn: 39, anode: 147 },
  // Both guides grounded, glow shared between them.
  bothLow: { gplus: 62, rtn: 34, anode: 147 },
};

export const mod = (a, m) => ((a % m) + m) % m;
export const K = (n) => `K${mod(n, CATHODES)}`;

// The state at stage s (any integer; wrapped here): drive levels, which electrodes glow (positions
// relative to 3n of the wrapped stage), the stable count, and the bench node voltages.
export function stageState(s) {
  const w = mod(s, STAGES);
  const n = Math.floor(w / PHASES);
  const phase = w % PHASES;
  const base = 3 * n;
  const glow = [
    [{ at: base, strength: 1 }],
    [{ at: base + 1, strength: 1 }],
    [
      { at: base + 1, strength: 0.75 },
      { at: base + 2, strength: 0.75 },
    ],
    [{ at: base + 2, strength: 1 }],
  ][phase];
  return {
    n,
    phase,
    g1Low: phase === 1 || phase === 2,
    g2Low: phase === 2 || phase === 3,
    glow,
    count: phase === 0 ? n : null,
    indexLit: phase === 0 && n === 1,
    nodes: [BENCH.rest, BENCH.oneLow, BENCH.bothLow, BENCH.oneLow][phase],
  };
}

// Kind of electrode at position p: 0 main cathode, 1 G1, 2 G2.
export const kindOf = (p) => mod(p, 3);

export function electrodeName(p) {
  const n = Math.floor(mod(p, ELECTRODES) / 3);
  return [`main cathode ${K(n)}`, `guide G1 between ${K(n)} and ${K(n + 1)}`, `guide G2 between ${K(n)} and ${K(n + 1)}`][kindOf(p)];
}

export function shortName(p) {
  return [K(Math.floor(mod(p, ELECTRODES) / 3)), "G1", "G2"][kindOf(p)];
}

// Voltage of electrode p from ground. `rising` names a guide kind (1 or 2) that has just been
// released and is still on its way up, shown at `risingAt` volts.
export function potential(p, state, nodes = state.nodes, rising = null) {
  const kind = kindOf(p);
  if (kind === 0) return nodes.rtn;
  if (kind === rising) return nodes.risingAt;
  return (kind === 1 ? state.g1Low : state.g2Low) ? 0 : nodes.gplus;
}

// One frame of the unrolled strip. "settled" is the stage as it stands; "instant" is the moment
// the buttons change, with the new drive and the glow where it was. For the instant the node
// voltages depend on what changed:
// - a guide grounded from rest: the glow is still on a cathode (BENCH.grounding);
// - the second guide grounded: the glow is on the first, at 0 V (BENCH.bothLow);
// - one of two guides released: it rises towards G+ while the glow stays on the other, at 0 V
//   (BENCH.oneLow), drawn at G+;
// - the last guide released: the glow rises with it, and the handoff comes as it passes the
//   cathodes' level (BENCH.rest), drawn there.
export function frame(stage, dir, kind) {
  const state = stageState(stage);
  if (kind !== "instant") {
    return { state, nodes: state.nodes, rising: null, glowStage: stage };
  }
  const before = stageState(stage - dir);
  const lowNow = state.g1Low + state.g2Low;
  const lowBefore = before.g1Low + before.g2Low;
  let nodes;
  let rising = null;
  if (lowNow > lowBefore) {
    nodes = lowBefore === 0 ? BENCH.grounding : BENCH.bothLow;
  } else {
    rising = before.g1Low && !state.g1Low ? 1 : 2;
    nodes = lowNow === 0 ? { ...BENCH.rest, risingAt: BENCH.rest.rtn } : { ...BENCH.oneLow, risingAt: BENCH.oneLow.gplus };
  }
  return { state, nodes, rising, glowStage: stage - dir };
}

// What just happened, in words. `dir` is +1 after a forward move, -1 after a backward one and 0
// after a restart.
export function caption(state, dir) {
  const { n, phase } = state;
  const hold = "Nothing more happens until the next pulse: the tube itself holds the count.";
  if (dir === 0) {
    return `The glow rests on main cathode ${K(n)}. Count = ${n}. Both guides sit above the cathodes, so the glow stays where it is. ${hold}`;
  }
  if (dir > 0) {
    return [
      `G2 released. The glow drops to the nearest main cathode, ${K(n)}: one step on, not back. Count = ${n}. ${hold}`,
      `G1 grounded. All ten G1 guides fall together, but only the one beside ${K(n)} lies in the glow's ionised neighbourhood, so the discharge moves onto it.`,
      `G2 grounded as well. The glow spreads to the G2 beside it, on the far side from ${K(n)}. The other G2 guides are too far from the discharge.`,
      `G1 released. It rises above the cathodes and gives up its share of the glow, which stays on G2, now beside ${K(n + 1)}.`,
    ][phase];
  }
  return [
    `G1 released. The glow drops to the nearest main cathode, ${K(n)}: one step back. Count = ${n}. ${hold}`,
    `G2 released. The glow stays on G1, beside ${K(n)}.`,
    `G1 grounded as well. The glow spreads to the G1 beside it, towards ${K(n)}.`,
    `G2 grounded first. The G2 beside ${K(n + 1)} takes the glow. Starting with G2 instead of G1 reverses the direction.`,
  ][phase];
}

// The same transitions in bench voltages (from ground), for the unrolled strip.
export function physicsCaption(state, dir) {
  const { n, phase } = state;
  const vm = V.maintaining;
  const { rest, grounding, oneLow } = BENCH;
  const strike = V.strikeUnprimed;
  if (dir === 0) {
    return `The glow sits on ${K(n)}. The cathodes are at about ${rest.rtn} V and the anode at about ${rest.anode} V: ${vm} V across the glow. Every other main cathode has the same ${vm} V across its gap: the model's maintaining voltage, enough to keep a glow going but below the estimated ${strike} V needed to start one unprimed. The guides, at about ${rest.gplus} V, have only ${rest.anode - rest.gplus} V.`;
  }
  const fall = (g, beside) =>
    `${g} is grounded: 0 V. The anode is still about ${grounding.anode} V, ${vm} V above the glowing ${beside}, so every ${g} suddenly has ${grounding.anode} V across its gap. A distant ${g} would need about ${strike} V, the estimated striking voltage, and stays dark; the ${g} beside the glow is primed by its ions and strikes. With the glow at 0 V the anode drops to ${oneLow.anode} V, and ${beside}, at about ${oneLow.rtn} V, is left with ${oneLow.anode - oneLow.rtn} V: below the model's ${vm} V maintaining voltage, so it goes out.`;
  const spread = (g, from) =>
    `${g} is grounded as well. With the glow on ${from}, also at 0 V, the anode is at ${vm} V, so ${g} has ${vm} V across it: the maintaining voltage. Only the ${g} next to the glow is primed enough to strike at that, so the glow spreads onto it.`;
  const release = (g, left) =>
    `${g} is released and rises towards G+, about ${oneLow.gplus} V. The glow on ${left}, still at 0 V, holds the anode at ${vm} V, so ${g}'s gap shrinks to ${vm - oneLow.gplus} V, far below the model's ${vm} V maintaining voltage: its share goes out.`;
  const land = (g, next, old) =>
    `${g} is released and rises, carrying the glow, with the anode ${vm} V above it. As ${g} passes the cathodes' level, about ${rest.rtn} V, the anode reaches about ${rest.anode} V and both nearby main cathodes have ${vm} V across them. ${next} is next to the glow and primed; ${old} is two electrodes away. The glow drops onto ${next}, and ${g}, back at about ${rest.gplus} V, is left with ${rest.anode - rest.gplus} V.`;
  if (dir > 0) {
    return [land("G2", K(n), K(n - 1)), fall("G1", K(n)), spread("G2", "G1"), release("G1", "G2")][phase];
  }
  return [land("G1", K(n), K(n + 1)), release("G2", "G1"), spread("G1", "G2"), fall("G2", K(n + 1))][phase];
}
