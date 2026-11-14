// BLE Floorplan: what the card and the panel share. The texts, the drawing of
// the floor plan with its scanners and trackers, the hover tooltip and the
// icons. The plan comes from the integration over the WebSocket API; this
// module only turns it into SVG.
export const VERSION = "0.19.2";

export const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);

export const COLORS = ["#e8590c", "#1c7ed6", "#2f9e44", "#ae3ec9", "#f59f00", "#0c8599"];

// The panel in the sidebar
export const PANEL_PATH = "/ble-floorplan";

const TEXTS = {
  en: {
    title: "BLE Floorplan", rooms: "Rooms", scanners: "Scanners", trackers: "Trackers",
    labels: "Labels", rotate: "Rotate the plan by 90°", settings: "Settings", close: "Close", back: "Back",
    edit: "Edit", move: "Move", save: "Save", cancel: "Cancel", remove: "Remove", measure: "Calibration run",
    start: "Start run", stop: "Stop run", circles: "Circles", tracker: "Tracker", scanner: "Scanner",
    room: "Room", count: "scanners", notSeen: "not seen", ignored: "ignored", position: "Position",
    height: "Height", refPower: "Reference power", default: "default", offset: "Offset",
    pairs: "Pair corrections", none: "none", hears: "Hears", heardBy: "Heard by",
    system: "System details", sysUptime: "Running for", sysLastStart: "Last start", sysUnavailable: "unavailable",
    sysSignal: "Wi-Fi signal", sysFirmware: "Firmware", sysUpdate: "update to {v} available",
    sysLastSeen: "Last received", sysAgo: "{t} ago", sysInRange: "Devices in range", sysInRangeHint: "last minute",
    sysMode: "Scan mode", sysActive: "active", sysPassive: "passive", sysSlots: "Connection slots",
    sysSlotsUsed: "{used} of {n} in use", sysReceiveOnly: "none, receive only", sysDevice: "Device",
    sysOpenDevice: "Open in Home Assistant", sysNotInHa: "not in Home Assistant",
    offline: "not reachable", offlineHint: "This scanner has received nothing for over a minute. Is it powered and connected to Home Assistant?",
    hintMeasure: "Tap the plan where the tracker lies, then start.",
    hintMove: "Tap the plan where the scanner is, or drag it; then save.", runs: "Runs", duration: "Length",
    delete: "Delete", fitExponent: "Fit the exponent too", compute: "Compute", apply: "Apply",
    preview: "Proposal", now: "now", proposed: "proposed", obs: "observations", exponent: "Exponent",
    rms: "RMS error (dB)", applied: "Applied.", saved: "Saved.", display: "Display", engine: "Engine",
    motion: "Motion", roomRules: "Rooms", robust: "Robust weights", attenuation: "Path loss exponent",
    refDefault: "Default reference power (dBm)", maxDistance: "Largest distance (m)",
    smoothing: "Smoothing (s)", minMove: "Dead zone (m)", clamp: "Keep trackers in the rooms",
    clampOutdoor: "Outdoor areas count as rooms", maxSpeed: "Top speed (m/s, 0 = none)",
    jumpDistance: "Jump distance (m, 0 = off)", jumpConfirm: "Jump confirmation (s)",
    walls: "Through walls only at doors", awaySeconds: "Away after (s) without a sighting", roomHold: "Hold time (s)",
    roomMargin: "Wall margin (m)", robustResidual: "Residual (m, 0 = off)",
    calibration: "Calibration", noRuns: "No runs yet.", running: "running",
    samples: "samples", rotation: "Rotation",
    noPlan: "No floor plan yet: an administrator sets it up in BLE Floorplan in the sidebar.",
    notLoaded: "BLE Floorplan is not set up.", unknown: "–",
    plan: "Floor plan", add: "Add", name: "Name", allOnPlan: "Every one Home Assistant knows is on the plan.",
    layoutHint: "Rooms as rectangles (x, y, w, h) or polygons (points), zones, outdoor areas and openings, in metres; area links a room to an area of Home Assistant. See the README.",
    confirmRemove: "Take {name} off the plan?", startHere: "No rooms yet: write the floor plan on the right, then add scanners and trackers.",
    timeline: "Timeline", live: "LIVE", backToLive: "Back to live", play: "Play", pause: "Pause",
    speed: "Speed", zoomIn: "Zoom in", zoomOut: "Zoom out", fit: "Whole plan", historyDays: "Days kept (0 = off)",
    timelineHint: "Keeps where the trackers were in Home Assistant's storage, at most 30 days.",
    timelineOff: "The timeline is off. Set the days to keep in the settings.",
    runOne: "1 run", runMany: "{n} runs", fitSaved: "Saved from {runs}: reference power {ref} dBm (was {old}), corrections {pairs}. Error {rmsOld} → {rmsNew} dB.",
    fitNone: "Nothing saved: no scanner heard the tracker at least 3 times. Let the run go on longer.",
    calHint: "A stopped or deleted run saves the tracker's reference power and its correction per scanner at once.",
    advanced: "Scanner offsets and exponent",
    advancedHint: "Compute and Apply fit the offsets of the scanners and the exponent from all runs, for all trackers.",
    newRun: "New run", pickTracker: "Tracker", runAt: "At",
    addScanner: "Add scanner", addTracker: "Add tracker", trackerCount: "{n} trackers", seenBy: "{n} scanners",
    planSaved: "Floor plan saved.",
    tabPlan: "Floor plan", tabScanners: "Scanners", tabTrackers: "Trackers", tabCalibration: "Calibration",
    tabTimeline: "Timeline", tabSettings: "Settings", menu: "Menu",
    about: "BLE Floorplan {version}", aboutCommit: "BLE Floorplan {version} · commit {commit}",
    asOf: "As of {time}", refresh: "Refresh", integrationSettings: "Settings",
    tabCoverage: "Coverage", coverage: "Coverage", covMode: "Map", covModel: "Model", covMeasured: "Measured",
    covDefault: "Default values", covAll: "All trackers",
    covGood: "Good: 3 or more scanners, around the place", covFair: "Fair: 2 scanners", covPoor: "Poor: 1 scanner or none",
    covUp: "Better with the probe scanners",
    covModelHint: "Predicted from the scanners' places, offsets and the path loss model. A scanner counts when it should receive at least {rssi} dBm.",
    covMeasuredHint: "What the scanners received where the trackers really were, over the days the timeline keeps. Grey: no tracker was there long enough.",
    covSummary: "{good} % of the area good, {fair} % fair, {poor} % poor.",
    probes: "Probe scanners", probeHint: "Tap the plan to place a scanner that is only thought of (up to 5, 1 m high). Nothing is saved.",
    probeOffset: "Probe scanners get the median offset of the scanners on the plan ({offset} dB).",
    removeAll: "Remove all", covOff: "The measurement records only while the timeline is on: set the days it keeps in the settings.",
    covDays: "{n} days since {first}", covNone: "No measurement yet.", covReset: "Start anew",
    covResetAsk: "Forget the whole measurement? Useful after a scanner moved or came in.",
    covRooms: "Rooms", covGoodScanners: "Good scanners", covLevel: "Level", covTime: "Time", covMiss: "Miss",
    covCellModel: "{good} scanners good · HDOP {hdop}", covCellMeasured: "Ø {good} scanners good · miss {miss} m · {time}",
  },
  de: {
    title: "BLE-Grundriss", rooms: "Räume", scanners: "Scanner", trackers: "Tracker",
    labels: "Beschriftung", rotate: "Grundriss um 90° drehen", settings: "Einstellungen", close: "Schließen", back: "Zurück",
    edit: "Bearbeiten", move: "Verschieben", save: "Speichern", cancel: "Abbrechen", remove: "Entfernen", measure: "Messlauf",
    start: "Messlauf starten", stop: "Messlauf beenden", circles: "Kreise", tracker: "Tracker", scanner: "Scanner",
    room: "Raum", count: "Scanner", notSeen: "nicht gesehen", ignored: "ignoriert", position: "Position",
    height: "Höhe", refPower: "Referenzleistung", default: "Standard", offset: "Offset",
    pairs: "Korrektur je Paar", none: "keine", hears: "Hört", heardBy: "Gehört von",
    system: "Systemdetails", sysUptime: "Läuft seit", sysLastStart: "Letzter Start", sysUnavailable: "nicht verfügbar",
    sysSignal: "WLAN-Signal", sysFirmware: "Firmware", sysUpdate: "Update auf {v} verfügbar",
    sysLastSeen: "Zuletzt empfangen", sysAgo: "vor {t}", sysInRange: "Geräte in Reichweite", sysInRangeHint: "letzte Minute",
    sysMode: "Scanmodus", sysActive: "aktiv", sysPassive: "passiv", sysSlots: "Verbindungsplätze",
    sysSlotsUsed: "{used} von {n} belegt", sysReceiveOnly: "keine, nur Empfang", sysDevice: "Gerät",
    sysOpenDevice: "In Home Assistant öffnen", sysNotInHa: "nicht in Home Assistant",
    offline: "nicht erreichbar", offlineHint: "Dieser Scanner hat seit über einer Minute nichts empfangen. Hat er Strom und ist er mit Home Assistant verbunden?",
    hintMeasure: "Auf den Grundriss tippen, wo der Tracker liegt, dann starten.",
    hintMove: "Auf den Grundriss tippen, wo der Scanner hängt, oder ihn ziehen; dann speichern.", runs: "Messläufe", duration: "Dauer",
    delete: "Löschen", fitExponent: "Exponent mitschätzen", compute: "Berechnen", apply: "Übernehmen",
    preview: "Vorschlag", now: "jetzt", proposed: "neu", obs: "Beobachtungen", exponent: "Exponent",
    rms: "RMS-Fehler (dB)", applied: "Übernommen.", saved: "Gespeichert.", display: "Anzeige", engine: "Engine",
    motion: "Bewegung", roomRules: "Räume", robust: "Robuste Gewichte", attenuation: "Pfadverlust-Exponent",
    refDefault: "Referenzleistung Standard (dBm)", maxDistance: "Größter Abstand (m)",
    smoothing: "Glättung (s)", minMove: "Totzone (m)", clamp: "Tracker in den Räumen halten",
    clampOutdoor: "Außenflächen zählen als Räume", maxSpeed: "Höchstgeschwindigkeit (m/s, 0 = keine)",
    jumpDistance: "Sprungweite (m, 0 = aus)", jumpConfirm: "Sprung-Bestätigung (s)",
    walls: "Wände nur an Türen passieren", awaySeconds: "Abwesend nach (s) ohne Empfang", roomHold: "Haltezeit (s)",
    roomMargin: "Wandabstand (m)", robustResidual: "Residuum (m, 0 = aus)",
    calibration: "Kalibrierung", noRuns: "Noch keine Messläufe.", running: "läuft",
    samples: "Samples", rotation: "Drehung",
    noPlan: "Noch kein Grundriss: Eine Administratorin oder ein Administrator richtet ihn in BLE Floorplan in der Seitenleiste ein.",
    notLoaded: "BLE Floorplan ist nicht eingerichtet.", unknown: "–",
    plan: "Grundriss", add: "Hinzufügen", name: "Name", allOnPlan: "Alle, die Home Assistant kennt, sind auf dem Plan.",
    layoutHint: "Räume als Rechteck (x, y, w, h) oder Polygon (points), Zonen, Außenflächen und Öffnungen, in Metern; area verknüpft einen Raum mit einem Bereich von Home Assistant. Siehe README.",
    confirmRemove: "{name} vom Plan nehmen?", startHere: "Noch keine Räume: rechts den Grundriss eintragen, dann Scanner und Tracker hinzufügen.",
    timeline: "Verlauf", live: "LIVE", backToLive: "Zurück zu live", play: "Abspielen", pause: "Anhalten",
    speed: "Tempo", zoomIn: "Vergrößern", zoomOut: "Verkleinern", fit: "Ganzer Grundriss", historyDays: "Tage aufbewahren (0 = aus)",
    timelineHint: "Speichert, wo die Tracker waren, im Speicher von Home Assistant, höchstens 30 Tage.",
    timelineOff: "Der Verlauf ist aus. In den Einstellungen festlegen, wie viele Tage er aufbewahrt wird.",
    runOne: "1 Messlauf", runMany: "{n} Messläufen", fitSaved: "Gespeichert aus {runs}: Referenzleistung {ref} dBm (vorher {old}), Korrekturen {pairs}. Fehler {rmsOld} → {rmsNew} dB.",
    fitNone: "Nichts gespeichert: Kein Scanner hat den Tracker mindestens 3-mal gehört. Den Messlauf länger laufen lassen.",
    calHint: "Ein beendeter oder gelöschter Messlauf speichert sofort die Referenzleistung des Trackers und seine Korrektur je Scanner.",
    advanced: "Scanner-Offsets und Exponent",
    advancedHint: "Berechnen und Übernehmen passen aus allen Messläufen die Offsets der Scanner und den Exponenten an, für alle Tracker.",
    newRun: "Neuer Messlauf", pickTracker: "Tracker", runAt: "Ort",
    addScanner: "Scanner hinzufügen", addTracker: "Tracker hinzufügen", trackerCount: "{n} Tracker", seenBy: "{n} Scanner",
    planSaved: "Grundriss gespeichert.",
    tabPlan: "Grundriss", tabScanners: "Scanner", tabTrackers: "Tracker", tabCalibration: "Kalibrierung",
    tabTimeline: "Verlauf", tabSettings: "Einstellungen", menu: "Menü",
    about: "BLE Floorplan {version}", aboutCommit: "BLE Floorplan {version} · Commit {commit}",
    asOf: "Stand {time}", refresh: "Aktualisieren", integrationSettings: "Einstellungen",
    tabCoverage: "Abdeckung", coverage: "Abdeckung", covMode: "Karte", covModel: "Modell", covMeasured: "Gemessen",
    covDefault: "Standardwerte", covAll: "Alle Tracker",
    covGood: "Gut: 3 oder mehr Scanner, rundherum verteilt", covFair: "Mittel: 2 Scanner", covPoor: "Schwach: 1 Scanner oder keiner",
    covUp: "Besser mit den Probe-Scannern",
    covModelHint: "Berechnet aus Standorten, Offsets und dem Pfadverlust-Modell der Scanner. Ein Scanner zählt, wenn er mindestens {rssi} dBm empfangen müsste.",
    covMeasuredHint: "Was die Scanner dort empfangen haben, wo die Tracker wirklich waren, über die Tage, die der Verlauf aufbewahrt. Grau: Dort war kein Tracker lange genug.",
    covSummary: "{good} % der Fläche gut, {fair} % mittel, {poor} % schwach.",
    probes: "Probe-Scanner", probeHint: "Auf den Grundriss tippen, um einen gedachten Scanner zu setzen (bis zu 5, 1 m hoch). Gespeichert wird nichts.",
    probeOffset: "Probe-Scanner bekommen den mittleren Offset der Scanner auf dem Plan ({offset} dB).",
    removeAll: "Alle entfernen", covOff: "Die Messung zeichnet nur auf, solange der Verlauf an ist: In den Einstellungen festlegen, wie viele Tage er aufbewahrt.",
    covDays: "{n} Tage seit {first}", covNone: "Noch keine Messung.", covReset: "Neu beginnen",
    covResetAsk: "Die ganze Messung vergessen? Sinnvoll, nachdem ein Scanner umgezogen oder dazugekommen ist.",
    covRooms: "Räume", covGoodScanners: "Gute Scanner", covLevel: "Stufe", covTime: "Zeit", covMiss: "Abweichung",
    covCellModel: "{good} Scanner gut · HDOP {hdop}", covCellMeasured: "Ø {good} Scanner gut · Abweichung {miss} m · {time}",
  },
};

