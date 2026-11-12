// Controls shared by the dekatron figures: stage and count stepping, play/pause, direction, speed
// and restart. The stage is kept unwrapped (it can pass 39 or go below 0) so a view can tell a
// step from K9 to K0 from a jump back to the start; model.stageState() wraps it.
import { PHASES } from "./model.js";

export const REDUCED_MOTION =
  window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function html(tag, attributes = {}, children = []) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "text") el.textContent = value;
    else el.setAttribute(key, value);
  }
  el.append(...children);
  return el;
}

const SVG_NS = "http://www.w3.org/2000/svg";
export function svg(tag, attributes = {}, children = []) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attributes)) el.setAttribute(key, value);
  el.append(...children);
  return el;
}

export const fmt = (v) => v.toFixed(2);

// `render({ stage, dir, cause })` is called after every change: cause is "move" (dir is +1 or -1),
// "reset" (dir 0) or "refresh" (an option changed; dir is the last move's). `extras` are further
// control groups appended to the bar. Returns the control bar and a refresh() for those extras.
export function createStepper({ render, extras = [], keyTarget }) {
  const button = (text, label) =>
    html("button", { type: "button", class: "md-button ring__button", "aria-label": label || text, text });
  const prev = button("◀ Stage", "Previous stage");
  const next = button("Stage ▶", "Next stage");
  const minus = button("Count −1");
  const plus = button("Count +1");
  const play = button("Play");
  const restart = button("Restart");
  const direction = html("select", { "aria-label": "Play direction" }, [
    html("option", { value: "1", text: "counting up (G1 first)" }),
    html("option", { value: "-1", text: "counting down (G2 first)" }),
  ]);
  const speed = html("input", { type: "range", min: "0", max: "4", step: "1", value: "1", "aria-label": "Speed" });

  const controls = html("div", { class: "ring__controls" }, [
    html("div", { class: "ring__group" }, [prev, next]),
    html("div", { class: "ring__group" }, [minus, plus]),
    html("div", { class: "ring__group" }, [play, html("label", {}, [html("span", { text: "Direction " }), direction])]),
    html("div", { class: "ring__group" }, [html("label", {}, [html("span", { text: "Speed " }), speed]), restart]),
    ...extras.map((nodes) => html("div", { class: "ring__group" }, nodes)),
  ]);

  let stage = 0;
  let lastDir = 0;
  let timer = null;
  let target = null; // stage that a count -1 / +1 is heading for

  const interval = () => [2400, 1400, 800, 450, 220][Number(speed.value)];
  const emit = (cause) => render({ stage, dir: lastDir, cause, interval: interval() });

  function move(dir) {
    stage += dir;
    lastDir = dir;
    emit("move");
  }

  function stop() {
    clearInterval(timer);
    timer = null;
    target = null;
    play.textContent = "Play";
    play.setAttribute("aria-label", "Play");
  }

  function start(dir, until = null) {
    stop();
    if (until !== null && REDUCED_MOTION) {
      while (stage !== until) move(dir);
      return;
    }
    target = until;
    const tick = () => {
      move(dir);
      if (target !== null && stage === target) stop();
    };
    timer = setInterval(tick, until === null ? interval() : Math.min(interval(), 600));
    if (until === null) {
      play.textContent = "Pause";
      play.setAttribute("aria-label", "Pause");
    }
    tick(); // the first stage at once; stop() clears the timer if that was the last one
  }

  // Count +1 / -1: run to the next main cathode in that direction.
  function count(dir) {
    start(dir, dir > 0 ? (Math.floor(stage / PHASES) + 1) * PHASES : Math.ceil(stage / PHASES - 1) * PHASES);
  }

  prev.addEventListener("click", () => (stop(), move(-1)));
  next.addEventListener("click", () => (stop(), move(1)));
  minus.addEventListener("click", () => count(-1));
  plus.addEventListener("click", () => count(1));
  play.addEventListener("click", () => (timer && target === null ? stop() : start(Number(direction.value))));
  restart.addEventListener("click", () => {
    stop();
    stage = 0;
    lastDir = 0;
    emit("reset");
  });
  const replay = () => {
    if (timer && target === null) start(Number(direction.value));
  };
  speed.addEventListener("input", replay);
  direction.addEventListener("change", replay);
  keyTarget?.addEventListener("keydown", (event) => {
    const keys = { ArrowRight: () => (stop(), move(1)), ArrowLeft: () => (stop(), move(-1)), ArrowUp: () => count(1), ArrowDown: () => count(-1) };
    if (keys[event.key]) {
      event.preventDefault();
      keys[event.key]();
    }
  });

  return { controls, refresh: () => emit("refresh"), start: () => emit("reset") };
}
