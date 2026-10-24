// The dekatron page's unrolled view (how-it-works/dekatron.md, "How the glow moves"): a few
// electrodes of the ring laid out in a row under the anode, with the glow, a schematic cloud of
// ions around it, and a chart of voltages from ground in the bench circuit.
//
// In the chart each electrode has a bar from its own voltage up to the anode's: the bar's length is
// the voltage across its gap. A tick 147 V above the electrode marks the model's maintaining
// voltage (measured at the bench's operating point); a dashed outline up to 256 V above it marks
// the striking voltage of fresh gas, estimated from the first strike. A primed gap strikes
// lower by an amount that was not measured, so that is drawn as an arrow with no number.
//
// Each <div class="dekatron-strip"> becomes the figure; its .ring__fallback is removed. Every
// change of drive is shown in two frames: the instant the buttons change (new drive, glow not yet
// moved), which is where the voltages decide what happens, then the state after the handoff
// (model.frame).
import { ELECTRODES, STAGES, V, frame, kindOf, physicsCaption, shortName, stageState, potential } from "./model.js";
import { REDUCED_MOTION, createStepper, fmt, html, svg } from "./stepper.js";

const PITCH = 64;
const WIDE = 640; // viewBox width; narrower on small screens, so the text stays readable
const NARROW = 420;
const GUTTER = 50; // left margin for the chart's limit labels
const HEIGHT = 405;
const EY = 112; // electrode row
const BASE = 387; // 0 V on the chart
const TOP_V = 320; // chart range, volts from ground
const SCALE = 140 / TOP_V; // px per volt
const SPAN = 7; // electrodes drawn either side of the centre

const yOf = (v) => BASE - v * SCALE;

// Glowing positions for a stage, unwrapped so a step from K9 to K0 continues to the right.
function glowAt(stage) {
  const turns = Math.floor(stage / STAGES) * ELECTRODES;
  return stageState(stage).glow.map((g) => ({ at: g.at + turns, strength: g.strength }));
}
// The strip is centred between the two cathodes of the current step, and only slides once a step
// completes, so within a step the glow is seen to move and the electrodes stay put.
const centreOf = (stage) => 3 * Math.floor(stage / 4) + 1;

function marker(kind) {
  if (kind === 0) return svg("circle", { r: 12 });
  if (kind === 1) return svg("path", { d: "M0 -10L9 7H-9Z" });
  return svg("rect", { x: -7, y: -7, width: 14, height: 14 });
}

let figureCount = 0;

