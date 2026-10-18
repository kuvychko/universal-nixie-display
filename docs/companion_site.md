# Universal Display: companion site

**Status:** Phase 1 in progress (site source in `website/`, local builds until the repository is public) · **Date:** 2026-10-10

## 1. Purpose

Create a visual companion to the universal display project: six IN-14 nixies, an A101 bidirectional dekatron, and a modern touchscreen interface. The site should connect the physical instrument to the mechanisms inside its tubes. A visitor should be able to enjoy the finished object, understand what makes it work, and follow the source if they want to build or investigate further.

The central question is: **How can a glow in a gas-filled tube display a number—or remember and count one?**

The two tube types make a natural contrast. A nixie is **stateless**: it shows whichever digit its driver selects, and forgets it the moment the drive changes. A dekatron is **stateful**: it is a counter, a one-digit register and a display in one glass envelope. The position of the glow *is* the stored digit, held by the discharge itself between pulses; the pulses only say "one more" or "one fewer." This contrast between showing a number and remembering one is the site's organising idea.

The primary audience is a curious technically minded visitor, without assumed knowledge of discharge tubes. Deeper explanations should also reward electronics hobbyists. Start with the object and an observable effect; introduce the circuit and physics when they answer a question the visitor now has.

This proposal covers the educational companion site. It does not change the display's hardware architecture or commit the project to new firmware features.

## 2. Follow the polyhedra project's approach