export const texts = (hass) => TEXTS[(hass?.language || "en").slice(0, 2)] || TEXTS.en;

// Numbers to read, in the language of Home Assistant
export const formatter = (hass) => {
  const lang = hass?.language || "en";
  return (v, d = 1) =>
    Number.isFinite(v) ? v.toLocaleString(lang, { minimumFractionDigits: d, maximumFractionDigits: d }) : "–";
};

// Numbers in a field: the language of Home Assistant; typing takes a point or a comma
export const fieldNumber = (hass, value) =>
  Number.isFinite(value) ? value.toLocaleString(hass?.language || "en", { useGrouping: false, maximumFractionDigits: 3 }) : "";

export const numOrNull = (v) => {
  const n = parseFloat(String(v).replace(",", "."));
  return Number.isFinite(n) ? n : null;
};

// Rooms are rectangles (x, y, w, h) or polygons (points), all in metres
export const roomPoints = (r) =>
  r.points || [[r.x, r.y], [r.x + r.w, r.y], [r.x + r.w, r.y + r.h], [r.x, r.y + r.h]];

const roomLabelPos = (r) => {
  if (r.lx !== undefined) return [r.lx, r.ly];
  const p = roomPoints(r);
  return [p.reduce((a, q) => a + q[0], 0) / p.length, p.reduce((a, q) => a + q[1], 0) / p.length];
};

