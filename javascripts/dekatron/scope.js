// A scope-like record of the bench circuit, for the ring figure: anode, G1 and G2 in volts from
// ground, each with the main cathodes (RTN) dashed underneath, and where the glow is; one column
// per stage change, newest on the right. The horizontal axis counts events, not time: the phases
// last as long as the buttons are held. Values are model.BENCH (calculated, first-order).
import { kindOf, shortName, stageState } from "./model.js";
import { fmt, svg } from "./stepper.js";

const LEFT = 92;
// viewBox width and columns shown: fewer on small screens, so the text stays readable.
const WIDE = { width: 640, columns: 14 };
const NARROW = { width: 420, columns: 8 };
const KEEP = WIDE.columns;
const LANES = {
  anode: { top: 14, height: 60, max: 220, ticks: [0, 100, 200], label: "Anode", value: (s) => s.nodes.anode },
  g1: { top: 98, height: 44, max: 100, ticks: [0, 50, 100], label: "G1", value: (s) => (s.g1Low ? 0 : s.nodes.gplus) },
  g2: { top: 166, height: 44, max: 100, ticks: [0, 50, 100], label: "G2", value: (s) => (s.g2Low ? 0 : s.nodes.gplus) },
};
const GLOW = { top: 226, height: 18, label: "Glow on" };
const HEIGHT = 270;

const yIn = (lane, v) => lane.top + (1 - v / lane.max) * lane.height;

export function createScope() {
  const traces = svg("g", { class: "scope__traces" });
  const furniture = svg("g");
  const root = svg("svg", { class: "scope__svg", role: "img" }, [furniture, traces]);
  let size = WIDE;
  let width = size.width;
  let col = 0;

  // Fixed furniture: lane labels, ground lines and the voltage ticks.
  function layout(next) {
    size = next;
    width = size.width;
    col = (width - LEFT - 8) / size.columns;
    root.setAttribute("viewBox", `0 0 ${width} ${HEIGHT}`);
    root.classList.toggle("scope__svg--narrow", size === NARROW);
    furniture.replaceChildren();
    for (const lane of Object.values(LANES)) {
      furniture.append(
        svg("text", { class: "scope__lane", x: 4, y: fmt(lane.top + lane.height / 2), "dominant-baseline": "central" }, [lane.label]),
        ...lane.ticks.flatMap((v) => [
          svg("line", { class: v ? "scope__grid" : "scope__ref", x1: LEFT, x2: width - 8, y1: fmt(yIn(lane, v)), y2: fmt(yIn(lane, v)) }),
          svg("text", { class: "scope__tick", x: LEFT - 6, y: fmt(yIn(lane, v)), "text-anchor": "end", "dominant-baseline": "central" }, [String(v)]),
        ]),
      );
    }
    furniture.append(
      svg("text", { class: "scope__lane", x: 4, y: fmt(GLOW.top + GLOW.height / 2), "dominant-baseline": "central" }, [GLOW.label]),
      svg("text", { class: "scope__tick", x: LEFT, y: HEIGHT - 6 }, ["earlier"]),
      svg("text", { class: "scope__tick", x: (LEFT + width) / 2, y: HEIGHT - 6, "text-anchor": "middle" }, ["not to time scale"]),
      svg("text", { class: "scope__tick", x: width - 8, y: HEIGHT - 6, "text-anchor": "end" }, ["now"]),
    );
  }
  layout(WIDE);

  let history = [];

  function draw() {
    const shown = history.slice(-size.columns);
    const x = (i) => LEFT + i * col;
    const now = shown.length - 1;
    const children = [svg("rect", { class: "scope__now", x: fmt(x(now)), y: 6, width: fmt(col), height: HEIGHT - 26 })];

    const step = (values, toY, cls) => {
      let d = "";
      values.forEach((v, i) => {
        const y = fmt(toY(v));
        d += i === 0 ? `M${fmt(x(0))} ${y}` : `V${y}`;
        d += `H${fmt(x(i + 1))}`;
      });
      return svg("path", { class: cls, d });
    };
    for (const lane of Object.values(LANES)) {
      const toY = (v) => yIn(lane, v);
      const value = lane.value(shown[now]);
      children.push(
        step(shown.map((s) => s.nodes.rtn), toY, "scope__trace scope__trace--rtn"),
        step(shown.map(lane.value), toY, "scope__trace"),
        svg("text", { class: "scope__value", x: fmt(x(now) + col / 2), y: fmt(toY(value) - 5), "text-anchor": "middle" }, [String(value)]),
      );
    }
    shown.forEach((s, i) => {
      const onGuide = kindOf(s.glow[0].at) !== 0;
      children.push(
        svg(
          "text",
          {
            class: `scope__glow${onGuide ? " scope__glow--guide" : ""}${i === now ? " scope__glow--now" : ""}`,
            x: fmt(x(i) + col / 2),
            y: fmt(GLOW.top + GLOW.height / 2),
            "text-anchor": "middle",
            "dominant-baseline": "central",
          },
          [s.glow.map((g) => shortName(g.at)).join("+")],
        ),
      );
    });
    traces.replaceChildren(...children);
    const last = shown[now];
    root.setAttribute(
      "aria-label",
      `Voltage record, newest last. Now: anode ${last.nodes.anode} V, cathodes ${last.nodes.rtn} V, G1 ${LANES.g1.value(last)} V, G2 ${LANES.g2.value(last)} V, glow on ${last.glow.map((g) => shortName(g.at)).join(" and ")}.`,
    );
  }

  return {
    root,
    // Pick the wide or narrow layout for a container this many CSS pixels wide.
    fit(pixels) {
      const next = pixels < 560 ? NARROW : WIDE;
      if (next !== size) {
        layout(next);
        if (history.length) draw();
      }
    },
    reset(stage) {
      history = [stageState(stage)];
      draw();
    },
    push(stage) {
      history.push(stageState(stage));
      if (history.length > KEEP) history = history.slice(-KEEP);
      draw();
    },
  };
}