function setup(container) {
  const uid = `dekatron-strip-${++figureCount}`;
  const defs = svg("defs", {}, [
    svg("radialGradient", { id: `${uid}-glow` }, [
      svg("stop", { offset: "0", class: "ring__halo-stop", "stop-opacity": "0.95" }),
      svg("stop", { offset: "0.5", class: "ring__halo-stop", "stop-opacity": "0.4" }),
      svg("stop", { offset: "1", class: "ring__halo-stop", "stop-opacity": "0" }),
    ]),
    svg("radialGradient", { id: `${uid}-cloud` }, [
      svg("stop", { offset: "0", class: "strip__cloud-stop", "stop-opacity": "0.35" }),
      svg("stop", { offset: "1", class: "strip__cloud-stop", "stop-opacity": "0" }),
    ]),
  ]);
  const clipRect = svg("rect", { x: GUTTER, y: 0, height: HEIGHT });
  defs.append(svg("clipPath", { id: `${uid}-clip` }, [clipRect]));

  const world = svg("g", { class: "strip__world" });
  const anodeLabel = svg("text", { class: "strip__label", y: 18, "text-anchor": "end" });
  const anodeLine = svg("line", { class: "strip__anode-line", x1: GUTTER });
  const furniture = svg("g");
  const root = svg("svg", { class: "strip__svg", role: "img", tabindex: "0" }, [
    defs,
    furniture,
    anodeLabel,
    svg("g", { "clip-path": `url(#${uid}-clip)` }, [world]),
    anodeLine,
  ]);

  // The fixed parts, for a viewBox `width` wide.
  let width = WIDE;
  function layout() {
    width = container.clientWidth < 560 ? NARROW : WIDE;
    root.setAttribute("viewBox", `0 0 ${width} ${HEIGHT}`);
    root.classList.toggle("strip__svg--narrow", width === NARROW);
    clipRect.setAttribute("width", width - GUTTER - 8);
    anodeLabel.setAttribute("x", width - 12);
    anodeLine.setAttribute("x2", width - 8);
    const grid = [0, 100, 200, 300].flatMap((v) => [
      svg("line", { class: v ? "strip__grid" : "strip__axis", x1: GUTTER, x2: width - 8, y1: fmt(yOf(v)), y2: fmt(yOf(v)) }),
      svg("text", { class: "strip__limit-label", x: GUTTER - 4, y: fmt(yOf(v)), "text-anchor": "end", "dominant-baseline": "central" }, [
        `${v} V`,
      ]),
    ]);
    furniture.replaceChildren(
      svg("rect", { class: "ring__anode", x: 8, y: 26, width: width - 16, height: 10, rx: 2 }),
      svg("text", { class: "strip__label", x: 8, y: 18 }, ["anode (the ring's centre, unrolled)"]),
      svg("text", { class: "strip__label", x: 8, y: 194 }, ["Volts from ground; bars run from electrode to anode."]),
      svg("text", { class: "strip__label", x: 8, y: 209 }, [`Tick: the model's maintaining voltage, ${V.maintaining} V.`]),
      svg("text", { class: "strip__label", x: 8, y: 224 }, [`Dashed: its estimated striking voltage, ≈${V.strikeUnprimed} V.`]),
      ...grid,
    );
  }

  const badge = html("p", { class: "ring__badge" });
  const text = html("p", { class: "ring__caption strip__caption", "aria-live": "polite" });

  let pending = null;
  let shownCentre = null;

  let last = null;
  function draw(view) {
    last = view;
    const { stage, dir, kind, centre } = view;
    const fr = frame(stage, dir, kind);
    const glow = glowAt(fr.glowStage);
    const anode = fr.nodes.anode;
    const positions = [];
    for (let p = centre - SPAN; p <= centre + SPAN; p++) positions.push(p);
    const lit = new Map(glow.map((g) => [g.at, g.strength]));
    const primed = new Set(positions.filter((p) => !lit.has(p) && glow.some((g) => Math.abs(g.at - p) === 1)));

    const clouds = [];
    const glows = [];
    const items = [];
    for (const g of glow) {
      clouds.push(svg("ellipse", { cx: g.at * PITCH, cy: EY, rx: 80, ry: 52, fill: `url(#${uid}-cloud)`, opacity: g.strength }));
      glows.push(svg("ellipse", { cx: g.at * PITCH, cy: EY, rx: 22, ry: 24, fill: `url(#${uid}-glow)`, opacity: g.strength }));
    }
    for (const p of positions) {
      const x = p * PITCH;
      const v = potential(p, fr.state, fr.nodes, fr.rising);
      const gap = anode - v;
      const rising = kindOf(p) === fr.rising;
      items.push(
        svg("line", { class: "strip__lead", x1: x, x2: x, y1: EY + 12, y2: EY + 30 }),
        svg("g", { class: `ring__el${lit.has(p) ? " ring__el--lit" : ""}`, transform: `translate(${x} ${EY})` }, [marker(kindOf(p))]),
        svg("text", { class: "strip__name", x, y: EY + 46, "text-anchor": "middle" }, [shortName(p)]),
        svg("text", { class: "strip__label", x, y: EY + 62, "text-anchor": "middle" }, [`${v} V${rising ? " ↑" : ""}`]),
      );
      // The model's estimated striking voltage for fresh gas: the part above the anode, dashed.
      const need = v + V.strikeUnprimed;
      if (need > anode) {
        items.push(svg("rect", { class: "strip__need", x: x - 7, y: fmt(yOf(need)), width: 14, height: fmt((need - anode) * SCALE) }));
      }
      items.push(
        svg("rect", { class: `strip__bar${lit.has(p) ? " strip__bar--lit" : ""}`, x: x - 7, y: fmt(yOf(anode)), width: 14, height: fmt(gap * SCALE) }),
        svg("line", { class: "strip__tick", x1: x - 12, x2: x + 12, y1: fmt(yOf(v + V.maintaining)), y2: fmt(yOf(v + V.maintaining)) }),
        svg("circle", { class: "strip__dot", cx: x, cy: fmt(yOf(v)), r: 3 }),
      );
      // Gap value, unless the electrode is partly cut off at either edge.
      if (Math.abs(p - centre) * PITCH < (width - GUTTER) / 2 - 24) {
        items.push(svg("text", { class: "strip__value", x: x + 10, y: fmt(yOf(anode) + 12) }, [String(gap)]));
      }
      if (primed.has(p)) {
        const y = yOf(need);
        items.push(
          svg("text", { class: "strip__primed", x, y: EY - 24, "text-anchor": "middle" }, ["primed"]),
          svg("path", { class: "strip__arrow", d: `M${x - 14} ${fmt(y)}V${fmt(y + 26)}m-4 -6l4 6l4 -6` }),
        );
      }
    }
    world.replaceChildren(...clouds, ...items, ...glows);
    anodeLine.setAttribute("y1", fmt(yOf(anode)));
    anodeLine.setAttribute("y2", fmt(yOf(anode)));

    // Slide to a new centre; jump without animation on a reset or the first draw.
    const animate = shownCentre !== null && kind !== "reset" && !view.jump && !REDUCED_MOTION;
    world.classList.toggle("strip__world--animate", animate);
    world.style.transform = `translateX(${(GUTTER + width) / 2 - centre * PITCH}px)`;
    shownCentre = centre;

    anodeLabel.textContent = `${anode} V`;
    badge.textContent = { instant: "The instant the buttons change", settled: "After the handoff", reset: "At rest" }[kind];
    badge.classList.toggle("ring__badge--transfer", kind === "instant");
    const names = glow.map((g) => shortName(g.at)).join(" and ");
    root.setAttribute("aria-label", `Unrolled electrodes. Glow on ${names}; anode ${anode} V from ground.`);
  }

  function render({ stage, dir, cause, interval }) {
    clearTimeout(pending);
    pending = null;
    const state = stageState(stage);
    text.textContent = physicsCaption(state, cause === "reset" ? 0 : dir);
    const settled = { stage, dir, centre: centreOf(stage), kind: cause === "reset" || dir === 0 ? "reset" : "settled" };
    if (cause !== "move" || REDUCED_MOTION) {
      draw(settled);
      return;
    }
    // First the instant after the switch: new drive, glow where it was, strip where it was.
    draw({ stage, dir, centre: centreOf(stage - dir), kind: "instant" });
    pending = setTimeout(() => draw(settled), Math.min(900, interval * 0.5));
  }

  const stepper = createStepper({ render, keyTarget: root });
  layout();
  new ResizeObserver(() => {
    const before = width;
    layout();
    if (width !== before && last) draw({ ...last, jump: true });
  }).observe(container);
  container.querySelector(".ring__fallback")?.remove();
  container.classList.add("ring--live");
  container.append(html("div", { class: "strip__figure" }, [root]), badge, text, stepper.controls);
  stepper.start();
}

document.querySelectorAll(".dekatron-strip").forEach(setup);