export const computeBounds = (plan) => {
  let maxX = 0;
  let maxY = 0;
  for (const r of plan?.rooms || []) {
    for (const [x, y] of roomPoints(r)) {
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  }
  return { w: maxX || 1, h: maxY || 1 };
};

export const trackerColor = (plan, key) => {
  const i = (plan?.trackers || []).findIndex((t) => t.key === key);
  return COLORS[(i < 0 ? 0 : i) % COLORS.length];
};

// What each tracker and each scanner shows: position, readings, colour, whether the scanner is silent
export const planInfo = (plan, positions, scannerPos, offline = []) => {
  const info = { trackers: {}, scanners: {} };
  for (const s of plan.scanners) {
    info.scanners[s.key] = { name: s.name, p: scannerPos(s), z: s.z, offline: offline.includes(s.key), trackers: [] };
  }
  plan.trackers.forEach((tr, i) => {
    const color = COLORS[i % COLORS.length];
    const pos = positions[tr.key] || {};
    const readings = pos.readings || {};
    const seen = pos.x != null && pos.y != null;
    info.trackers[tr.key] = { name: tr.name, color, readings, p: seen ? pos : null, room: pos.room };
    for (const s of plan.scanners) {
      const r = readings[s.key] || {};
      info.scanners[s.key].trackers.push({ key: tr.key, name: tr.name, color, d: r.distance ?? null, rssi: r.rssi, used: !!r.used });
    }
  });
  return info;
};

// Rotation and labels: per browser, under a key of the card or of the panel
export const loadRot = (key, fallback) => {
  let v = null;
  try {
    v = window.localStorage.getItem(key);
  } catch (e) {
    // no storage
  }
  const r = v === null ? fallback : parseInt(v, 10);
  return [0, 90, 180, 270].includes(r) ? r : 0;
};

export const loadLabels = (key, fallback) => {
  try {
    const v = JSON.parse(window.localStorage.getItem(key) || "null");
    if (v && typeof v === "object") return { ...fallback, ...v };
  } catch (e) {
    // no storage or bad content
  }
  return fallback;
};

export const keep = (key, value) => {
  try {
    window.localStorage.setItem(key, typeof value === "string" ? value : JSON.stringify(value));
  } catch (e) {
    // no storage
  }
};

// Turn a text back at its anchor so it stays readable on the rotated plan
const upright = (rot, x, y, extra = 0) => (extra - rot ? ` transform="rotate(${extra - rot} ${x} ${y})"` : "");

export const dotHtml = (tr, i, pos, { rot, labels, open }) => {
  const color = COLORS[i % COLORS.length];
  return (
    `<g class="tracker${open ? " open" : ""}" data-key="${esc(tr.key)}"><circle cx="${pos.x}" cy="${pos.y}" r="0.28" fill="${color}"/>` +
    (labels.trackers
      ? `<text class="tlabel" x="${pos.x}" y="${pos.y - 0.42}" fill="${color}"${upright(rot, pos.x, pos.y)}>${esc(tr.name)}</text>`
      : "") +
    `</g>`
  );
};

// The floor plan as SVG. `marks` goes above the rooms and below the scanners
// (true positions, run positions), `trails` below the trackers.
// The whole plan on screen, in the units of the plan: rotated, with a margin
const fullBox = (B, rot) => {
  const pad = 0.9;
  const landscape = rot % 180 !== 0;
  return [-pad, -pad, (landscape ? B.h : B.w) + 2 * pad, (landscape ? B.w : B.h) + 2 * pad];
};

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

// The part of the plan in view. Zoomed in (view.k > 1), the box takes the
// shape of the map (view.a = width / height), so a zoomed plan fills it,
// and its centre stays where the plan is.
export const viewBox = (B, rot, view) => {
  let [x, y, w, h] = fullBox(B, rot);
  if (!view || view.k <= 1) return [x, y, w, h];
  if (view.a > 0) {
    if (w / h < view.a) {
      x -= (h * view.a - w) / 2;
      w = h * view.a;
    } else {
      y -= (w / view.a - h) / 2;
      h = w / view.a;
    }
  }
  const vw = w / view.k;
  const vh = h / view.k;
  view.cx = clamp(view.cx, x + vw / 2, x + w - vw / 2);
  view.cy = clamp(view.cy, y + vh / 2, y + h - vh / 2);
  return [view.cx - vw / 2, view.cy - vh / 2, vw, vh];
};

export const planSvg = (plan, o) => {
  const B = o.bounds;
  const rot = o.rot;
  // Rotate the plan as a whole, turn every text back at its anchor so it stays readable
  const planTf = {
    0: "",
    90: `rotate(90) translate(0 ${-B.h})`,
    180: `rotate(180) translate(${-B.w} ${-B.h})`,
    270: `rotate(270) translate(${-B.w} 0)`,
  }[rot];
  const rooms = plan.rooms
    .map((r) => {
      const cls = r.zone ? "zone" : r.outdoor ? "room outdoor" : "room";
      const [lx, ly] = roomLabelPos(r);
      const fs = r.fs ? ` style="font-size:${r.fs}px"` : "";
      // A room's own `rot` is relative to the plan; on screen the label stays
      // horizontal or reads from bottom to top
      const screenRot = r.rot ? ((((r.rot + rot) % 180) + 180) % 180 === 0 ? 0 : -90) : 0;
      const label = r.label === false || !o.labels.rooms || !r.name
        ? ""
        : `<text class="rlabel" x="${lx}" y="${ly}"${fs}${upright(rot, lx, ly, screenRot)}>${esc(r.name)}</text>`;
      const shape = r.points
        ? `<polygon class="${cls}" points="${r.points.map((p) => p.join(",")).join(" ")}"/>`
        : `<rect class="${cls}" x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}"/>`;
      return shape + label;
    })
    .join("");
  // Doors and open passages: break the wall line, mark them thin and dashed
  const openings = (plan.openings || [])
    .map(
      (w) =>
        `<line class="gap" x1="${w[0]}" y1="${w[1]}" x2="${w[2]}" y2="${w[3]}"/>` +
        `<line class="opening" x1="${w[0]}" y1="${w[1]}" x2="${w[2]}" y2="${w[3]}"/>`
    )
    .join("");
  let circles = "";
  const dots = [];
  plan.trackers.forEach((tr, i) => {
    const pos = o.positions[tr.key] || {};
    if (pos.x == null || pos.y == null) return;
    dots.push(dotHtml(tr, i, pos, { rot, labels: o.labels, open: o.openTracker === tr.key }));
    if (o.circles === tr.key) {
      const readings = pos.readings || {};
      circles += plan.scanners
        .filter((s) => readings[s.key]?.used)
        .map((s) => {
          const [x, y] = o.scannerPos(s);
          return `<circle class="range" cx="${x}" cy="${y}" r="${readings[s.key].distance}" stroke="${COLORS[i % COLORS.length]}"/>`;
        })
        .join("");
    }
  });
  const scanners = plan.scanners
    .map((s) => {
      const [x, y] = o.scannerPos(s);
      const cls = `scanner${o.movable === s.key ? " movable" : ""}${o.openScanner === s.key ? " open" : ""}` +
        `${o.offline?.includes(s.key) ? " offline" : ""}`;
      return (
        `<g class="${cls}" data-key="${esc(s.key)}">` +
        `<rect x="${x - 0.22}" y="${y - 0.22}" width="0.44" height="0.44" rx="0.08"/>` +
        (o.labels.scanners ? `<text class="slabel" x="${x}" y="${y + 0.62}"${upright(rot, x, y)}>${esc(s.name)}</text>` : "") +
        `</g>`
      );
    })
    .join("");
  return `<svg viewBox="${viewBox(B, rot, o.view).join(" ")}" preserveAspectRatio="${o.align || "xMidYMin"} meet">` +
    `<g id="plan" transform="${planTf}">${rooms}${openings}${circles}${o.marks || ""}<g id="trails">${o.trails || ""}</g>` +
    `${scanners}<g id="dots">${dots.join("")}</g></g></svg>`;
};

// A crosshair at a true position: dashed while it is chosen, solid while a run is going
export const crosshair = (x, y, live) =>
  `<g class="truepos${live ? " live" : ""}"><circle cx="${x}" cy="${y}" r="0.3"/>` +
  `<line x1="${x - 0.45}" y1="${y}" x2="${x + 0.45}" y2="${y}"/>` +
  `<line x1="${x}" y1="${y - 0.45}" x2="${x}" y2="${y + 0.45}"/></g>`;

// The point of the plan under the pointer, inside the plan
export const toPlan = (root, e, bounds) => {
  const plan = root.getElementById("plan");
  const pt = plan.ownerSVGElement.createSVGPoint();
  pt.x = e.clientX;
  pt.y = e.clientY;
  const p = pt.matrixTransform(plan.getScreenCTM().inverse());
  return [Math.min(Math.max(p.x, 0), bounds.w), Math.min(Math.max(p.y, 0), bounds.h)];
};

export const snap = (v) => Math.round(v * 20) / 20;

// The facts of a tracker or a scanner, for the tooltip and the card's info box
export const detailHtml = (info, kind, key, t, fmt) => {
  if (kind === "tracker") {
    const tr = info.trackers[key];
    if (!tr) return "";
    const rows = Object.values(info.scanners)
      .map((s) => {
        const e = s.trackers.find((x) => x.key === key) || {};
        const status = s.offline ? t.offline : e.d == null ? t.notSeen : e.used ? "" : t.ignored;
        return `<tr class="${e.used ? "" : "ign"}"><td>${esc(s.name)}</td><td class="num">${e.d == null ? "" : `${fmt(e.d)} m`}</td>` +
          `<td class="num">${e.rssi == null ? "" : `${fmt(e.rssi, 0)} dBm`}</td><td>${status}</td></tr>`;
      })
      .join("");
    const posText = tr.p
      ? `${esc(tr.room ?? t.unknown)} (${fmt(tr.p.x)} / ${fmt(tr.p.y)} m) · ${tr.p.scanner_count} ${t.count}`
      : t.notSeen;
    return `<b><span class="dot" style="background:${tr.color}"></span>${esc(tr.name)}</b><div class="sub">${t.position}: ${posText}</div><table>${rows}</table>`;
  }
  const s = info.scanners[key];
  if (!s) return "";
  const rows = s.trackers
    .map(
      (e) =>
        `<tr class="${e.used ? "" : "ign"}"><td><span class="dot" style="background:${e.color}"></span>${esc(e.name)}</td>` +
        `<td class="num">${e.d == null ? "" : `${fmt(e.d)} m`}</td><td class="num">${e.rssi == null ? "" : `${fmt(e.rssi, 0)} dBm`}</td>` +
        `<td>${e.d == null ? t.notSeen : e.used ? "" : t.ignored}</td></tr>`
    )
    .join("");
  const off = s.offline ? `<div class="sub offline">${esc(t.offline)}</div>` : "";
  return `<b>${esc(s.name)}</b>${off}<div class="sub">${t.position} ${fmt(s.p[0])} / ${fmt(s.p[1])} m · ${t.height} ${fmt(s.z)} m</div><table>${rows}</table>`;
};

// Tooltip next to the pointer over a scanner or a tracker; not on touch
export const bindHover = (map, tip, html) => {
  if (!map || !tip) return;
  let over = null;
  const place = (e) => {
    const r = map.getBoundingClientRect();
    let x = e.clientX - r.left + 14;
    const y = e.clientY - r.top + 14;
    if (x + tip.offsetWidth > r.width) x = Math.max(0, e.clientX - r.left - tip.offsetWidth - 14);
    tip.style.left = `${x}px`;
    tip.style.top = `${y}px`;
  };
  map.addEventListener("pointerover", (e) => {
    const g = e.target.closest?.(".scanner, .tracker");
    if (!g || e.pointerType === "touch") return;
    over = { kind: g.classList.contains("scanner") ? "scanner" : "tracker", key: g.dataset.key };
    tip.innerHTML = html(over.kind, over.key);
    tip.style.display = tip.innerHTML ? "block" : "none";
    place(e);
  });
  map.addEventListener("pointermove", (e) => {
    if (over) place(e);
  });
  map.addEventListener("pointerout", (e) => {
    const g = e.target.closest?.(".scanner, .tracker");
    if (!g || g.contains(e.relatedTarget)) return;
    over = null;
    tip.style.display = "none";
  });
  // Live data: the tooltip follows the readings while the pointer stays
  return () => {
    if (over) tip.innerHTML = html(over.kind, over.key);
  };
};

// Go to a page of Home Assistant without reloading it
export const navigate = (path) => {
  window.history.pushState(null, "", path);
  window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
};

// Zoom and pan of the plan in a map: pinch, wheel (on the card with Ctrl, as a
// trackpad pinch sends it), the buttons in the corner; drag pans while
// zoomed in. The map stays, the plan in it is redrawn every second: the view
// lives here and goes into every drawing (planSvg's `view`).
export class PlanZoom {
  // geom() returns {bounds, rot}; wheel: zoom with the plain wheel too
  constructor({ geom, texts, wheel }) {
    this.geom = geom;
    this.texts = texts;
    this.wheel = wheel;
    this.view = null;
  }

  // Bind to a (new) map element
  attach(map) {
    this.map = map;
    this.pointers = new Map();
    this.gesture = null;
    const btns = document.createElement("div");
    btns.className = "zoombtns";
    map.append(btns);
    this.btns = btns;
    this._buttons();
    btns.addEventListener("click", (e) => {
      e.stopPropagation();
      const b = e.target.closest("[data-zoom]");
      if (!b || b.disabled) return;
      if (b.dataset.zoom === "fit") this.reset();
      else this.zoomBy(b.dataset.zoom === "in" ? 1.5 : 1 / 1.5);
    });
    map.addEventListener("wheel", (e) => this._wheel(e), { passive: false });
    map.addEventListener("pointerdown", (e) => this._down(e));
    map.addEventListener("pointermove", (e) => this._move(e));
    for (const ev of ["pointerup", "pointercancel"]) map.addEventListener(ev, (e) => this._up(e));
    // The click that ends a pan or a pinch selects nothing
    map.addEventListener("click", (e) => {
      if (this.moved) {
        e.stopPropagation();
        e.preventDefault();
        this.moved = false;
      }
    }, true);
  }

  reset() {
    this.view = null;
    this._apply();
  }

  zoomBy(f) {
    const b = this._box();
    if (b) this._zoomAt([b.x + b.width / 2, b.y + b.height / 2], (this.view?.k || 1) * f);
  }

  _svg() {
    return this.map?.querySelector("svg:not(.mdi)");
  }

  _box() {
    return this._svg()?.viewBox.baseVal;
  }

  // Screen point → plan view units
  _pt(x, y) {
    const svg = this._svg();
    const pt = svg.createSVGPoint();
    pt.x = x;
    pt.y = y;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    return [p.x, p.y];
  }

  // Plan units per screen pixel
  _scale() {
    return 1 / (this._svg().getScreenCTM()?.a || 1);
  }

  _zoomAt(p, k) {
    const svg = this._svg();
    const b = this._box();
    if (!svg || !b) return;
    const k0 = this.view?.k || 1;
    const k1 = clamp(k, 1, 10);
    if (k1 <= 1.001) {
      this.reset();
      return;
    }
    const r = svg.getBoundingClientRect();
    const c = [b.x + b.width / 2, b.y + b.height / 2];
    this.view = { k: k1, cx: p[0] + ((c[0] - p[0]) * k0) / k1, cy: p[1] + ((c[1] - p[1]) * k0) / k1, a: r.width / r.height };
    this._apply();
  }

  _panBy(dx, dy) {
    if (!this.view) return;
    const s = this._scale();
    this.view.cx -= dx * s;
    this.view.cy -= dy * s;
    this._apply();
  }

  _apply() {
    const svg = this._svg();
    if (svg) {
      const { bounds, rot } = this.geom();
      svg.setAttribute("viewBox", viewBox(bounds, rot, this.view).join(" "));
    }
    this.map?.classList.toggle("zoomed", !!this.view);
    this._buttons();
  }

  _buttons() {
    if (!this.btns) return;
    const t = this.texts();
    const k = this.view?.k || 1;
    const btn = (z, name, title, off) =>
      iconButton(name, title, `data-zoom="${z}"${off ? " disabled" : ""}`);
    const html = btn("in", "plus", t.zoomIn, k >= 10) + btn("out", "minus", t.zoomOut, k <= 1) +
      (this.view ? btn("fit", "fit", t.fit, false) : "");
    if (this.btns.innerHTML !== html) this.btns.innerHTML = html;
  }

  _wheel(e) {
    if (!this._svg() || (!this.wheel && !e.ctrlKey)) return;
    e.preventDefault();
    // A trackpad pinch comes as small steps with Ctrl
    const f = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015));
    this._zoomAt(this._pt(e.clientX, e.clientY), (this.view?.k || 1) * f);
  }

  _down(e) {
    if (!this._svg() || e.target.closest(".zoombtns, .maptools, .scanner.movable") || (e.pointerType === "mouse" && e.button !== 0)) return;
    this.pointers.set(e.pointerId, [e.clientX, e.clientY]);
    this.moved = false;
    this._start();
  }

  _start() {
    const ps = [...this.pointers.values()];
    if (ps.length >= 2) {
      const [a, b] = ps;
      this.gesture = { pinch: true, d: Math.hypot(a[0] - b[0], a[1] - b[1]), m: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] };
    } else if (ps.length === 1) {
      this.gesture = { pinch: false, p: ps[0], pan: false };
    } else this.gesture = null;
  }

  _move(e) {
    if (!this.pointers.has(e.pointerId) || !this.gesture) return;
    this.pointers.set(e.pointerId, [e.clientX, e.clientY]);
    const g = this.gesture;
    const ps = [...this.pointers.values()];
    if (g.pinch && ps.length >= 2) {
      const [a, b] = ps;
      const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      const m = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      if (g.d > 0) this._zoomAt(this._pt(m[0], m[1]), (this.view?.k || 1) * (d / g.d));
      this._panBy(m[0] - g.m[0], m[1] - g.m[1]);
      g.d = d;
      g.m = m;
      this.moved = true;
    } else if (!g.pinch && this.view) {
      const dx = e.clientX - g.p[0];
      const dy = e.clientY - g.p[1];
      if (!g.pan && Math.hypot(dx, dy) < 5) return;
      if (!g.pan) {
        g.pan = true;
        this.map.setPointerCapture?.(e.pointerId);
        this.map.classList.add("panning");
      }
      this._panBy(dx, dy);
      g.p = [e.clientX, e.clientY];
      this.moved = true;
    }
  }

  _up(e) {
    if (!this.pointers.delete(e.pointerId)) return;
    this.map.classList.remove("panning");
    this._start();
  }
}

