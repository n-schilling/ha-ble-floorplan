// BLE Floorplan card: shows the trackers of the BLE Floorplan integration on the
// floor plan. The plan, the scanners, the live positions and the calibration
// runs come from the integration over the WebSocket API; the card only draws.
// Tapping a tracker or a scanner opens its panel with the details and, for
// admins, its actions: edit, move, calibration run. The gear opens the
// settings, the calibration runs and the proposal.
const VERSION = "0.7.0";

if (!customElements.get("ble-floorplan-card")) {
  const esc = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
  const COLORS = ["#e8590c", "#1c7ed6", "#2f9e44", "#ae3ec9", "#f59f00", "#0c8599"];

  const TEXTS = {
    en: {
      title: "BLE Floorplan", rooms: "Rooms", scanners: "Scanners", trackers: "Trackers",
      labels: "Labels", rotate: "Rotate the plan by 90°", settings: "Settings", close: "Close",
      edit: "Edit", move: "Move", save: "Save", cancel: "Cancel", measure: "Calibration run",
      start: "Start run", stop: "Stop run", circles: "Circles", tracker: "Tracker", scanner: "Scanner",
      room: "Room", count: "scanners", notSeen: "not seen", ignored: "ignored", position: "Position",
      height: "Height", refPower: "Reference power", default: "default", offset: "Offset",
      pairs: "Pair corrections", none: "none", hears: "Hears", hintMeasure: "Tap the plan where the tracker lies, then start.",
      hintMove: "Drag the scanner to its place, then save.", runs: "Runs", duration: "Length",
      delete: "Delete", fitExponent: "Fit the exponent too", compute: "Compute", apply: "Apply",
      preview: "Proposal", now: "now", proposed: "proposed", obs: "observations", exponent: "Exponent",
      rms: "RMS error (dB)", applied: "Applied.", saved: "Saved.", display: "Display", engine: "Engine",
      motion: "Motion", roomRules: "Rooms", robust: "Robust weights", attenuation: "Path loss exponent",
      refDefault: "Default reference power (dBm)", maxDistance: "Largest distance (m)",
      smoothing: "Smoothing (s)", minMove: "Dead zone (m)", clamp: "Keep trackers in the rooms",
      clampOutdoor: "Outdoor areas count as rooms", maxSpeed: "Top speed (m/s, 0 = none)",
      jumpDistance: "Jump distance (m, 0 = off)", jumpConfirm: "Jump confirmation (s)",
      walls: "Through walls only at doors", roomHold: "Hold time (s)", roomMargin: "Wall margin (m)", robustResidual: "Residual (m, 0 = off)",
      calibration: "Calibration", noRuns: "No runs yet. Start one from a tracker.", running: "running",
      samples: "samples", rotation: "Rotation", noPlan: "No floor plan yet: an administrator sets it up from the gear of this card.",
      notLoaded: "BLE Floorplan is not set up.", unknown: "–",
      hint: "Hover a scanner or a tracker for details, tap it for its panel.",
      plan: "Floor plan", add: "Add", name: "Name", allOnPlan: "Every one Home Assistant knows is on the plan.",
      layoutHint: "Rooms as rectangles (x, y, w, h) or polygons (points), zones, outdoor areas and openings, in metres; see the README.",
      confirmRemove: "Take {name} off the plan?", startHere: "Open the gear to draw the floor plan and add scanners and trackers.",
      newScannerHint: "New scanners land in the middle; move them to their place from their panel.",
    },
    de: {
      title: "BLE-Grundriss", rooms: "Räume", scanners: "Scanner", trackers: "Tracker",
      labels: "Beschriftung", rotate: "Grundriss um 90° drehen", settings: "Einstellungen", close: "Schließen",
      edit: "Bearbeiten", move: "Verschieben", save: "Speichern", cancel: "Abbrechen", measure: "Messlauf",
      start: "Messlauf starten", stop: "Messlauf beenden", circles: "Kreise", tracker: "Tracker", scanner: "Scanner",
      room: "Raum", count: "Scanner", notSeen: "nicht gesehen", ignored: "ignoriert", position: "Position",
      height: "Höhe", refPower: "Referenzleistung", default: "Standard", offset: "Offset",
      pairs: "Korrektur je Paar", none: "keine", hears: "Hört", hintMeasure: "Auf den Grundriss tippen, wo der Tracker liegt, dann starten.",
      hintMove: "Scanner an seinen Platz ziehen, dann speichern.", runs: "Messläufe", duration: "Dauer",
      delete: "Löschen", fitExponent: "Exponent mitschätzen", compute: "Berechnen", apply: "Übernehmen",
      preview: "Vorschlag", now: "jetzt", proposed: "neu", obs: "Beobachtungen", exponent: "Exponent",
      rms: "RMS-Fehler (dB)", applied: "Übernommen.", saved: "Gespeichert.", display: "Anzeige", engine: "Engine",
      motion: "Bewegung", roomRules: "Räume", robust: "Robuste Gewichte", attenuation: "Pfadverlust-Exponent",
      refDefault: "Referenzleistung Standard (dBm)", maxDistance: "Größter Abstand (m)",
      smoothing: "Glättung (s)", minMove: "Totzone (m)", clamp: "Tracker in den Räumen halten",
      clampOutdoor: "Außenflächen zählen als Räume", maxSpeed: "Höchstgeschwindigkeit (m/s, 0 = keine)",
      jumpDistance: "Sprungweite (m, 0 = aus)", jumpConfirm: "Sprung-Bestätigung (s)",
      walls: "Wände nur an Türen passieren", roomHold: "Haltezeit (s)", roomMargin: "Wandabstand (m)", robustResidual: "Residuum (m, 0 = aus)",
      calibration: "Kalibrierung", noRuns: "Noch keine Messläufe. Start über einen Tracker.", running: "läuft",
      samples: "Samples", rotation: "Drehung", noPlan: "Noch kein Grundriss: Eine Administratorin oder ein Administrator richtet ihn über das Zahnrad dieser Karte ein.",
      notLoaded: "BLE Floorplan ist nicht eingerichtet.", unknown: "–",
      hint: "Maus über Scanner oder Tracker zeigt Details, Antippen öffnet das Panel.",
      plan: "Grundriss", add: "Hinzufügen", name: "Name", allOnPlan: "Alle, die Home Assistant kennt, sind auf dem Plan.",
      layoutHint: "Räume als Rechteck (x, y, w, h) oder Polygon (points), Zonen, Außenflächen und Öffnungen, in Metern; siehe README.",
      confirmRemove: "{name} vom Plan nehmen?", startHere: "Über das Zahnrad den Grundriss eintragen und Scanner und Tracker hinzufügen.",
      newScannerHint: "Neue Scanner landen in der Mitte; über ihr Panel an den Platz schieben.",
    },
  };

  const SETTING_FIELDS = [
    ["engine", "attenuation", "attenuation", 0.1],
    ["engine", "ref_power_default", "refDefault", 1],
    ["engine", "max_distance", "maxDistance", 0.5],
    ["engine", "smoothing_seconds", "smoothing", 1],
    ["engine", "min_move", "minMove", 0.05],
    ["engine", "clamp", "clamp", "bool"],
    ["engine", "clamp_outdoor", "clampOutdoor", "bool"],
    ["motion", "max_speed", "maxSpeed", 0.1],
    ["motion", "jump_distance", "jumpDistance", 0.1],
    ["motion", "jump_confirm_seconds", "jumpConfirm", 0.5],
    ["motion", "walls", "walls", "bool"],
    ["roomRules", "room_hold_seconds", "roomHold", 0.5],
    ["roomRules", "room_margin", "roomMargin", 0.05],
    ["robust", "robust_residual", "robustResidual", 0.1],
  ];

  // Rooms are rectangles (x, y, w, h) or polygons (points), all in metres
  const roomPoints = (r) =>
    r.points || [[r.x, r.y], [r.x + r.w, r.y], [r.x + r.w, r.y + r.h], [r.x, r.y + r.h]];

  const roomLabelPos = (r) => {
    if (r.lx !== undefined) return [r.lx, r.ly];
    const p = roomPoints(r);
    return [p.reduce((a, q) => a + q[0], 0) / p.length, p.reduce((a, q) => a + q[1], 0) / p.length];
  };

  const numOrNull = (v) => {
    const n = parseFloat(String(v).replace(",", "."));
    return Number.isFinite(n) ? n : null;
  };

  class BleFloorplanCard extends HTMLElement {
    setConfig(config) {
      this._config = {
        rotation: 0,
        show_room_labels: true,
        show_scanner_labels: true,
        show_tracker_labels: true,
        ...config,
      };
      this._rot = this._loadRot();
      this._labels = this._loadLabels();
      // The open panel: {kind: "tracker" | "scanner" | "settings", key}
      this._panel = null;
      // What the map does: null, "move" (drag one scanner), "measure" (tap the true position)
      this._mode = null;
      this._dragPos = null;
      this._form = null;
      this._measure = null;
      this._cal = { fitN: false, proposal: null };
      this._busy = false;
      this._note = null;
      this._selected = null;
      this._hover = null;
      this._labelMenu = false;
      this._info = { trackers: {}, scanners: {} };
      this._plan = this._plan || null;
      this._positions = this._positions || {};
      this._calibration = this._calibration || { active: null, runs: [] };
      if (!this.shadowRoot) this.attachShadow({ mode: "open" });
      this._render();
    }

    set hass(hass) {
      const first = !this._hass;
      this._hass = hass;
      if (first || !this._unsub) this._subscribe();
    }

    connectedCallback() {
      if (this._hass && !this._unsub) this._subscribe();
    }

    disconnectedCallback() {
      this._unsubscribe();
    }

    getCardSize() {
      return 12;
    }

    static getConfigElement() {
      return document.createElement("ble-floorplan-card-editor");
    }

    static getStubConfig() {
      return {};
    }

    get _t() {
      const lang = (this._hass?.language || "en").slice(0, 2);
      return TEXTS[lang] || TEXTS.en;
    }

    get _n() {
      const lang = this._hass?.language || "en";
      return (v, d = 1) =>
        Number.isFinite(v) ? v.toLocaleString(lang, { minimumFractionDigits: d, maximumFractionDigits: d }) : this._t.unknown;
    }

    get _admin() {
      return !!this._hass?.user?.is_admin;
    }

    async _subscribe() {
      if (this._subscribing || !this._hass) return;
      this._subscribing = true;
      try {
        this._unsub = await this._hass.connection.subscribeMessage(
          (event) => this._onEvent(event),
          { type: "ble_floorplan/subscribe" }
        );
        this._error = null;
      } catch (err) {
        this._error = err?.code === "not_loaded" ? this._t.notLoaded : String(err?.message || err);
        this._render();
      } finally {
        this._subscribing = false;
      }
    }

    _unsubscribe() {
      if (this._unsub) {
        const unsub = this._unsub;
        this._unsub = null;
        unsub().catch(() => {});
      }
    }

    _onEvent(event) {
      if (event.floorplan) {
        this._plan = event.floorplan;
        this._bounds = this._computeBounds();
      }
      if (event.positions) this._positions = event.positions;
      if (event.calibration) this._calibration = event.calibration;
      if (this._dragging || this._typing()) return;
      this._render();
    }

    // A redraw while a field has the focus would lose the input
    _typing() {
      const el = this.shadowRoot?.activeElement;
      return !!el && (el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA");
    }

    // Rotation: the choice of this browser, else the default of the configuration
    _loadRot() {
      let v = null;
      try {
        v = window.localStorage.getItem("ble-floorplan-card-rot");
      } catch (e) {
        // no storage
      }
      const r = v === null ? this._config.rotation : parseInt(v, 10);
      return [0, 90, 180, 270].includes(r) ? r : 0;
    }

    // Labels (rooms, scanners, trackers): per browser, else the defaults
    _loadLabels() {
      const def = {
        rooms: this._config.show_room_labels,
        scanners: this._config.show_scanner_labels,
        trackers: this._config.show_tracker_labels,
      };
      try {
        const v = JSON.parse(window.localStorage.getItem("ble-floorplan-card-labels") || "null");
        if (v && typeof v === "object") return { ...def, ...v };
      } catch (e) {
        // no storage or bad content
      }
      return def;
    }

    _toggleLabel(kind) {
      this._labels = { ...this._labels, [kind]: !this._labels[kind] };
      try {
        window.localStorage.setItem("ble-floorplan-card-labels", JSON.stringify(this._labels));
      } catch (e) {
        // no storage
      }
    }

    _setRot(r) {
      this._rot = r;
      try {
        window.localStorage.setItem("ble-floorplan-card-rot", String(r));
      } catch (e) {
        // no storage
      }
    }

    _computeBounds() {
      let maxX = 0;
      let maxY = 0;
      for (const r of this._plan?.rooms || []) {
        for (const [x, y] of roomPoints(r)) {
          maxX = Math.max(maxX, x);
          maxY = Math.max(maxY, y);
        }
      }
      return { w: maxX || 1, h: maxY || 1 };
    }

    _scannerPos(s) {
      return (this._dragPos && this._dragPos[s.key]) || [s.x, s.y];
    }

    _trackerColor(key) {
      const i = (this._plan?.trackers || []).findIndex((t) => t.key === key);
      return COLORS[(i < 0 ? 0 : i) % COLORS.length];
    }

    _open(kind, key) {
      if (kind === "settings") {
        const empty = !this._plan?.rooms.length;
        this._secOpen = new Set(empty ? ["plan", "scanners", "trackers"] : []);
        this._layout = null;
        this._candidates = null;
      }
      this._panel = { kind, key };
      this._mode = null;
      this._dragPos = null;
      this._form = null;
      this._measure = null;
      this._note = null;
      this._labelMenu = false;
      this._render();
    }

    _close() {
      this._panel = null;
      this._mode = null;
      this._dragPos = null;
      this._form = null;
      this._measure = null;
      this._note = null;
      this._render();
    }

    // The hover tooltip: the same facts as the panels, next to the pointer
    _tipHtml() {
      const h = this._hover;
      const t = this._t;
      const fmt = this._n;
      if (!h) return "";
      if (h.kind === "tracker") {
        const tr = this._info.trackers[h.key];
        if (!tr) return "";
        const rows = (this._plan.scanners || [])
          .map((s) => {
            const r = tr.readings[s.key] || {};
            const status = r.distance == null ? t.notSeen : r.used ? "" : t.ignored;
            return `<tr class="${r.used ? "" : "ign"}"><td>${esc(s.name)}</td><td class="num">${r.distance == null ? "" : `${fmt(r.distance)} m`}</td>` +
              `<td class="num">${r.rssi == null ? "" : `${fmt(r.rssi, 0)} dBm`}</td><td>${status}</td></tr>`;
          })
          .join("");
        const posText = tr.p
          ? `${esc(tr.room ?? t.unknown)} (${fmt(tr.p.x)} / ${fmt(tr.p.y)} m) · ${tr.p.scanner_count} ${t.count}`
          : t.notSeen;
        return `<b style="color:${tr.color}">${esc(tr.name)}</b><div>${t.position}: ${posText}</div><table>${rows}</table>`;
      }
      const s = this._info.scanners[h.key];
      if (!s) return "";
      const rows = s.trackers
        .map(
          (e) =>
            `<tr class="${e.used ? "" : "ign"}"><td><span class="dot" style="background:${e.color}"></span>${esc(e.name)}</td>` +
            `<td class="num">${e.d == null ? "" : `${fmt(e.d)} m`}</td><td class="num">${e.rssi == null ? "" : `${fmt(e.rssi, 0)} dBm`}</td>` +
            `<td>${e.d == null ? t.notSeen : e.used ? "" : t.ignored}</td></tr>`
        )
        .join("");
      return (
        `<b>${esc(s.name)}</b><div class="sub">${t.position} ${fmt(s.p[0])} / ${fmt(s.p[1])} m · ${t.height} ${fmt(s.z)} m</div>` +
        `<table>${rows}</table>`
      );
    }

    _render() {
      if (!this.shadowRoot || !this._config) return;
      const t = this._t;
      const c = this._config;
      const plan = this._plan;
      const head = `<div class="head"><div class="title">${esc(c.title || t.title)}</div>`;
      if (!plan) {
        this.shadowRoot.innerHTML = `<style>${this._style()}</style><ha-card>${head}</div>` +
          `<div class="hint">${esc(this._error || t.noPlan)}</div></ha-card>`;
        return;
      }
      if (!plan.rooms.length && !this._admin) {
        this.shadowRoot.innerHTML = `<style>${this._style()}</style><ha-card>${head}</div>` +
          `<div class="hint">${esc(t.noPlan)}</div></ha-card>`;
        return;
      }
      const B = this._bounds || this._computeBounds();
      const pad = 0.9;
      const rot = this._rot;
      const landscape = rot % 180 !== 0;
      const vbW = landscape ? B.h : B.w;
      const vbH = landscape ? B.w : B.h;
      // Rotate the plan as a whole, turn every text back at its anchor so it stays readable
      const planTf = {
        0: "",
        90: `rotate(90) translate(0 ${-B.h})`,
        180: `rotate(180) translate(${-B.w} ${-B.h})`,
        270: `rotate(270) translate(${-B.w} 0)`,
      }[rot];
      const upright = (x, y, extra = 0) => (extra - rot ? ` transform="rotate(${extra - rot} ${x} ${y})"` : "");

      const rooms = plan.rooms
        .map((r) => {
          const cls = r.zone ? "zone" : r.outdoor ? "room outdoor" : "room";
          const [lx, ly] = roomLabelPos(r);
          const fs = r.fs ? ` style="font-size:${r.fs}px"` : "";
          // A room's own `rot` is relative to the plan; on screen the label stays
          // horizontal or reads from bottom to top
          const screenRot = r.rot ? ((((r.rot + rot) % 180) + 180) % 180 === 0 ? 0 : -90) : 0;
          const label = r.label === false || !this._labels.rooms || !r.name
            ? ""
            : `<text class="rlabel" x="${lx}" y="${ly}"${fs}${upright(lx, ly, screenRot)}>${esc(r.name)}</text>`;
          const shape = r.points
            ? `<polygon class="${cls}" points="${r.points.map((p) => p.join(",")).join(" ")}"/>`
            : `<rect class="${cls}" x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}"/>`;
          return shape + label;
        })
        .join("");

      // Doors and open passages: break the wall line, mark them thin and dashed
      const openings = (plan.openings || [])
        .map(
          (o) =>
            `<line class="gap" x1="${o[0]}" y1="${o[1]}" x2="${o[2]}" y2="${o[3]}"/>` +
            `<line class="opening" x1="${o[0]}" y1="${o[1]}" x2="${o[2]}" y2="${o[3]}"/>`
        )
        .join("");

      this._info = { trackers: {}, scanners: {} };
      for (const s of plan.scanners) {
        this._info.scanners[s.key] = { name: s.name, p: this._scannerPos(s), z: s.z, trackers: [] };
      }

      let circles = "";
      const dots = [];
      plan.trackers.forEach((tr, i) => {
        const color = COLORS[i % COLORS.length];
        const pos = this._positions[tr.key] || {};
        const readings = pos.readings || {};
        const seen = pos.x != null && pos.y != null;
        this._info.trackers[tr.key] = { name: tr.name, color, readings, p: seen ? pos : null, room: pos.room };
        for (const s of plan.scanners) {
          const r = readings[s.key] || {};
          this._info.scanners[s.key].trackers.push({ key: tr.key, name: tr.name, color, d: r.distance ?? null, rssi: r.rssi, used: !!r.used });
        }
        if (!seen) return;
        const open = this._panel?.kind === "tracker" && this._panel.key === tr.key;
        dots.push(
          `<g class="tracker${open ? " open" : ""}" data-key="${esc(tr.key)}"><circle cx="${pos.x}" cy="${pos.y}" r="0.28" fill="${color}"/>` +
            (this._labels.trackers
              ? `<text class="tlabel" x="${pos.x}" y="${pos.y - 0.42}" fill="${color}"${upright(pos.x, pos.y)}>${esc(tr.name)}</text>`
              : "") +
            `</g>`
        );
        if (this._selected === tr.key) {
          circles += plan.scanners
            .filter((s) => readings[s.key]?.used)
            .map((s) => {
              const [x, y] = this._scannerPos(s);
              return `<circle class="range" cx="${x}" cy="${y}" r="${readings[s.key].distance}" stroke="${color}"/>`;
            })
            .join("");
        }
      });

      // The true position of the run that is going, else the place tapped for the next one
      const active = this._calibration.runs.find((r) => r.id === this._calibration.active);
      const mark = active ? [active.x, active.y] : this._measure?.x != null ? [this._measure.x, this._measure.y] : null;
      const truePos = mark && (active || this._mode === "measure")
        ? `<g class="truepos${active ? " live" : ""}"><circle cx="${mark[0]}" cy="${mark[1]}" r="0.3"/>` +
          `<line x1="${mark[0] - 0.45}" y1="${mark[1]}" x2="${mark[0] + 0.45}" y2="${mark[1]}"/>` +
          `<line x1="${mark[0]}" y1="${mark[1] - 0.45}" x2="${mark[0]}" y2="${mark[1] + 0.45}"/></g>`
        : "";

      const scanners = plan.scanners
        .map((s) => {
          const [x, y] = this._scannerPos(s);
          const movable = this._mode === "move" && this._panel?.key === s.key;
          const open = this._panel?.kind === "scanner" && this._panel.key === s.key;
          return (
            `<g class="scanner${movable ? " movable" : ""}${open ? " open" : ""}" data-key="${esc(s.key)}">` +
            `<rect x="${x - 0.22}" y="${y - 0.22}" width="0.44" height="0.44" rx="0.08"/>` +
            (this._labels.scanners ? `<text class="slabel" x="${x}" y="${y + 0.62}"${upright(x, y)}>${esc(s.name)}</text>` : "") +
            `</g>`
          );
        })
        .join("");

      const tip = this._hover
        ? `<div class="tip" style="left:${this._hover.px}px;top:${this._hover.py}px">${this._tipHtml()}</div>`
        : `<div class="tip" style="display:none"></div>`;
      const labelMenu = this._labelMenu
        ? `<div class="menu">${[["rooms", t.rooms], ["scanners", t.scanners], ["trackers", t.trackers]]
            .map(([k, l]) => `<label><input type="checkbox" data-toggle="${k}"${this._labels[k] ? " checked" : ""}> ${esc(l)}</label>`)
            .join("")}</div>`
        : "";
      // Number fields format their values in the language of Home Assistant, not of the device
      const lang = esc(this._hass?.language || "en");
      const panel = this._panel ? `<div class="panel" lang="${lang}">${this._panelHtml(active)}</div>` : "";

      this.shadowRoot.innerHTML = `
        <style>${this._style()}</style>
        <ha-card>
          ${head}
            <div class="btns">
              <button id="rotate" class="icon" title="${esc(t.rotate)}">⟳</button>
              <span class="menuwrap"><button id="labels" class="icon${this._labelMenu ? " on" : ""}" title="${esc(t.labels)}">Aa</button>${labelMenu}</span>
              ${this._admin ? `<button id="settings" class="icon${this._panel?.kind === "settings" ? " on" : ""}" title="${esc(t.settings)}">⚙</button>` : ""}
            </div>
          </div>
          <div class="body${landscape ? " landscape" : ""}${this._panel ? " withpanel" : ""}"><div class="map${this._mode === "measure" && !active ? " aim" : ""}">
          ${plan.rooms.length
            ? `<svg viewBox="${-pad} ${-pad} ${vbW + 2 * pad} ${vbH + 2 * pad}" preserveAspectRatio="xMidYMin meet">
            <g id="plan" transform="${planTf}">${rooms}${openings}${circles}${truePos}${scanners}${dots.join("")}</g>
          </svg>`
            : `<div class="empty">${esc(t.startHere)}</div>`}${tip}</div>${panel}</div>
        </ha-card>`;

      this._bind();
    }

    _panelHtml(active) {
      const t = this._t;
      const p = this._panel;
      const note = this._note ? `<div class="${this._note.kind}">${esc(this._note.text)}</div>` : "";
      if (p.kind === "settings") return this._settingsHtml(active, note);
      if (p.kind === "tracker") {
        const tr = this._plan.trackers.find((x) => x.key === p.key);
        return tr ? this._trackerHtml(tr, active) + note : `<div class="hint">${t.unknown}</div>`;
      }
      const s = this._plan.scanners.find((x) => x.key === p.key);
      return s ? this._scannerHtml(s) + note : `<div class="hint">${t.unknown}</div>`;
    }

    _head(title, color) {
      const dot = color ? `<span class="dot" style="background:${color}"></span>` : "";
      return `<div class="phead"><b>${dot}${esc(title)}</b><button id="close" class="icon" title="${esc(this._t.close)}">✕</button></div>`;
    }

    // Numbers in the language of Home Assistant; typing takes a point or a comma
    _num(value) {
      return Number.isFinite(value)
        ? value.toLocaleString(this._hass?.language || "en", { useGrouping: false, maximumFractionDigits: 3 })
        : "";
    }

    _field(id, label, value) {
      return `<label class="f">${esc(label)}<input type="text" inputmode="decimal" data-field="${esc(id)}" value="${esc(this._num(value))}"></label>`;
    }

    _trackerHtml(tr, active) {
      const t = this._t;
      const fmt = this._n;
      const info = this._info.trackers[tr.key];
      const pos = info.p;
      const status = pos
        ? `${esc(pos.room || t.unknown)} · ${fmt(pos.x)} / ${fmt(pos.y)} m · ${pos.scanner_count} ${t.count}`
        : t.notSeen;
      const rows = this._plan.scanners
        .map((s) => {
          const r = info.readings[s.key] || {};
          const cls = r.distance == null ? "ign" : r.used ? "" : "ign";
          return `<tr class="${cls}"><td>${esc(s.name)}</td><td class="num">${r.distance == null ? t.notSeen : `${fmt(r.distance)} m`}</td>` +
            `<td class="num">${r.rssi == null ? "" : `${fmt(r.rssi, 0)} dBm`}</td></tr>`;
        })
        .join("");
      const pairs = this._plan.scanners
        .filter((s) => this._plan.pair_offsets?.[s.key]?.[tr.key] != null)
        .map((s) => `${esc(s.name)} ${this._plan.pair_offsets[s.key][tr.key] > 0 ? "+" : ""}${fmt(this._plan.pair_offsets[s.key][tr.key])}`)
        .join(" · ");
      let body;
      if (this._form) {
        const f = this._form;
        body = `<div class="form">
          ${this._field("height", `${t.height} (m)`, f.height, 0.05)}
          ${this._field("ref_power", `${t.refPower} (dBm, ${t.default} ${fmt(this._plan.settings.ref_power_default, 0)})`, f.ref_power, 1)}
          <div class="sec">${t.pairs} (dB)</div>
          ${this._plan.scanners.map((s) => this._field(`pair:${s.key}`, s.name, f.pairs[s.key], 0.1)).join("")}
          <div class="row"><button id="cancel">${t.cancel}</button><button id="save" class="primary">${t.save}</button></div></div>`;
      } else {
        const ref = tr.ref_power == null ? `${t.default} (${fmt(this._plan.settings.ref_power_default, 0)} dBm)` : `${fmt(tr.ref_power)} dBm`;
        body = `<div class="kv"><span>${t.height}</span><span>${fmt(tr.height, 2)} m</span>
          <span>${t.refPower}</span><span>${ref}</span>
          <span>${t.pairs}</span><span>${pairs || t.none}</span></div>`;
      }
      let measure = "";
      const mine = active && active.tracker === tr.key;
      if (mine) {
        const counts = Object.entries(active.counts || {})
          .map(([k, n]) => `${esc(this._plan.scanners.find((s) => s.key === k)?.name || k)} ${n}`)
          .join(" · ");
        measure = `<div class="measure"><div class="sec">${t.measure} · ${t.running}</div>
          <div>${fmt(active.x)} / ${fmt(active.y)} m · ${t.height} ${fmt(active.height)} m</div>
          <div class="hint">${counts || "…"}</div>
          <div class="row"><button id="calStop" class="primary"${this._busy ? " disabled" : ""}>${t.stop}</button></div></div>`;
      } else if (this._mode === "measure") {
        const m = this._measure;
        const ready = m.x != null && !this._busy && !active;
        measure = `<div class="measure"><div class="sec">${t.measure}</div>
          ${this._field("mheight", `${t.height} (m)`, m.height, 0.05)}
          <div class="kv"><span>${t.position}</span><span>${m.x == null ? t.hintMeasure : `${fmt(m.x, 2)} / ${fmt(m.y, 2)} m`}</span></div>
          <div class="row"><button id="cancel">${t.cancel}</button><button id="calStart" class="primary"${ready ? "" : " disabled"}>${t.start}</button></div></div>`;
      }
      const actions = this._form || this._mode === "measure" || mine
        ? ""
        : `<div class="row">
            <button id="circles" class="${this._selected === tr.key ? "on" : ""}">${t.circles}</button>
            ${this._admin ? `<button id="edit">${t.edit}</button><button id="measure"${active ? " disabled" : ""}>${t.measure}</button>` : ""}
          </div>`;
      return `${this._head(tr.name, info.color)}<div class="status">${status}</div><table class="small">${rows}</table>${body}${measure}${actions}`;
    }

    _scannerHtml(s) {
      const t = this._t;
      const fmt = this._n;
      const info = this._info.scanners[s.key];
      const rows = info.trackers
        .map(
          (e) =>
            `<tr class="${e.d == null || !e.used ? "ign" : ""}"><td><span class="dot" style="background:${e.color}"></span>${esc(e.name)}</td>` +
            `<td class="num">${e.d == null ? t.notSeen : `${fmt(e.d)} m`}</td><td class="num">${e.rssi == null ? "" : `${fmt(e.rssi, 0)} dBm`}</td></tr>`
        )
        .join("");
      const pairs = this._plan.trackers
        .filter((tr) => this._plan.pair_offsets?.[s.key]?.[tr.key] != null)
        .map((tr) => `${esc(tr.name)} ${this._plan.pair_offsets[s.key][tr.key] > 0 ? "+" : ""}${fmt(this._plan.pair_offsets[s.key][tr.key])}`)
        .join(" · ");
      let body;
      if (this._form) {
        const f = this._form;
        body = `<div class="form"><div class="grid3">
          ${this._field("x", "x (m)", f.x, 0.05)}${this._field("y", "y (m)", f.y, 0.05)}${this._field("z", `${t.height} (m)`, f.z, 0.05)}</div>
          ${this._field("rssi_offset", `${t.offset} (dB)`, f.rssi_offset, 0.1)}
          <div class="sec">${t.pairs} (dB)</div>
          ${this._plan.trackers.map((tr) => this._field(`pair:${tr.key}`, tr.name, f.pairs[tr.key], 0.1)).join("")}
          <div class="row"><button id="cancel">${t.cancel}</button><button id="save" class="primary">${t.save}</button></div></div>`;
      } else if (this._mode === "move") {
        const [x, y] = this._scannerPos(s);
        body = `<div class="measure"><div class="hint">${t.hintMove}</div><div class="kv"><span>${t.position}</span><span>${fmt(x)} / ${fmt(y)} m</span></div>
          <div class="row"><button id="cancel">${t.cancel}</button><button id="saveMove" class="primary">${t.save}</button></div></div>`;
      } else {
        body = `<div class="kv"><span>${t.position}</span><span>${fmt(s.x)} / ${fmt(s.y)} m · ${t.height} ${fmt(s.z)} m</span>
          <span>${t.offset}</span><span>${s.rssi_offset > 0 ? "+" : ""}${fmt(s.rssi_offset)} dB</span>
          <span>${t.pairs}</span><span>${pairs || t.none}</span></div>`;
      }
      const actions = this._form || this._mode === "move" || !this._admin
        ? ""
        : `<div class="row"><button id="move">${t.move}</button><button id="edit">${t.edit}</button></div>`;
      return `${this._head(s.name)}<div class="status">${t.hears}</div><table class="small">${rows}</table>${body}${actions}`;
    }

    _settingsHtml(active, note = "") {
      const t = this._t;
      const fmt = this._n;
      const plan = this._plan;
      const f = this._form || { settings: { ...plan.settings } };
      const sections = {};
      for (const [sec, key, label, step] of SETTING_FIELDS) {
        const v = f.settings[key];
        sections[sec] = (sections[sec] || "") + (step === "bool"
          ? `<label class="check"><input type="checkbox" data-setting="${key}"${v ? " checked" : ""}> ${esc(t[label])}</label>`
          : `<label class="f">${esc(t[label])}<input type="text" inputmode="decimal" data-setting="${key}" value="${esc(this._num(v))}"></label>`);
      }
      const rotation = [0, 90, 180, 270]
        .map((v) => `<option value="${v}"${this._rot === v ? " selected" : ""}>${v}°</option>`)
        .join("");
      const sec = (id, title, body) =>
        `<details data-sec="${id}"${this._secOpen?.has(id) ? " open" : ""}><summary>${esc(title)}</summary><div class="secbody">${body}</div></details>`;
      const saveSettings = `<div class="row"><button class="primary" data-save-settings${this._busy ? " disabled" : ""}>${t.save}</button></div>`;
      const layout = `<textarea id="layoutText" rows="14" spellcheck="false" wrap="off">${esc(this._layout ?? "…")}</textarea>
        <div class="row"><button id="saveLayout" class="primary"${this._busy || this._layout == null ? " disabled" : ""}>${t.save}</button></div>
        <div class="hint">${esc(t.layoutHint)}</div>`;
      const cand = this._candidates;
      const listRows = (items, attr) => items.length
        ? `<table class="small">${items.map((x) => `<tr><td>${esc(x.name)}</td><td class="num"><button class="small" ${attr}="${esc(x.key)}" title="${esc(t.delete)}"${this._busy ? " disabled" : ""}>✕</button></td></tr>`).join("")}</table>`
        : "";
      const addForm = (kind, options, extra) => {
        if (cand == null) return `<div class="hint">…</div>`;
        if (!options.length) return `<div class="hint">${esc(t.allOnPlan)}</div>`;
        return `<div class="form"><label class="f">${esc(t.add)}<select id="add-${kind}">${options.join("")}</select></label>${extra}
          <div class="row"><button id="add-${kind}-btn" class="primary"${this._busy ? " disabled" : ""}>${t.add}</button></div></div>`;
      };
      const scannerOptions = (cand?.scanners || []).map((c) => `<option value="${esc(c.source)}">${esc(c.name)} (${esc(c.source)})</option>`);
      const trackerOptions = (cand?.trackers || []).map((c) =>
        `<option value="${esc(c.device_id ? `device:${c.device_id}` : `address:${c.address}`)}">${esc(c.name)}${c.address ? ` (${esc(c.address)})` : ""}</option>`);
      const add = this._add || {};
      const scannersBody = listRows(plan.scanners, "data-remove-scanner") +
        addForm("scanner", scannerOptions, this._field("addz", `${t.height} (m)`, add.z ?? 1)) +
        `<div class="hint">${esc(t.newScannerHint)}</div>`;
      const trackersBody = listRows(plan.trackers, "data-remove-tracker") +
        addForm("tracker", trackerOptions,
          `<label class="f">${esc(t.name)}<input type="text" id="addname" value="${esc(add.name ?? cand?.trackers?.[0]?.name ?? "")}"></label>` +
          this._field("addh", `${t.height} (m)`, add.height ?? 1));
      const display = `
        <label class="f">${t.rotation}<select id="rotSelect">${rotation}</select></label>
        <div class="checks">${[["rooms", t.rooms], ["scanners", t.scanners], ["trackers", t.trackers]]
          .map(([k, l]) => `<label class="check"><input type="checkbox" data-toggle="${k}"${this._labels[k] ? " checked" : ""}> ${esc(l)}</label>`)
          .join("")}</div>`;
      const settings = ["engine", "motion", "roomRules", "robust"]
        .map((id) => sec(id, t[id], `<div class="grid2">${sections[id]}</div>${saveSettings}`))
        .join("");

      const name = (key) => plan.trackers.find((x) => x.key === key)?.name || key;
      const sname = (key) => plan.scanners.find((x) => x.key === key)?.name || key;
      const runRows = this._calibration.runs
        .map((r) => {
          const counts = plan.scanners.map((s) => `<td class="num">${r.counts[s.key] || 0}</td>`).join("");
          const length = r.running ? t.running : `${Math.round(r.duration)} s`;
          return `<tr class="${r.running ? "live" : ""}"><td>${esc(name(r.tracker))}</td>` +
            `<td class="num">${fmt(r.x)} / ${fmt(r.y)}</td><td class="num">${length}</td>${counts}` +
            `<td><button class="small" data-delete="${esc(r.id)}" title="${esc(t.delete)}"${this._busy ? " disabled" : ""}>✕</button></td></tr>`;
        })
        .join("");
      const scannerCols = plan.scanners.map((s) => `<th class="num" title="${esc(s.name)}">${esc(s.name)}</th>`).join("");
      const runs = this._calibration.runs.length
        ? `<div class="scrollx"><table class="runs"><tr><th>${t.tracker}</th><th class="num">x / y</th><th class="num">${t.duration}</th>${scannerCols}<th></th></tr>${runRows}</table></div>`
        : `<div class="hint">${t.noRuns}</div>`;
      const finished = this._calibration.runs.some((r) => !r.running);
      const solve = `<div class="row">
          <label class="check"><input id="calFitN" type="checkbox"${this._cal.fitN ? " checked" : ""}> ${t.fitExponent}</label>
          <button id="calSolve"${finished && !this._busy ? "" : " disabled"}>${t.compute}</button></div>`;
      let preview = "";
      const pr = this._cal.proposal;
      if (pr) {
        const row = (label, v, extra = "") =>
          `<tr class="${v.old !== v.new ? "changed" : ""}"><td>${label}</td><td class="num">${fmt(v.old, 1)}</td>` +
          `<td class="num">${fmt(v.new, 1)}</td><td class="num">${extra}</td></tr>`;
        const section = (label) => `<tr class="sec"><td colspan="4">${label}</td></tr>`;
        const rows = [];
        if (pr.attenuation) rows.push(section(t.exponent), row("n", pr.attenuation));
        rows.push(section(`${t.refPower} (dBm)`));
        for (const [k, v] of Object.entries(pr.trackers)) rows.push(row(esc(name(k)), v, `${v.runs} / ${v.samples}`));
        rows.push(section(`${t.offset} (dB)`));
        for (const [k, v] of Object.entries(pr.scanners)) rows.push(row(esc(sname(k)), v, `${v.runs} / ${v.samples}`));
        rows.push(section(`${t.pairs} (dB)`));
        for (const [sk, trs] of Object.entries(pr.pairs)) {
          for (const [tk, v] of Object.entries(trs)) rows.push(row(`${esc(sname(sk))} · ${esc(name(tk))}`, v, `${v.runs} / ${v.samples}`));
        }
        rows.push(section(t.rms), row("RMS", pr.rms, `${pr.observations} ${t.obs}`));
        preview = `<div class="sec">${t.preview}</div>
          <div class="scrollx"><table class="diff"><tr><th></th><th class="num">${t.now}</th><th class="num">${t.proposed}</th><th class="num">${t.runs} / ${t.samples}</th></tr>${rows.join("")}</table></div>
          <div class="row"><button id="calApply" class="primary"${this._busy || active ? " disabled" : ""}>${t.apply}</button></div>`;
      }
      return this._head(t.settings) + note +
        sec("plan", t.plan, layout) +
        sec("scanners", t.scanners, scannersBody) +
        sec("trackers", t.trackers, trackersBody) +
        sec("display", t.display, display) +
        settings +
        sec("calibration", t.calibration, runs + solve + preview);
    }

    _style() {
      return `
        ha-card { padding: 12px 16px 16px; }
        .head { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
        .title { font-size: 1.2em; font-weight: 500; }
        .btns { display: flex; gap: 6px; align-items: center; }
        .menuwrap { position: relative; }
        .menu { position: absolute; right: 0; top: 36px; z-index: 4; background: var(--card-background-color);
          border: 1px solid var(--divider-color); border-radius: 8px; padding: 6px 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.3);
          display: flex; flex-direction: column; gap: 4px; white-space: nowrap; }
        button { font: inherit; border: 1px solid var(--divider-color); background: var(--secondary-background-color);
          color: var(--primary-text-color); border-radius: 8px; padding: 4px 10px; cursor: pointer; }
        button.icon { width: 34px; padding: 4px 0; font-size: 1.05em; line-height: 1.3; }
        button.on { border-color: var(--primary-color); color: var(--primary-color); }
        button.primary { background: var(--primary-color); color: var(--text-primary-color); border-color: transparent; }
        button:disabled { opacity: 0.5; cursor: default; }
        button.small { padding: 0 6px; line-height: 1.6; }
        .body { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; margin-top: 8px; }
        .map { flex: 1 1 360px; min-width: 0; position: relative; }
        .body.landscape .map { flex-basis: 100%; }
        .panel { flex: 1 1 280px; min-width: 0; max-width: 100%; font-size: 0.95em; }
        .body.withpanel:not(.landscape) .panel { flex: 0 1 300px; }
        svg { width: 100%; max-height: 85vh; display: block; touch-action: none; overflow: hidden; }
        .map.aim svg { cursor: crosshair; }
        .room { fill: var(--card-background-color); stroke: var(--primary-text-color); stroke-width: 0.08; stroke-linejoin: miter; }
        .room.outdoor { fill: none; stroke-width: 0.04; stroke-dasharray: 0.25 0.15; opacity: 0.6; }
        .zone { fill: none; stroke: var(--secondary-text-color); stroke-width: 0.03; stroke-dasharray: 0.15 0.12; }
        .gap { stroke: var(--card-background-color); stroke-width: 0.12; }
        .opening { stroke: var(--secondary-text-color); stroke-width: 0.025; stroke-dasharray: 0.1 0.08; }
        .rlabel { font-size: 0.38px; fill: var(--secondary-text-color); text-anchor: middle; dominant-baseline: middle; }
        .scanner rect { fill: var(--primary-text-color); }
        .scanner, .tracker { cursor: pointer; }
        .scanner.open rect { stroke: var(--primary-color); stroke-width: 0.08; }
        .tracker.open circle { stroke: var(--primary-text-color); stroke-width: 0.06; }
        .scanner.movable { cursor: grab; }
        .scanner.movable rect { fill: var(--primary-color); }
        .slabel { font-size: 0.3px; fill: var(--primary-text-color); text-anchor: middle; }
        .tlabel { font-size: 0.36px; font-weight: 600; text-anchor: middle; }
        .range { fill: none; stroke-width: 0.04; stroke-dasharray: 0.12 0.1; opacity: 0.8; }
        .truepos circle { fill: none; stroke: var(--primary-color); stroke-width: 0.06; stroke-dasharray: 0.12 0.08; }
        .truepos line { stroke: var(--primary-color); stroke-width: 0.05; }
        .truepos.live circle { stroke-dasharray: none; stroke-width: 0.08; }
        .tip { position: absolute; z-index: 3; pointer-events: none; white-space: nowrap; font-size: 0.85em;
          background: var(--card-background-color); color: var(--primary-text-color);
          border: 1px solid var(--divider-color); border-radius: 8px; padding: 6px 10px;
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3); }
        .tip b { display: block; margin-bottom: 2px; }
        .tip .sub { color: var(--secondary-text-color); }
        .tip table { width: auto; margin-top: 4px; }
        .tip td { padding: 1px 8px 1px 0; border: 0; }
        table { width: 100%; border-collapse: collapse; }
        th, td { text-align: left; padding: 3px 6px; border-bottom: 1px solid var(--divider-color); }
        th { color: var(--secondary-text-color); font-weight: 500; font-size: 0.85em; }
        td.num, th.num { text-align: right; white-space: nowrap; }
        tr.ign { color: var(--secondary-text-color); }
        tr.live td { color: var(--primary-color); }
        table.small td { padding: 2px 6px; }
        .phead { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 4px; }
        .phead b { font-size: 1.1em; font-weight: 500; }
        .status { color: var(--secondary-text-color); margin-bottom: 6px; }
        .kv { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; margin-top: 8px; }
        .kv span:nth-child(odd) { color: var(--secondary-text-color); }
        .row { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-top: 10px; }
        .sec { color: var(--secondary-text-color); font-size: 0.85em; margin: 12px 0 4px; }
        .sec.big { font-size: 1em; color: var(--primary-text-color); font-weight: 500; margin-top: 16px; }
        .form, .measure { margin-top: 8px; }
        .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; }
        .grid3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px 8px; }
        label.f { display: flex; flex-direction: column; gap: 2px; font-size: 0.8em; color: var(--secondary-text-color); margin-top: 6px; }
        label.f input, label.f select { font: inherit; font-size: 1.15em; padding: 5px 8px; border-radius: 6px; width: 100%; box-sizing: border-box;
          border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
        label.check { display: flex; align-items: center; gap: 6px; margin-top: 6px; }
        .grid2 label.check { grid-column: 1 / -1; }
        .scrollx { overflow-x: auto; }
        .checks { display: flex; gap: 12px; flex-wrap: wrap; }
        .runs th { max-width: 5em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .diff tr.sec td { color: var(--secondary-text-color); font-size: 0.85em; padding-top: 8px; border: 0; }
        .diff tr.changed td:nth-child(3) { font-weight: 600; color: var(--primary-color); }
        .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }
        .hint { color: var(--secondary-text-color); font-size: 0.85em; margin-top: 6px; }
        .empty { color: var(--secondary-text-color); padding: 48px 16px; text-align: center; border: 1px dashed var(--divider-color); border-radius: 8px; }
        details { border-top: 1px solid var(--divider-color); padding: 8px 0; }
        details > summary { cursor: pointer; font-weight: 500; list-style-position: inside; }
        .secbody { padding-top: 4px; }
        textarea { width: 100%; box-sizing: border-box; font-family: var(--code-font-family, monospace); font-size: 0.85em;
          border: 1px solid var(--divider-color); border-radius: 6px; padding: 6px 8px; resize: vertical; white-space: pre; overflow-x: auto;
          background: var(--card-background-color); color: var(--primary-text-color); }
        .err { color: var(--error-color, #c62828); margin-top: 8px; }
        .ok { color: var(--success-color, #2e7d32); margin-top: 8px; }`;
    }

    _bind() {
      const root = this.shadowRoot;
      const t = this._t;
      root.getElementById("rotate")?.addEventListener("click", () => {
        this._setRot((this._rot + 90) % 360);
        this._hover = null;
        this._render();
      });
      root.getElementById("labels")?.addEventListener("click", () => {
        this._labelMenu = !this._labelMenu;
        this._render();
      });
      root.getElementById("settings")?.addEventListener("click", () => {
        if (this._panel?.kind === "settings") this._close();
        else this._open("settings");
      });
      root.getElementById("close")?.addEventListener("click", () => this._close());
      root.querySelectorAll("input[data-toggle]").forEach((cb) =>
        cb.addEventListener("change", () => {
          this._toggleLabel(cb.dataset.toggle);
          this._render();
        })
      );
      root.getElementById("rotSelect")?.addEventListener("change", (e) => {
        this._setRot(parseInt(e.target.value, 10));
        this._render();
      });
      const plan = root.getElementById("plan");
      const svg = root.querySelector("svg");
      const toPlan = (e) => {
        const pt = plan.ownerSVGElement.createSVGPoint();
        pt.x = e.clientX;
        pt.y = e.clientY;
        const p = pt.matrixTransform(plan.getScreenCTM().inverse());
        const B = this._bounds;
        return [Math.min(Math.max(p.x, 0), B.w), Math.min(Math.max(p.y, 0), B.h)];
      };
      if (this._mode === "measure") {
        svg?.addEventListener("click", (e) => {
          if (this._calibration.active) return;
          const [x, y] = toPlan(e);
          this._measure.x = Math.round(x * 20) / 20;
          this._measure.y = Math.round(y * 20) / 20;
          this._render();
        });
      } else if (this._mode === "move") {
        const g = root.querySelector(".scanner.movable");
        g?.addEventListener("pointerdown", (ev) => {
          ev.preventDefault();
          this._dragging = true;
          const key = g.dataset.key;
          const move = (e) => {
            const [px, py] = toPlan(e);
            const x = Math.round(px * 20) / 20;
            const y = Math.round(py * 20) / 20;
            this._dragPos[key] = [x, y];
            const rect = g.querySelector("rect");
            const text = g.querySelector("text");
            rect.setAttribute("x", x - 0.22);
            rect.setAttribute("y", y - 0.22);
            if (text) {
              text.setAttribute("x", x);
              text.setAttribute("y", y + 0.62);
              if (this._rot) text.setAttribute("transform", `rotate(${-this._rot} ${x} ${y})`);
            }
          };
          const up = () => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", up);
            this._dragging = false;
            this._render();
          };
          window.addEventListener("pointermove", move);
          window.addEventListener("pointerup", up);
        });
      } else {
        root.querySelectorAll(".tracker").forEach((g) => g.addEventListener("click", () => this._open("tracker", g.dataset.key)));
        root.querySelectorAll(".scanner").forEach((g) => g.addEventListener("click", () => this._open("scanner", g.dataset.key)));
      }
      this._bindHover(root.querySelector(".map"), root.querySelector(".tip"));
      if (this._panel) this._bindPanel(root);
    }

    _bindPanel(root) {
      const t = this._t;
      const p = this._panel;
      const plan = this._plan;
      // Form fields keep what is typed; the next redraw shows it again
      root.querySelectorAll("input[data-field]").forEach((input) =>
        input.addEventListener("input", () => {
          const id = input.dataset.field;
          const v = numOrNull(input.value);
          if (id === "mheight") this._measure.height = v ?? this._measure.height;
          else if (id === "addz") this._add = { ...(this._add || {}), z: v ?? 1 };
          else if (id === "addh") this._add = { ...(this._add || {}), height: v ?? 1 };
          else if (id.startsWith("pair:")) this._form.pairs[id.slice(5)] = v;
          else this._form[id] = v;
        })
      );
      root.querySelectorAll("input[data-setting]").forEach((input) =>
        input.addEventListener("input", () => {
          if (!this._form) this._form = { settings: { ...plan.settings } };
          this._form.settings[input.dataset.setting] = input.type === "checkbox" ? input.checked : numOrNull(input.value);
        })
      );
      root.getElementById("cancel")?.addEventListener("click", () => {
        this._form = null;
        this._mode = null;
        this._dragPos = null;
        this._measure = null;
        this._render();
      });
      if (p.kind === "tracker") {
        const tr = plan.trackers.find((x) => x.key === p.key);
        root.getElementById("circles")?.addEventListener("click", () => {
          this._selected = this._selected === tr.key ? null : tr.key;
          this._render();
        });
        root.getElementById("edit")?.addEventListener("click", () => {
          const pairs = {};
          for (const s of plan.scanners) pairs[s.key] = plan.pair_offsets?.[s.key]?.[tr.key] ?? null;
          this._form = { height: tr.height, ref_power: tr.ref_power ?? null, pairs };
          this._note = null;
          this._render();
        });
        root.getElementById("save")?.addEventListener("click", () => {
          const f = this._form;
          const msg = { type: "ble_floorplan/set_tracker", key: tr.key, height: f.height ?? tr.height, ref_power: f.ref_power, pair_offsets: f.pairs };
          this._call(msg, () => {
            this._form = null;
            this._note = { kind: "ok", text: t.saved };
          });
        });
        root.getElementById("measure")?.addEventListener("click", () => {
          this._mode = "measure";
          this._measure = { x: null, y: null, height: tr.height };
          this._note = null;
          this._render();
        });
        root.getElementById("calStart")?.addEventListener("click", () => {
          const m = this._measure;
          this._call({ type: "ble_floorplan/calibration/start", tracker: tr.key, x: m.x, y: m.y, height: m.height }, () => {
            this._mode = null;
            this._measure = null;
          });
        });
        root.getElementById("calStop")?.addEventListener("click", () => this._call({ type: "ble_floorplan/calibration/stop" }));
      } else if (p.kind === "scanner") {
        const s = plan.scanners.find((x) => x.key === p.key);
        root.getElementById("move")?.addEventListener("click", () => {
          this._mode = "move";
          this._dragPos = {};
          this._note = null;
          this._render();
        });
        root.getElementById("saveMove")?.addEventListener("click", () => {
          const [x, y] = this._scannerPos(s);
          this._call({ type: "ble_floorplan/set_scanner", key: s.key, x, y }, () => {
            this._mode = null;
            this._dragPos = null;
            this._note = { kind: "ok", text: t.saved };
          });
        });
        root.getElementById("edit")?.addEventListener("click", () => {
          const pairs = {};
          for (const tr of plan.trackers) pairs[tr.key] = plan.pair_offsets?.[s.key]?.[tr.key] ?? null;
          this._form = { x: s.x, y: s.y, z: s.z, rssi_offset: s.rssi_offset, pairs };
          this._note = null;
          this._render();
        });
        root.getElementById("save")?.addEventListener("click", () => {
          const f = this._form;
          const msg = { type: "ble_floorplan/set_scanner", key: s.key, x: f.x ?? s.x, y: f.y ?? s.y, z: f.z ?? s.z, rssi_offset: f.rssi_offset ?? s.rssi_offset, pair_offsets: f.pairs };
          this._call(msg, () => {
            this._form = null;
            this._note = { kind: "ok", text: t.saved };
          });
        });
      } else {
        root.querySelectorAll("button[data-save-settings]").forEach((b) => b.addEventListener("click", () => {
          const settings = { ...(this._form?.settings || plan.settings) };
          for (const [, key, , step] of SETTING_FIELDS) if (step !== "bool" && settings[key] == null) settings[key] = plan.settings[key];
          this._call({ type: "ble_floorplan/set_settings", settings }, () => {
            this._form = null;
            this._note = { kind: "ok", text: t.saved };
          });
        }));
        root.querySelectorAll("details[data-sec]").forEach((d) => d.addEventListener("toggle", () => {
          if (d.open) this._secOpen.add(d.dataset.sec);
          else this._secOpen.delete(d.dataset.sec);
          this._loadSection(d.dataset.sec);
        }));
        for (const id of this._secOpen) this._loadSection(id);
        root.getElementById("layoutText")?.addEventListener("input", (e) => {
          this._layout = e.target.value;
        });
        root.getElementById("saveLayout")?.addEventListener("click", () =>
          this._call({ type: "ble_floorplan/set_layout", yaml: this._layout }, (result) => {
            this._layout = result.yaml;
            this._note = { kind: "ok", text: t.saved };
          })
        );
        root.querySelectorAll("button[data-remove-scanner], button[data-remove-tracker]").forEach((b) =>
          b.addEventListener("click", () => {
            const isScanner = b.hasAttribute("data-remove-scanner");
            const key = isScanner ? b.dataset.removeScanner : b.dataset.removeTracker;
            const item = (isScanner ? plan.scanners : plan.trackers).find((x) => x.key === key);
            if (!window.confirm(t.confirmRemove.replace("{name}", item?.name || key))) return;
            this._call({ type: isScanner ? "ble_floorplan/remove_scanner" : "ble_floorplan/remove_tracker", key }, () => {
              this._candidates = null;
            });
          })
        );
        root.getElementById("add-tracker")?.addEventListener("change", (e) => {
          const c = (this._candidates?.trackers || []).find((x) => (x.device_id ? `device:${x.device_id}` : `address:${x.address}`) === e.target.value);
          this._add = { ...(this._add || {}), name: c?.name ?? "" };
          this._render();
        });
        root.getElementById("addname")?.addEventListener("input", (e) => {
          this._add = { ...(this._add || {}), name: e.target.value };
        });
        root.getElementById("add-scanner-btn")?.addEventListener("click", () => {
          const source = root.getElementById("add-scanner").value;
          this._call({ type: "ble_floorplan/add_scanner", source, z: this._add?.z ?? 1 }, () => {
            this._candidates = null;
            this._add = null;
            this._note = { kind: "ok", text: t.saved };
          });
        });
        root.getElementById("add-tracker-btn")?.addEventListener("click", () => {
          const value = root.getElementById("add-tracker").value;
          const c = (this._candidates?.trackers || []).find((x) => (x.device_id ? `device:${x.device_id}` : `address:${x.address}`) === value);
          const msg = { type: "ble_floorplan/add_tracker", name: (this._add?.name || c?.name || "").trim() || value, height: this._add?.height ?? 1 };
          if (value.startsWith("device:")) msg.device_id = value.slice(7);
          else msg.address = value.slice(8);
          this._call(msg, () => {
            this._candidates = null;
            this._add = null;
            this._note = { kind: "ok", text: t.saved };
          });
        });
        root.getElementById("calFitN")?.addEventListener("change", (e) => {
          this._cal.fitN = e.target.checked;
        });
        root.querySelectorAll("button[data-delete]").forEach((b) =>
          b.addEventListener("click", () => this._call({ type: "ble_floorplan/calibration/delete", run_id: b.dataset.delete }))
        );
        root.getElementById("calSolve")?.addEventListener("click", () =>
          this._call({ type: "ble_floorplan/calibration/solve", attenuation: this._cal.fitN }, (result) => {
            this._cal.proposal = result;
          })
        );
        root.getElementById("calApply")?.addEventListener("click", () => {
          const pr = this._cal.proposal;
          const msg = { type: "ble_floorplan/calibration/apply", trackers: {}, scanners: {}, pairs: {} };
          if (pr.attenuation) msg.attenuation = pr.attenuation.new;
          for (const [k, v] of Object.entries(pr.trackers)) msg.trackers[k] = v.new;
          for (const [k, v] of Object.entries(pr.scanners)) msg.scanners[k] = v.new;
          for (const [sk, trs] of Object.entries(pr.pairs)) {
            msg.pairs[sk] = {};
            for (const [tk, v] of Object.entries(trs)) msg.pairs[sk][tk] = v.new;
          }
          this._call(msg, () => {
            this._cal.proposal = null;
            this._note = { kind: "ok", text: t.applied };
          });
        });
      }
    }

    // Loads what an opened section of the settings shows, once
    async _loadSection(id) {
      if (id === "plan" && this._layout == null && !this._loadingLayout) {
        this._loadingLayout = true;
        try {
          this._layout = (await this._hass.callWS({ type: "ble_floorplan/get_layout" })).yaml;
        } catch (err) {
          this._note = { kind: "err", text: String(err?.message || err) };
        }
        this._loadingLayout = false;
        if (!this._typing()) this._render();
      }
      if ((id === "scanners" || id === "trackers") && this._candidates == null && !this._loadingCandidates) {
        this._loadingCandidates = true;
        try {
          this._candidates = await this._hass.callWS({ type: "ble_floorplan/candidates" });
        } catch (err) {
          this._note = { kind: "err", text: String(err?.message || err) };
        }
        this._loadingCandidates = false;
        if (!this._typing()) this._render();
      }
    }

    // One call of the API; the result goes to `then`, an error to the panel
    async _call(msg, then) {
      this._busy = true;
      this._note = null;
      this._render();
      try {
        const result = await this._hass.callWS(msg);
        if (then) then(result);
      } catch (err) {
        this._note = { kind: "err", text: String(err?.message || err?.code || err) };
      }
      this._busy = false;
      this._render();
    }

    // Tooltip next to the pointer; content and place survive a redraw
    _bindHover(map, tip) {
      if (!map || !tip) return;
      const place = (e) => {
        const r = map.getBoundingClientRect();
        let x = e.clientX - r.left + 14;
        const y = e.clientY - r.top + 14;
        if (x + tip.offsetWidth > r.width) x = Math.max(0, e.clientX - r.left - tip.offsetWidth - 14);
        tip.style.left = `${x}px`;
        tip.style.top = `${y}px`;
        if (this._hover) Object.assign(this._hover, { px: x, py: y });
      };
      map.querySelectorAll(".scanner, .tracker").forEach((g) => {
        const kind = g.classList.contains("scanner") ? "scanner" : "tracker";
        g.addEventListener("pointerenter", (e) => {
          if (e.pointerType === "touch") return;
          this._hover = { kind, key: g.dataset.key, px: 0, py: 0 };
          tip.innerHTML = this._tipHtml();
          tip.style.display = "block";
          place(e);
        });
        g.addEventListener("pointermove", place);
        g.addEventListener("pointerleave", () => {
          this._hover = null;
          tip.style.display = "none";
        });
      });
    }
  }

  customElements.define("ble-floorplan-card", BleFloorplanCard);

  // Visual editor (dashboard → edit → card): the title only. Everything else
  // is set on the card itself or lives in the integration.
  class BleFloorplanCardEditor extends HTMLElement {
    setConfig(config) {
      this._config = config;
      if (!this.shadowRoot) {
        this.attachShadow({ mode: "open" });
        this._render();
      }
    }

    set hass(hass) {
      this._hass = hass;
    }

    _render() {
      const c = this._config;
      const de = (this._hass?.language || "en").startsWith("de");
      const L = de
        ? { title: "Titel", hint: "Drehung und Beschriftungen stellt man auf der Karte ein, Grundriss, Scanner, Tracker und Einstellungen in der Integration." }
        : { title: "Title", hint: "Rotation and labels are set on the card; the plan, the scanners, the trackers and the settings live in the integration." };
      this.shadowRoot.innerHTML = `
        <style>
          input { width: 100%; box-sizing: border-box; font: inherit; padding: 10px; border-radius: 4px;
            border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
          input:focus { outline: 2px solid var(--primary-color); border-color: transparent; }
          label { display: block; font-size: 0.75em; color: var(--secondary-text-color); margin-bottom: 2px; }
          .hint { color: var(--secondary-text-color); font-size: 0.85em; }
        </style>
        <div><label>${esc(L.title)}</label><input data-path="title" type="text" value="${esc(c.title ?? "")}"></div>
        <p class="hint">${esc(L.hint)}</p>`;
      this.shadowRoot.querySelector("input").addEventListener("change", (e) => {
        const config = { ...this._config };
        if (e.target.value === "") delete config.title;
        else config.title = e.target.value;
        this._config = config;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
      });
    }
  }

  customElements.define("ble-floorplan-card-editor", BleFloorplanCardEditor);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "ble-floorplan-card",
    name: "BLE Floorplan",
    description: "Bluetooth trackers on the floor plan of the BLE Floorplan integration",
  });
  console.info(`ble-floorplan-card ${VERSION}`);
}