Reference: [polyhedra-to-rational-functions](https://github.com/kuvychko/polyhedra-to-rational-functions/), reviewed at commit `36ee641657cd48a7888d7822c1bd94895503f201`.

The reference repository uses MkDocs Material, Markdown content in `docs/`, custom JavaScript interactive figures, GitHub Pages deployment, and a separation between public explanation and supporting evidence. Its home page offers two entry points: “The objects” and “The question.” The same editorial pattern fits this project.

| Reference project pattern | Universal display adaptation |
|---|---|
| Photograph of the printed collection | Photograph or short video of the working display; an A101 bench photograph is sufficient initially |
| “The objects” | “The display”: what it does, the controls, and demonstrated modes |
| “The question” | “How the tubes work”: glow discharge, dekatron counting, and nixie digit selection |
| Interactive mathematical primer | Interactive electrode diagrams with synchronized drive sequences |
| Experiments and decision records | Bench observations, annotated scope captures, and design decisions |
| Reproduce and printing information | Links to hardware, firmware, enclosure files, and documented build instructions |
| Explicit limitations | Clear boundaries between conceptual animation, measured behavior, and tube-specific specifications |

Reuse the structure and publishing discipline without recreating the reference project's entire research or catalog machinery. Two tube explanations do not need a generated gallery system.

## 3. Proposed site structure

Begin with a small site hosted from the universal display repository. The landing page acts as the companion page, with focused explanations behind it.

| Page | Purpose and content |
|---|---|
| **Home** | Hero image, a short introduction, current project status, and two routes: “Explore the display” and “Understand the tubes.” |
| **The display** | Real hardware, controls, and modes as they become available. Distinguish working features from planned ones. |
| **How a dekatron counts** | The first and most substantial explainer: electrode ring, single-glow behavior, guide handoff, direction, and retained count. |
| **How a nixie displays a digit** | Stacked numeral cathodes, common anode, external digit selection, and visible glow around the selected shape. |
| **Build and investigate** | Repository links, selected design decisions, bench evidence, and reproduction information. Link to canonical build documents rather than duplicating them. |
| **About and sources** | Project motivation, historical references, datasheets, credits, and licensing. |

Keep the historical overview within the tube pages initially. A separate history page is unnecessary until there is enough material to justify it.

## 4. First centerpiece: the A101 explainer

### Questions the page must answer

1. Why does only one main cathode glow when all are connected to the circuit?
2. How can pulsing an entire guide group select only the guide beside the current glow?
3. How does the discharge transfer to the next main cathode rather than return to the old one?
4. Why does reversing the pulse order reverse the count?
5. What preserves the count between pulses?

### Visual composition

Use a top-down schematic of the electrode ring, with ten main cathodes and two guides between successive main cathodes. Distinguish main cathodes, G1, and G2 through labels and shapes as well as color. Show their shared electrical connections on demand, so the default view stays readable.

Beside or below the ring, show a compact drive-state panel and a sentence explaining the current stage. A synchronized waveform view can appear in an expandable technical section. On a phone, stack these elements vertically.

The sequence is `K_n → G1_n → G2_n → K_(n+1)`, with the reverse sequence available. Labels must state the viewing direction. Verify the physical guide ordering and pin mapping against A101 documentation and the actual tube before presenting the drawing as an A101 layout.

### Controls

- **Next electrode / previous electrode:** inspect each guide handoff.
- **Count +1 / count −1:** complete one main-cathode-to-main-cathode cycle.
- **Play / pause and speed:** repeat the sequence at an explanatory pace.
- **Restart demonstration:** return to a known illustrated state. This is a presentation control, not a claim about the hardware reset circuit.
- **Show connections / show voltages:** reveal technical detail without requiring it for the basic explanation.

Begin paused. One interaction should immediately produce a meaningful change. The numerical count is stable on main cathodes; intermediate guide positions should be explicitly marked as a transfer in progress.

### A tube that remembers

Make the memory point explicit, not incidental:

- The glow position is a one-digit decimal register; the ring of ten main cathodes is a ten-state counter. The drive circuit changes the state but does not hold it.
- In this build the controller cannot read the count at all. Nine of the ten main cathodes are tied together at the socket; only the index cathode K1 is sensed. Firmware infers the count from pulses since the last index; the tube is the only place the count actually lives.
- The memory is volatile: it lasts while the discharge is powered. Switch off and the count is gone; on the next strike the glow settles wherever it settles.
- Historical illustration: the Harwell Dekatron computer (below) used dekatrons as its main store.
- Interactive hook: pause the drive and let the visitor notice that nothing changes. The count stays.

### Historical note

Keep it short, dated and sourced (§9):

- **1945–1947:** John Reginald Acton, then at Cossor, finds that a pulse can move a glow discharge from one cathode to another, and that it stays there when the pulse ends. He conceives a line of ten cathodes.
- **1948:** At Ericsson Telephones, Beeston, Acton demonstrates a first prototype in November; the ten-way GC10A (up to about 400 pulses per second) is ready for production by the end of the year.
- **1949–1950:** Provisional patent, 18 January 1949. The name "Dekatron" (Ray Bacon) appears in print in May 1950.
- **1950s:** The GC10B (about 4,000 pulses per second) becomes the standard tube, used by the thousand in scalers, timers, calculators and cash registers; the GC10D reaches 40,000 per second. The design is copied in Europe, the USA and the USSR.
- **1951:** The Harwell Dekatron computer first runs. Its store is 720 dekatrons (nine boxes of 80). It is switched off in 1973 and rebooted at The National Museum of Computing on 20 November 2012, recognised in 2013 as the world's oldest original working digital computer.
- **Mid-1960s:** Transistor counters make the dekatron obsolete and Ericsson production ends, although installed equipment, such as spot-welder timers, stays in service to the end of the century.
- **A101:** a Soviet two-guide, bidirectional dekatron. Its production history is still to be sourced.

### Explain two mechanisms separately

**Why one glow persists.** Show a small supply–anode-resistor–tube circuit. Before ignition, the anode is near the supply potential. Once a gap conducts, the shared resistor drops voltage, allowing the existing discharge to persist while suppressing fresh discharges elsewhere. Explain the difference between striking and sustaining voltage. The count is held while powered; this is not nonvolatile memory.

**How it moves.** A suitably biased neighboring guide can establish a discharge with help from the nearby ionized region. During the handoff, its glow grows while the previous glow fades. The changed electrical conditions suppress the previous discharge. Adjacency and the ordered guide pulses select the path.

Animate this as a local handoff, including a brief shared-glow stage where appropriate—not as a luminous bead physically traveling through the tube. Do not imply that every electrode at the same voltage should conduct or that the lowest-potential electrode always wins regardless of distance.

### Scientific boundaries

The animation is a qualitative state model, not a plasma simulation. Any halo representing ionization must be labeled schematic. Playback is slowed dramatically and must not imply real pulse durations. Voltages follow the bench test circuit and are given **from ground** throughout (decided 2026-10-10): the page opens with that schematic, so every number refers to one fixed reference. Node voltages are calculated from the bench resistor values with a first-order tube model (anode = glowing electrode + 147 V) and shown beside the two measured points; the strike and maintaining limits are measured. Timing is not shown: the figures count events, not time.

A single data model should drive the ring, captions, voltage states, and waveform marker. This prevents the illustration and explanation from disagreeing. General behavior can be explained now; the final circuit-specific sequence should be checked against the successful bench setup before release.

## 5. Second centerpiece: the IN-14 nixie explainer

Lead with the question: **Where are all the other digits when one is glowing?**

Show the numeral cathodes as separate layers inside the tube. Let the visitor select 0–9 and watch the chosen cathode highlight within the stack, with a glow surrounding its shape. Pair a front view with an exploded side view; a simple SVG treatment is sufficient for the first version. A rotatable 3D model is optional later.

Explain that the gas glows near the selected cold cathode: the numeral is not an incandescent filament. Show the common anode and external switching concept. The controller selects the digit; the nixie itself does not store and increment a count like a dekatron.

Verify the actual IN-14 stack order before labeling it as mechanically accurate. If the first drawing uses a convenient illustrative order, say so. Keep physical wire geometry visually distinct from the glow effect. Do not introduce multiplexing into the basic explanation unless the implemented display uses it.

End with a concise comparison:

| Property | Nixie | Dekatron |
|---|---|---|
| Visible state | Selected numeral shape | Position of the glow |
| Selection mechanism | External digit driver | Ordered pulses transferring discharge between electrodes |
| Role | Displays an externally selected digit | Holds a powered count and advances or reverses it |
| Stores a value | No: the driver holds the digit | Yes, while powered: the glow position is the value |

## 6. Connect the illustrations to the actual build

Use original project photographs and observations wherever possible. Initial assets can be modest: one clear A101 photograph, a short slow-stepping video, and a schematic electrode diagram. Add the completed instrument's hero photograph later.

Useful evidence to capture during development:

- A guide-voltage scope trace showing one complete count transition.
- A description of the tested drive sequence and voltage reference points.
- Photographs of the nixie numeral stack and selected glowing digits.
- A concise account of what differed between the conceptual diagram and the bench behavior.

The story should progress from observation to mechanism to implementation. Keep routine assembly logs out of the main explanation; curate the few observations that help visitors understand the device. Place high-voltage construction precautions in the build documentation where they are relevant.

## 7. Implementation and repository integration

Use **MkDocs Material and GitHub Pages**, matching the reference repository. Store prose in Markdown and embed small, self-contained JavaScript modules. SVG is the default for electrode diagrams, connection overlays, and simple waveforms; it supports crisp labels and avoids an unnecessary 3D dependency.

Layout as built (2026-10-10). `docs/` keeps the engineering documents; the site has its own source directory so the two never mix:

| Path | Contents |
|---|---|
| `docs/companion_site.md` | This proposal, maintained as the implementation plan |
| `mkdocs.yml`, `pyproject.toml`, `uv.lock` | Site configuration (`docs_dir: website`, strict) and the pinned `docs` dependency group |
| `website/index.md` | Landing page |
| `website/display.md` | Instrument overview |
| `website/how-it-works/dekatron.md` | A101 explanation and interactive figure |
| `website/how-it-works/nixie.md` | IN-14 explanation and interactive figure |
| `website/build.md` and `website/about.md` | Build entry point and sources |
| `website/javascripts/` | Animation state model and view modules |
| `website/stylesheets/` | Site CSS |
| `website/assets/` | Optimized photos, diagrams, video posters, and selected measurements |
| `tools/check_site.py` | Post-build checks: subpath-safe links, alt text, local images |
| `.github/workflows/site.yml`, `deploy-site.yml` | Strict build on every push; manual-only deploy to GitHub Pages |

Keep the site static: no backend or connection to the physical instrument is required. Use local assets and system fonts where practical. Preserve readable text and static diagrams when JavaScript is unavailable. Provide keyboard controls, visible focus, reduced-motion behavior, and explicit pause. Avoid relying on orange glow alone to communicate the active electrode.

Follow the reference deployment pattern: strict site build and link checks in CI; preview and review before the initial public release; subsequent publication from a successfully checked commit. Check GitHub Pages subpath handling explicitly. The site URL is set to `https://kuvychko.github.io/universal-nixie-display/`; deployment is a release step, run by hand when the repository goes public.

Licences follow the repository (decided 2026-10-10): site text, diagrams and photographs under CERN-OHL-P v2, JavaScript and tools under MIT. Third-party datasheets and historical images retain their own rights; link to them rather than assuming they inherit the project license.

## 8. Delivery sequence and acceptance criteria

### Phase 1 — Publishable dekatron explanation

Create the MkDocs scaffold, a modest landing page, the A101 article and interactive ring, a static fallback, and source notes. Use the already-working tube as the physical anchor; completion of the entire display is not a prerequisite.

Complete when a visitor can step through both directions, distinguish guide positions from count positions, and explain why only one stable glow remains. Confirm wraparound in both directions, agreement between all displayed states, readable phone layout, and correct labels and relative potentials. Pass the strict build and link checks.

### Phase 2 — Nixies and the complete instrument

Add the digit-stack explainer, the comparison, and photographs and descriptions of demonstrated instrument features. Complete when selecting a digit makes its physical layer and glow unambiguous, and the published build description matches the actual hardware.

### Phase 3 — Optional depth

Add measured waveforms, a more detailed ignition/transfer view, or a 3D nixie cutaway only when they answer a specific remaining question. Live device control, a general discharge simulator, and a large historical archive are outside the initial scope.

## 9. Sources and verification notes

- **Reference site architecture:** [repository](https://github.com/kuvychko/polyhedra-to-rational-functions/), particularly `README.md`, `PHASE2.md`, `mkdocs.yml`, `docs/index.md`, `docs/research/primer.md`, and `.github/workflows/docs.yml` at the commit above.
- **Original operating explanation:** [1954 Ericsson catalogue transcription](https://electricstuff.co.uk/dekatron.html). Useful for striking versus sustaining voltage, adjacent glow transfer, and guide sequencing; distinguish its tube examples from A101 specifications.
- **A101 implementation example:** [Threeneuron's Dekatron Shield](https://threeneurons.wordpress.com/arduino/dekatron-shield-kit/). A concrete driver and timing reference, not proof that the current project uses the same circuit.
- **Historical account:** [John and Robin Acton, “Dekatron – The Story of an Invention”](https://www.computerconservationsociety.org/resurrection/res61.htm). Supports Acton's 1945 observation at Cossor, the November 1948 Ericsson prototype, the GC10A/B/D tubes and their speeds, the 18 January 1949 provisional patent, the name's origin, copies abroad, mid-1960s displacement, and continued service of installed equipment.
- **Harwell Dekatron computer:** [The National Museum of Computing, “The Harwell Dekatron / WITCH”](https://www.tnmoc.org/witch). Dates (1949 design, 1951 first run, 1973 switch-off, 20 November 2012 reboot), the 720-dekatron store, and the Guinness recognitions.
- **Still to verify during implementation:** A101 production history (manufacturer and years), primary A101 and IN-14 datasheets, exact electrode and numeral-stack geometry, and the final project's guide waveforms. Do not publish illustrative parameters as measured device specifications.

## 10. Going public

The repository goes public and the site goes live together, when the bench-test video is shared
(decided 2026-10-11; confirmed 2026-10-18). The site must be ready before the link is.

**Before flipping the repository** (status as of 2026-10-18):

| Check | Status |
|---|---|
| History holds no datasheets, vendor models or other third-party files that may not be redistributed (`docs/datasheets/` and `hardware/*/simulation/models/vendor/` were never committed) | Done |
| No secrets or large files in history | Done |
| `hardware/dekatron/Cart_Oct08_0432PM.xls` (the frozen Mouser order, cited by `hardware.md` and `gen_schematics.py`) holds part numbers, quantities and prices only: no name, address or account | Done: keep |
| Commits carry the author's e-mail address; it becomes public with the history | Accepted by the author (2026-10-11) |
| Safety warning and at-your-own-risk disclaimer: README, bring-up bench test, site (home, dekatron page, build page, Safety page) | Done |
| Licences present (`LICENSE`, `LICENSE-CERN-OHL-P-2.0`, `LICENSE-MIT`), and `LICENSE` maps every directory including `website/` (content CERN-OHL-P, `website/javascripts/` MIT) | Done (`website/` added 2026-10-18) |
| Photographs carry no EXIF or GPS data; on the PCBWay label only the QR code is blurred. The job number on the labels and the board silkscreen is released | Done; accepted by the author (2026-10-18) |
| README repository layout marks the directories that are still empty as planned | Done (2026-10-18) |
| README acknowledgement of PCBWay's sponsorship, without claims about board quality until boards arrive | Done; updated 2026-10-18 after the boards arrived (2026-10-15): packaging and edge finish noted with photos, electrical results left to bring-up |
| Bench-test video on YouTube, linked from the site (below) | Open: video not yet made |
| Photograph of the A101 socket housing and tube shroud assembly (`enclosure/dekatron-bench-test/`) | Open: photo to come from the author |
| Strict build and `tools/check_site.py` pass; external links resolve | Done (2026-10-18; the CCS and Printables pages answer scripted requests with 403: check them in a browser) |
| Site read-through after the last content change | Before release |

**Release sequence:**

1. Final local check: `uv run --group docs mkdocs build --strict` and `uv run python tools/check_site.py`; preview with `mkdocs serve`.
2. Make the repository public (Settings → General → Danger Zone).
3. Run **Deploy site** (Actions → Deploy site → Run workflow). It builds, checks and pushes `gh-pages`.
4. Settings → Pages → Source: deploy from the `gh-pages` branch, root. Wait for the first Pages build.
5. Check the live site at https://kuvychko.github.io/universal-nixie-display/: every page loads, figures work, the subpath is right, and the repository links listed by `check_site.py` now resolve.
6. Set the repository's About website to the site URL.
7. Share the video with links to the site and the repository.

**The video** (decided 2026-10-11): the author uploads it to YouTube, and the site links to it rather than embedding it, so the site still makes no third-party requests. A still frame from the video, saved as a small image in `website/assets/`, can act as the link on the home page and the dekatron page. The caption says what is shown, the supply voltage and the date.

## 11. Growing with the project

The site follows the build, one phase at a time, and only ever describes what has been demonstrated. Each phase gate in the [project plan](project_plan.md) is also a site update:

| Project phase | What the site gains |
|---|---|
| Now: A101 on the bench (Phase 1 bench test) | Dekatron explainer, bench circuit, bench-test video, history and speed survey |
| 1D: dekatron controller board brought up | Board photos and a short build note; measured waveforms (guide drive, index) replacing calculated values where they exist; homing and the exercise-or-dark behaviour shown; a first note on PCB quality, now that the boards are in hand |
| 2: Nixie supply and six-tube mount | The IN-14 explainer and its numeral-stack figure (§5), with the stack order checked against a tube; Nixie photos |
| 3: ESP32 interface and host commands | "The display" page fills in: modes that work, the touchscreen, the encoder, and the USB command set (linked, not duplicated) |
| 4: Enclosure | Photographs of the finished object; the home page hero becomes the instrument |
| 5: Rev A release | Build and investigate becomes a real reproduction guide, pointing at the released files |

Rules for every update:

- **One status, three places.** A phase change updates the README Status table, the home page status box, and a dated entry on a short **Progress** page (newest first; to be added with the first update after go-live), so a visitor can see what changed and when.
- **Demonstrated only.** A feature appears on the site once it works on real hardware, with a photo, video or measurement; plans are labelled as plans.
- **Measured beats calculated.** When a measurement replaces a calculated value on a page, say so, and keep the calculation only if the comparison teaches something.
- **Keep the strict build green.** Every content change passes `mkdocs build --strict` and `tools/check_site.py`; the Site workflow checks each push.

The intended result is a small, durable explanation built around a real object: visitors can see the tubes working, manipulate a faithful conceptual model, and understand the engineering that connects the two.