// Material Design Icons, as Home Assistant draws them
export const MDI = {
  menu: "M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z",
  plus: "M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z",
  minus: "M19,13H5V11H19V13Z",
  fit: "M17,4H20C21.1,4 22,4.9 22,6V8H20V6H17V4M4,8V6H7V4H4C2.9,4 2,4.9 2,6V8H4M20,16V18H17V20H20C21.1,20 22,19.1 22,18V16H20M7,18H4V16H2V18C2,19.1 2.9,20 4,20H7V18M18,8H6V16H18V8M16,14H8V10H16V14Z",
  close: "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
  back: "M20,11V13H8L13.5,18.5L12.08,19.92L4.16,12L12.08,4.08L13.5,5.5L8,11H20Z",
  refresh: "M17.65,6.35C16.2,4.9 14.21,4 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20C15.73,20 18.84,17.45 19.73,14H17.65C16.83,16.33 14.61,18 12,18A6,6 0 0,1 6,12A6,6 0 0,1 12,6C13.66,6 15.14,6.69 16.22,7.78L13,11H20V4L17.65,6.35Z",
  cog: "M12,8A4,4 0 0,1 16,12A4,4 0 0,1 12,16A4,4 0 0,1 8,12A4,4 0 0,1 12,8M12,10A2,2 0 0,0 10,12A2,2 0 0,0 12,14A2,2 0 0,0 14,12A2,2 0 0,0 12,10M10,22C9.75,22 9.54,21.82 9.5,21.58L9.13,18.93C8.5,18.68 7.96,18.34 7.44,17.94L4.95,18.95C4.73,19.03 4.46,18.95 4.34,18.73L2.34,15.27C2.21,15.05 2.27,14.78 2.46,14.63L4.57,12.97L4.5,12L4.57,11L2.46,9.37C2.27,9.22 2.21,8.95 2.34,8.73L4.34,5.27C4.46,5.05 4.73,4.96 4.95,5.05L7.44,6.05C7.96,5.66 8.5,5.32 9.13,5.07L9.5,2.42C9.54,2.18 9.75,2 10,2H14C14.25,2 14.46,2.18 14.5,2.42L14.87,5.07C15.5,5.32 16.04,5.66 16.56,6.05L19.05,5.05C19.27,4.96 19.54,5.05 19.66,5.27L21.66,8.73C21.79,8.95 21.73,9.22 21.54,9.37L19.43,11L19.5,12L19.43,13L21.54,14.63C21.73,14.78 21.79,15.05 21.66,15.27L19.66,18.73C19.54,18.95 19.27,19.04 19.05,18.95L16.56,17.95C16.04,18.34 15.5,18.68 14.87,18.93L14.5,21.58C14.46,21.82 14.25,22 14,22H10M11.25,4L10.88,6.61C9.68,6.86 8.62,7.5 7.85,8.39L5.44,7.35L4.69,8.65L6.8,10.2C6.4,11.37 6.4,12.64 6.8,13.8L4.68,15.36L5.43,16.66L7.86,15.62C8.63,16.5 9.68,17.14 10.87,17.38L11.24,20H12.76L13.13,17.39C14.32,17.14 15.37,16.5 16.14,15.62L18.57,16.66L19.32,15.36L17.2,13.81C17.6,12.64 17.6,11.37 17.2,10.2L19.31,8.65L18.56,7.35L16.15,8.39C15.38,7.5 14.32,6.86 13.12,6.62L12.75,4H11.25Z",
  plus: "M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z",
  delete: "M19,4H15.5L14.5,3H9.5L8.5,4H5V6H19M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19Z",
  play: "M8,5.14V19.14L19,12.14L8,5.14Z",
  pause: "M14,19H18V5H14M6,19H10V5H6V19Z",
  stop: "M18,18H6V6H18V18Z",
  chevron: "M8.59,16.58L13.17,12L8.59,7.41L10,6L16,12L10,18L8.59,16.58Z",
  rotate: "M16.89,15.5L18.31,16.89C19.21,15.73 19.76,14.39 19.93,13H17.91C17.77,13.87 17.43,14.72 16.89,15.5M13,17.9V19.92C14.39,19.75 15.74,19.21 16.9,18.31L15.46,16.87C14.71,17.41 13.87,17.76 13,17.9M19.93,11C19.76,9.61 19.21,8.27 18.31,7.11L16.89,8.53C17.43,9.28 17.77,10.13 17.91,11M15.55,5.55L11,1V4.07C7.06,4.56 4,7.92 4,12C4,16.08 7.05,19.44 11,19.93V17.91C8.16,17.43 6,14.97 6,12C6,9.03 8.16,6.57 11,6.09V10L15.55,5.55Z",
  label: "M16,17H5V7H16L19.55,12M17.63,5.84C17.27,5.33 16.67,5 16,5H5A2,2 0 0,0 3,7V17A2,2 0 0,0 5,19H16C16.67,19 17.27,18.66 17.63,18.15L22,12L17.63,5.84Z",
  move: "M13,6V11H18V7.75L22.25,12L18,16.25V13H13V18H16.25L12,22.25L7.75,18H11V13H6V16.25L1.75,12L6,7.75V11H11V6H7.75L12,1.75L16.25,6H13Z",
  plan: "M2,2H8V4H16V2H22V8H20V16H22V22H16V20H8V22H2V16H4V8H2V2M16,8V6H8V8H6V16H8V18H16V16H18V8H16M4,4V6H6V4H4M18,4V6H20V4H18M4,18V20H6V18H4M18,18V20H20V18H18Z",
  scanner: "M4.93,4.93C3.12,6.74 2,9.24 2,12C2,14.76 3.12,17.26 4.93,19.07L6.34,17.66C4.89,16.22 4,14.22 4,12C4,9.79 4.89,7.78 6.34,6.34L4.93,4.93M19.07,4.93L17.66,6.34C19.11,7.78 20,9.79 20,12C20,14.22 19.11,16.22 17.66,17.66L19.07,19.07C20.88,17.26 22,14.76 22,12C22,9.24 20.88,6.74 19.07,4.93M7.76,7.76C6.67,8.85 6,10.35 6,12C6,13.65 6.67,15.15 7.76,16.24L9.17,14.83C8.45,14.11 8,13.11 8,12C8,10.89 8.45,9.89 9.17,9.17L7.76,7.76M16.24,7.76L14.83,9.17C15.55,9.89 16,10.89 16,12C16,13.11 15.55,14.11 14.83,14.83L16.24,16.24C17.33,15.15 18,13.65 18,12C18,10.35 17.33,8.85 16.24,7.76M12,10A2,2 0 0,0 10,12A2,2 0 0,0 12,14A2,2 0 0,0 14,12A2,2 0 0,0 12,10Z",
  tracker: "M12,11.5A2.5,2.5 0 0,1 9.5,9A2.5,2.5 0 0,1 12,6.5A2.5,2.5 0 0,1 14.5,9A2.5,2.5 0 0,1 12,11.5M12,2A7,7 0 0,0 5,9C5,14.25 12,22 12,22C12,22 19,14.25 19,9A7,7 0 0,0 12,2Z",
  calibration: "M11,2V4.07C7.38,4.53 4.53,7.38 4.07,11H2V13H4.07C4.53,16.62 7.38,19.47 11,19.93V22H13V19.93C16.62,19.47 19.47,16.62 19.93,13H22V11H19.93C19.47,7.38 16.62,4.53 13,4.07V2M11,6.08V8H13V6.09C15.5,6.5 17.5,8.5 17.92,11H16V13H17.91C17.5,15.5 15.5,17.5 13,17.92V16H11V17.91C8.5,17.5 6.5,15.5 6.08,13H8V11H6.09C6.5,8.5 8.5,6.5 11,6.08M12,11A1,1 0 0,0 11,12A1,1 0 0,0 12,13A1,1 0 0,0 13,12A1,1 0 0,0 12,11Z",
  coverage: "M3,21H6V18H3M8,21H11V14H8M13,21H16V9H13M18,21H21V3H18V21Z",
  timeline: "M13.5,8H12V13L16.28,15.54L17,14.33L13.5,12.25V8M13,3A9,9 0 0,0 4,12H1L4.96,16.03L9,12H6A7,7 0 0,1 13,5A7,7 0 0,1 20,12A7,7 0 0,1 13,19C11.07,19 9.32,18.21 8.06,16.94L6.64,18.36C8.27,20 10.5,21 13,21A9,9 0 0,0 22,12A9,9 0 0,0 13,3",
  settings: "M12,15.5A3.5,3.5 0 0,1 8.5,12A3.5,3.5 0 0,1 12,8.5A3.5,3.5 0 0,1 15.5,12A3.5,3.5 0 0,1 12,15.5M19.43,12.97C19.47,12.65 19.5,12.33 19.5,12C19.5,11.67 19.47,11.34 19.43,11L21.54,9.37C21.73,9.22 21.78,8.95 21.66,8.73L19.66,5.27C19.54,5.05 19.27,4.96 19.05,5.05L16.56,6.05C16.04,5.66 15.5,5.32 14.87,5.07L14.5,2.42C14.46,2.18 14.25,2 14,2H10C9.75,2 9.54,2.18 9.5,2.42L9.13,5.07C8.5,5.32 7.96,5.66 7.44,6.05L4.95,5.05C4.73,4.96 4.46,5.05 4.34,5.27L2.34,8.73C2.21,8.95 2.27,9.22 2.46,9.37L4.57,11C4.53,11.34 4.5,11.67 4.5,12C4.5,12.33 4.53,12.65 4.57,12.97L2.46,14.63C2.27,14.78 2.21,15.05 2.34,15.27L4.34,18.73C4.46,18.95 4.73,19.03 4.95,18.95L7.44,17.94C7.96,18.34 8.5,18.68 9.13,18.93L9.5,21.58C9.54,21.82 9.75,22 10,22H14C14.25,22 14.46,21.82 14.5,21.58L14.87,18.93C15.5,18.67 16.04,18.34 16.56,17.94L19.05,18.95C19.27,19.03 19.54,18.95 19.66,18.73L21.66,15.27C21.78,15.05 21.73,14.78 21.54,14.63L19.43,12.97Z",
};

