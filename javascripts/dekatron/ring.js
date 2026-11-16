// The dekatron page (how-it-works/dekatron.md): the interactive electrode ring.
//
// Each <div class="dekatron-ring"> becomes a ring of 30 electrodes (main cathodes K0-K9, with a
// G1 and a G2 guide between each pair), a drive-state panel, a caption, a scope-like record of the
// drive (scope.js) and controls. Its static fallback (.ring__fallback) is removed once the figure is
// built. The state model is model.js; the controls are stepper.js.
import { BENCH, CATHODES, ELECTRODES, caption, electrodeName, mod, stageState } from "./model.js";
import { createScope } from "./scope.js";
import { createStepper, fmt, html, svg } from "./stepper.js";

const R_ELECTRODE = 120;

// --- drawing ------------------------------------------------------------------------------------

const angle = (p) => ((-90 + (360 * p) / ELECTRODES) * Math.PI) / 180;
const polar = (p, r) => [r * Math.cos(angle(p)), r * Math.sin(angle(p))];

function arcPath(p0, p1, r) {
  const [x0, y0] = polar(p0, r);
  const [x1, y1] = polar(p1, r);
  const large = mod(p1 - p0, ELECTRODES) > ELECTRODES / 2 ? 1 : 0;
  return `M${fmt(x0)} ${fmt(y0)}A${r} ${r} 0 ${large} 1 ${fmt(x1)} ${fmt(y1)}`;
}

// One electrode's marker: circle for main cathodes, triangle for G1, square for G2.
function marker(p) {
  const [x, y] = polar(p, R_ELECTRODE);
  const deg = (angle(p) * 180) / Math.PI;
  const kind = p % 3;
  let shape;
  if (kind === 0) shape = svg("circle", { r: 8 });
  else if (kind === 1) shape = svg("path", { d: "M0 -6.5L6 4.5H-6Z" });
  else shape = svg("rect", { x: -4.5, y: -4.5, width: 9, height: 9 });
  return svg(
    "g",
    {
      class: `ring__el ring__el--${["k", "g1", "g2"][kind]}`,
      transform: `translate(${fmt(x)} ${fmt(y)}) rotate(${fmt(deg + 90)})`,
    },
    [shape],
  );
}

function buildRing(uid) {
  const halo = svg("radialGradient", { id: `${uid}-halo` }, [
    svg("stop", { offset: "0", class: "ring__halo-stop", "stop-opacity": "0.9" }),
    svg("stop", { offset: "0.45", class: "ring__halo-stop", "stop-opacity": "0.35" }),
    svg("stop", { offset: "1", class: "ring__halo-stop", "stop-opacity": "0" }),
  ]);

  // Shared connections, hidden until asked for: nine cathodes on the RTN bus (K1 is the index and
  // has its own wire), and the two guide buses.
  const connections = svg("g", { class: "ring__connections", "aria-hidden": "true" });
  connections.append(
    svg("path", { class: "ring__bus", d: arcPath(6, 0.0001 + ELECTRODES, 140) }),
    svg("circle", { class: "ring__bus", r: 97 }),
    svg("circle", { class: "ring__bus", r: 84 }),
  );
  for (let p = 0; p < ELECTRODES; p++) {
    const kind = p % 3;
    if (kind === 0 && p === 3) {
      const [x0, y0] = polar(p, 129);
      const [x1, y1] = polar(p + 0.8, 170);
      connections.append(svg("line", { class: "ring__wire ring__wire--index", x1: fmt(x0), y1: fmt(y0), x2: fmt(x1), y2: fmt(y1) }));
      continue;
    }
    const [r0, r1] = kind === 0 ? [129, 140] : kind === 1 ? [113, 97] : [115, 84];
    const [x0, y0] = polar(p, r0);
    const [x1, y1] = polar(p, r1);
    connections.append(
      svg("line", { class: "ring__wire", x1: fmt(x0), y1: fmt(y0), x2: fmt(x1), y2: fmt(y1) }),
      svg("circle", { class: "ring__node", cx: fmt(x1), cy: fmt(y1), r: 1.8 }),
    );
  }
  const [ix, iy] = polar(3.8, 174);
  connections.append(
    svg("text", { class: "ring__bus-label", x: fmt(ix + 4), y: fmt(iy) }, ["index"]),
    svg("text", { class: "ring__bus-label", x: 0, y: 186, "text-anchor": "middle" }, ["RTN bus: nine cathodes joined"]),
    svg("text", { class: "ring__bus-label", x: 0, y: 104, "text-anchor": "middle" }, ["G1 bus"]),
    svg("text", { class: "ring__bus-label", x: 0, y: 79, "text-anchor": "middle" }, ["G2 bus"]),
  );

  const halos = svg("g", { class: "ring__halos", "aria-hidden": "true" });
  const markers = [];
  const electrodes = svg("g", { class: "ring__electrodes" });
  for (let p = 0; p < ELECTRODES; p++) {
    const m = marker(p);
    markers.push(m);
    electrodes.append(m);
  }
  const labels = svg("g", { class: "ring__labels", "aria-hidden": "true" });
  for (let n = 0; n < CATHODES; n++) {
    const [x, y] = polar(3 * n, 155);
    labels.append(svg("text", { x: fmt(x), y: fmt(y), "text-anchor": "middle", "dominant-baseline": "central" }, [`K${n}`]));
  }
  const guideLabel = svg("text", { class: "ring__guide-label", "text-anchor": "middle", "dominant-baseline": "central", "aria-hidden": "true" });

  const root = svg(
    "svg",
    { class: "ring__svg", viewBox: "-200 -200 400 400", role: "img", tabindex: "0" },
    [
      svg("defs", {}, [halo]),
      connections,
      svg("circle", { class: "ring__anode", r: 40 }),
      svg("text", { class: "ring__anode-label", "text-anchor": "middle", "dominant-baseline": "central" }, ["anode"]),
      halos,
      electrodes,
      labels,
      guideLabel,
    ],
  );
  return { root, halos, markers, guideLabel, haloId: `${uid}-halo` };
}