// Home Assistant's own icon and icon button, with the paths above: nothing to load
export const icon = (name) => `<ha-svg-icon path="${MDI[name]}"></ha-svg-icon>`;
export const iconButton = (name, label, attrs = "") =>
  `<ha-icon-button path="${MDI[name]}" label="${esc(label)}"${attrs ? ` ${attrs}` : ""}></ha-icon-button>`;

// How long a failed subscription waits before it tries again (ms)
const RETRY_MS = 30000;

// The live subscription of the card and the page: one at a time, none left
// behind by an element that went away while it was being set up, and after a
// failure (the integration not loaded, say) a new try only every RETRY_MS
export class LiveSubscription {
  constructor(host, onEvent, onError) {
    this._host = host;
    this._onEvent = onEvent;
    this._onError = onError;
    this._unsub = null;
    // Bumped by close(): a subscription that arrives for an older one is dropped
    this._gen = 0;
    this._pending = -1;
    this._retryAt = 0;
    this._timer = null;
  }

  get active() {
    return !!this._unsub;
  }

  // Subscribe unless subscribed, on the way, waiting for a retry or the host is gone
  ensure(hass) {
    this._hass = hass;
    if (!hass || this._unsub || this._pending === this._gen || !this._host.isConnected) return;
    if (Date.now() < this._retryAt) return;
    const gen = (this._pending = this._gen);
    hass.connection
      .subscribeMessage((event) => this._onEvent(event), { type: "ble_floorplan/subscribe" })
      .then(
        (unsub) => {
          if (this._pending === gen) this._pending = -1;
          if (gen !== this._gen || !this._host.isConnected) {
            unsub().catch(() => {});
            if (gen !== this._gen) this.ensure(this._hass);
            return;
          }
          this._unsub = unsub;
          this._retryAt = 0;
          this._onError(null);
        },
        (err) => {
          if (this._pending === gen) this._pending = -1;
          if (gen !== this._gen) return;
          this._retryAt = Date.now() + RETRY_MS;
          clearTimeout(this._timer);
          this._timer = setTimeout(() => this.ensure(this._hass), RETRY_MS);
          this._onError(err);
        }
      );
  }

  close() {
    this._gen += 1;
    this._retryAt = 0;
    clearTimeout(this._timer);
    this._timer = null;
    if (this._unsub) {
      const unsub = this._unsub;
      this._unsub = null;
      unsub().catch(() => {});
    }
  }
}

// The floor plan, its tooltip and the icon buttons on it
export const PLAN_CSS = `
  .map { position: relative; min-width: 0; }
  .map svg:not(.mdi) { width: 100%; height: 100%; display: block; touch-action: pan-x pan-y; overflow: hidden; }
  .map.zoomed svg:not(.mdi), .map.aim svg:not(.mdi) { touch-action: none; }
  .map.zoomed svg:not(.mdi) { cursor: grab; }
  .map.panning svg:not(.mdi) { cursor: grabbing; }
  .zoombtns { position: absolute; right: 8px; bottom: 8px; display: flex; flex-direction: column; gap: 2px; z-index: 1;
    background: var(--card-background-color); border-radius: 20px; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2); }
  .zoombtns ha-icon-button { color: var(--secondary-text-color); }
  .map.aim svg:not(.mdi) { cursor: crosshair; }
  .room { fill: var(--card-background-color); stroke: var(--primary-text-color); stroke-width: 0.08; stroke-linejoin: miter; }
  .room.outdoor { fill: none; stroke-width: 0.04; stroke-dasharray: 0.25 0.15; opacity: 0.6; }
  .zone { fill: none; stroke: var(--secondary-text-color); stroke-width: 0.03; stroke-dasharray: 0.15 0.12; }
  .gap { stroke: var(--card-background-color); stroke-width: 0.12; }
  .opening { stroke: var(--secondary-text-color); stroke-width: 0.025; stroke-dasharray: 0.1 0.08; }
  .rlabel { font-size: 0.38px; fill: var(--secondary-text-color); text-anchor: middle; dominant-baseline: middle; }
  .scanner rect { fill: var(--primary-text-color); }
  .scanner, .tracker { cursor: pointer; }
  .scanner.open rect { fill: var(--primary-color); stroke: var(--primary-color); stroke-width: 0.08; }
  .tracker.open circle { stroke: var(--primary-text-color); stroke-width: 0.06; }
  .scanner.movable { cursor: grab; }
  .scanner.movable rect { fill: var(--primary-color); }
  .scanner.offline rect { fill: var(--card-background-color); stroke: var(--error-color); stroke-width: 0.08; stroke-dasharray: 0.1 0.06; }
  .scanner.offline .slabel, .sub.offline { fill: var(--error-color); color: var(--error-color); }
  .slabel { font-size: 0.3px; fill: var(--primary-text-color); text-anchor: middle; }
  .tlabel { font-size: 0.36px; font-weight: 600; text-anchor: middle; }
  .range { fill: none; stroke-width: 0.04; stroke-dasharray: 0.12 0.1; opacity: 0.8; }
  .truepos circle { fill: none; stroke: var(--primary-color); stroke-width: 0.06; stroke-dasharray: 0.12 0.08; }
  .truepos line { stroke: var(--primary-color); stroke-width: 0.05; }
  .truepos.live circle { stroke-dasharray: none; stroke-width: 0.08; }
  .runmark { stroke: var(--card-background-color); stroke-width: 0.04; opacity: 0.85; }
  .cov { stroke: none; fill-opacity: 0.38; }
  .cov.l0 { fill: var(--error-color, #db4437); }
  .cov.l1 { fill: var(--warning-color, #ffa600); }
  .cov.l2 { fill: var(--success-color, #43a047); }
  .cov.up { stroke: var(--primary-text-color); stroke-width: 0.03; stroke-dasharray: 0.08 0.06; }
  .probe rect { fill: none; stroke: var(--primary-color); stroke-width: 0.06; stroke-dasharray: 0.1 0.07; }
  .probe text { font-size: 0.3px; font-weight: 600; fill: var(--primary-color); text-anchor: middle; dominant-baseline: middle; }
  .trail { fill: none; stroke-width: 0.08; stroke-linecap: round; stroke-linejoin: round; opacity: 0.55; }
  .tip { position: absolute; z-index: 3; pointer-events: none; white-space: nowrap; font-size: 12px; line-height: 1.5; display: none;
    background: var(--card-background-color); color: var(--primary-text-color);
    border: 1px solid var(--divider-color); border-radius: 8px; padding: 8px 12px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2); }
  .tip b, .info b { display: flex; align-items: center; font-weight: 500; font-size: 14px; }
  .tip .sub, .info .sub { color: var(--secondary-text-color); }
  .tip table, .info table { border-collapse: collapse; margin-top: 4px; }
  .tip td, .info td { padding: 1px 12px 1px 0; }
  .tip td.num, .info td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .tip tr.ign, .info tr.ign { color: var(--secondary-text-color); }
  .dot { display: inline-block; flex: none; width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }
  ha-icon-button { color: var(--secondary-text-color); }
  ha-icon-button.on { color: var(--primary-color); }
  .menu { position: absolute; right: 0; top: 44px; z-index: 4; display: flex; flex-direction: column; padding: 4px 0;
    background: var(--card-background-color); border-radius: 8px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25); white-space: nowrap; }
  .menu label { display: flex; align-items: center; gap: 12px; padding: 8px 16px; cursor: pointer; color: var(--primary-text-color); }
  .menu label:hover { background: color-mix(in srgb, var(--primary-text-color) 6%, transparent); }
  .menu input { accent-color: var(--primary-color); width: 18px; height: 18px; margin: 0; }
`;