// --- the figure ---------------------------------------------------------------------------------

let figureCount = 0;

function setup(container) {
  const uid = `dekatron-ring-${++figureCount}`;
  const ring = buildRing(uid);
  const scope = createScope();

  const connections = html("input", { type: "checkbox" });
  const voltages = html("input", { type: "checkbox" });

  const row = (label) => {
    const value = html("dd");
    return { value, nodes: [html("dt", { text: label }), value] };
  };
  const rows = { count: row("Count"), g1: row("G1 guides"), g2: row("G2 guides"), index: row("Index (K1, board)") };
  const badge = html("p", { class: "ring__badge" });
  const text = html("p", { class: "ring__caption", "aria-live": "polite" });
  const anodeNote = html("p", { class: "ring__volts" });

  const panel = html("div", { class: "ring__panel" }, [
    badge,
    html("dl", { class: "ring__state" }, Object.values(rows).flatMap((r) => r.nodes)),
    anodeNote,
    text,
  ]);

  function render({ stage, dir, cause }) {
    const state = stageState(stage);
    const lit = new Map(state.glow.map((g) => [mod(g.at, ELECTRODES), g.strength]));
    ring.markers.forEach((m, p) => m.classList.toggle("ring__el--lit", lit.has(p)));
    ring.halos.replaceChildren(
      ...[...lit].map(([p, strength]) => {
        const [x, y] = polar(p, R_ELECTRODE);
        return svg("circle", { cx: fmt(x), cy: fmt(y), r: 24, fill: `url(#${ring.haloId})`, opacity: strength });
      }),
    );
    // Name the guide(s) holding the glow, inside the ring next to them.
    if (state.phase === 0) {
      ring.guideLabel.textContent = "";
    } else {
      const p = mod(3 * state.n + (state.phase === 3 ? 2 : 1), ELECTRODES);
      const [x, y] = polar(p + (state.phase === 2 ? 0.5 : 0), 64);
      ring.guideLabel.setAttribute("x", fmt(x));
      ring.guideLabel.setAttribute("y", fmt(y));
      ring.guideLabel.textContent = ["", "G1", "G1+G2", "G2"][state.phase];
    }

    const level = (low) => (low ? "grounded" : "at rest") + (voltages.checked ? `: ${low ? 0 : state.nodes.gplus} V` : "");
    rows.count.value.textContent =
      state.count === null ? `between ${state.n} and ${mod(state.n + 1, CATHODES)}, transfer in progress` : String(state.count);
    rows.g1.value.textContent = level(state.g1Low);
    rows.g2.value.textContent = level(state.g2Low);
    rows.index.value.textContent = state.indexLit ? "lit: the controller sees a pulse" : "dark";
    badge.textContent = state.count === null ? "Transfer in progress (guide)" : "Stable: glow on a main cathode";
    badge.classList.toggle("ring__badge--transfer", state.count === null);
    anodeNote.hidden = !voltages.checked;
    anodeNote.textContent = `From ground, on the bench at ${BENCH.supply} V (calculated): anode ${state.nodes.anode} V, main cathodes ${state.nodes.rtn} V.`;
    text.textContent = caption(state, dir);
    const where = state.glow.map((g) => electrodeName(g.at)).join(" and ");
    ring.root.setAttribute("aria-label", `Dekatron electrode ring. Glow on ${where}.`);
    container.classList.toggle("ring--connections", connections.checked);

    if (cause === "move") scope.push(stage);
    else if (cause === "reset") scope.reset(stage);
  }

  const stepper = createStepper({
    render,
    keyTarget: ring.root,
    extras: [
      [
        html("label", {}, [connections, html("span", { text: " Show connections" })]),
        html("label", {}, [voltages, html("span", { text: " Show voltages" })]),
      ],
    ],
  });
  connections.addEventListener("change", stepper.refresh);
  voltages.addEventListener("change", stepper.refresh);

  container.querySelector(".ring__fallback")?.remove();
  container.classList.add("ring--live");
  // Controls sit right under the ring, so a press and its effect stay on screen together; the
  // voltage record is optional detail, collapsed below them.
  container.append(
    html("div", { class: "ring__body" }, [html("div", { class: "ring__figure" }, [ring.root]), panel]),
    stepper.controls,
    html("details", { class: "scope__details" }, [
      html("summary", { text: "Voltage record of the bench circuit" }),
      html("figure", { class: "scope" }, [
        scope.root,
        html("figcaption", {
          text: `In volts from ground, calculated from the bench circuit's resistor values. Dashed: the main cathodes. A grounded guide drops below them; at rest it sits above. Count up and then down to compare the two sequences.`,
        }),
      ]),
    ]),
  );
  stepper.start();
  new ResizeObserver(() => scope.fit(container.clientWidth)).observe(container);
}

document.querySelectorAll(".dekatron-ring").forEach(setup);
