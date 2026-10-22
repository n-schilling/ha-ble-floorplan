// BLE Floorplan card: shows the trackers of the BLE Floorplan integration on the
// floor plan. The plan, the scanners and the live positions come from the
// integration over the WebSocket API; the card only draws. Scanners can be
// dragged to their place (admins), which the integration stores. The
// calibration mode (admins) records runs with the tracker at a known place
// and shows the integration's proposal before it is applied.
const VERSION = "0.2.0";

if (!customElements.get("ble-floorplan-card")) {
  const esc = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
  const COLORS = ["#e8590c", "#1c7ed6", "#2f9e44", "#ae3ec9", "#f59f00", "#0c8599"];

  const TEXTS = {
    en: {
      title: "BLE Floorplan", rooms: "Rooms", scanners: "Scanners", trackers: "Trackers",
      labels: "Show or hide the labels of", rotate: "Rotate the plan by 90°", edit: "Move scanners",
      cancel: "Cancel", save: "Save", tracker: "Tracker", room: "Room", nearest: "Nearest scanner",
      count: "Scanners", notSeen: "not seen", ignored: "ignored", position: "Position",
      height: "Height", hintEdit: "Drag the scanners to where they are, set their heights, then save.",
      hint: "Hover a scanner or a tracker for details, tap a row for the distance circles.",
      noPlan: "No floor plan yet: import one or set it over the WebSocket API.",
      notLoaded: "BLE Floorplan is not set up.", unknown: "–",
      calibrate: "Calibrate", close: "Close", start: "Start run", stop: "Stop run", compute: "Compute",
      apply: "Apply", runs: "Runs", truePos: "True position", tapPlan: "Tap the plan where the tracker is.",
      fitExponent: "Fit the exponent too", noRuns: "No runs yet.", running: "running", preview: "Proposal",
      now: "now", proposed: "proposed", obs: "observations", refPower: "Reference power (dBm)",
      offset: "Scanner offset (dB)", pairs: "Pair correction (dB)", exponent: "Exponent", rms: "RMS error (dB)",
      duration: "Length", delete: "Delete", applied: "Applied.", samples: "samples",
      hintCal: "Put the tracker at a known place, tap that place on the plan, start the run, wait a minute or two, stop it. " +
        "Several places and trackers give a better fit. Compute shows a proposal; nothing changes until you apply it.",
    },
    de: {
      title: "BLE-Grundriss", rooms: "Räume", scanners: "Scanner", trackers: "Tracker",
      labels: "Beschriftung ein-/ausblenden:", rotate: "Grundriss um 90° drehen", edit: "Scanner verschieben",
      cancel: "Abbrechen", save: "Speichern", tracker: "Tracker", room: "Raum", nearest: "Nächster Scanner",
      count: "Scanner", notSeen: "nicht gesehen", ignored: "ignoriert", position: "Position",
      height: "Höhe", hintEdit: "Scanner an ihren echten Standort ziehen, Höhen eintragen, dann speichern.",
      hint: "Maus über Scanner oder Tracker zeigt Details, Zeile antippen die Abstandskreise.",
      noPlan: "Noch kein Grundriss: per Import oder WebSocket-API anlegen.",
      notLoaded: "BLE Floorplan ist nicht eingerichtet.", unknown: "–",
      calibrate: "Kalibrieren", close: "Schließen", start: "Messlauf starten", stop: "Messlauf beenden", compute: "Berechnen",
      apply: "Übernehmen", runs: "Messläufe", truePos: "Wahre Position", tapPlan: "Auf den Grundriss tippen, wo der Tracker liegt.",
      fitExponent: "Exponent mitschätzen", noRuns: "Noch keine Messläufe.", running: "läuft", preview: "Vorschlag",
      now: "jetzt", proposed: "neu", obs: "Beobachtungen", refPower: "Referenzleistung (dBm)",
      offset: "Scanner-Offset (dB)", pairs: "Korrektur je Paar (dB)", exponent: "Exponent", rms: "RMS-Fehler (dB)",
      duration: "Dauer", delete: "Löschen", applied: "Übernommen.", samples: "Samples",
      hintCal: "Tracker an eine bekannte Stelle legen, die Stelle auf dem Grundriss antippen, Messlauf starten, ein, zwei Minuten warten, beenden. " +
        "Mehrere Stellen und Tracker ergeben eine bessere Anpassung. Berechnen zeigt einen Vorschlag; nichts ändert sich, bis er übernommen wird.",
    },
  };

  // Rooms are rectangles (x, y, w, h) or polygons (points), all in metres
  const roomPoints = (r) =>
    r.points || [[r.x, r.y], [r.x + r.w, r.y], [r.x + r.w, r.y + r.h], [r.x, r.y + r.h]];

  const roomLabelPos = (r) => {
    if (r.lx !== undefined) return [r.lx, r.ly];
    const p = roomPoints(r);
    return [p.reduce((a, q) => a + q[0], 0) / p.length, p.reduce((a, q) => a + q[1], 0) / p.length];
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
      this._editing = false;
      this._dragPos = null;
      this._heights = null;
      this._selected = null;
      this._hover = null;
      this._info = { trackers: {}, scanners: {} };
      this._plan = this._plan || null;
      this._positions = this._positions || {};
      this._calibration = this._calibration || { active: null, runs: [] };
      this._calibrating = false;
      this._cal = null;
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

    // A redraw while a field of the calibration panel has the focus would lose the input
    _typing() {
      const el = this.shadowRoot?.activeElement;
      return !!el && (el.tagName === "INPUT" || el.tagName === "SELECT");
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
            return `<tr class="${r.used ? "" : "ign"}"><td>${esc(s.name)}</td><td class="num">${fmt(r.distance)} m</td>` +
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
            `<td class="num">${fmt(e.d)} m</td><td class="num">${e.rssi == null ? "" : `${fmt(e.rssi, 0)} dBm`}</td>` +
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
      if (!plan.rooms.length && !plan.scanners.length) {
        this.shadowRoot.innerHTML = `<style>${this._style()}</style><ha-card>${head}</div>` +
          `<div class="hint">${esc(t.noPlan)}</div></ha-card>`;
        return;
      }
      const fmt = this._n;
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
      const legend = [];
      plan.trackers.forEach((tr, i) => {
        const color = COLORS[i % COLORS.length];
        const pos = this._positions[tr.key] || {};
        const readings = pos.readings || {};
        const seen = pos.x != null && pos.y != null;
        const info = { name: tr.name, color, readings, p: seen ? pos : null, room: pos.room };
        for (const s of plan.scanners) {
          const r = readings[s.key] || {};
          this._info.scanners[s.key].trackers.push({ name: tr.name, color, d: r.distance ?? null, rssi: r.rssi, used: !!r.used });
        }
        if (seen) {
          dots.push(
            `<g class="tracker" data-key="${esc(tr.key)}"><circle cx="${pos.x}" cy="${pos.y}" r="0.28" fill="${color}"/>` +
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
        }
        this._info.trackers[tr.key] = info;
        const nearest = plan.scanners.find((s) => s.key === pos.nearest);
        legend.push({ tr, color, room: seen ? pos.room ?? t.unknown : t.notSeen, nearest: nearest ? nearest.name : t.unknown, n: pos.scanner_count || 0 });
      });

      const scanners = plan.scanners
        .map((s) => {
          const [x, y] = this._scannerPos(s);
          return (
            `<g class="scanner${this._editing ? " editable" : ""}" data-key="${esc(s.key)}">` +
            `<rect x="${x - 0.22}" y="${y - 0.22}" width="0.44" height="0.44" rx="0.08"/>` +
            (this._labels.scanners ? `<text class="slabel" x="${x}" y="${y + 0.62}"${upright(x, y)}>${esc(s.name)}</text>` : "") +
            `</g>`
          );
        })
        .join("");

      // The true position of the run that is going, else the place tapped for the next one
      const active = this._calibration.runs.find((r) => r.id === this._calibration.active);
      const mark = active ? [active.x, active.y] : this._cal && this._cal.x != null ? [this._cal.x, this._cal.y] : null;
      const truePos = this._calibrating && mark
        ? `<g class="truepos${active ? " live" : ""}"><circle cx="${mark[0]}" cy="${mark[1]}" r="0.3"/>` +
          `<line x1="${mark[0] - 0.45}" y1="${mark[1]}" x2="${mark[0] + 0.45}" y2="${mark[1]}"/>` +
          `<line x1="${mark[0]}" y1="${mark[1] - 0.45}" x2="${mark[0]}" y2="${mark[1] + 0.45}"/></g>`
        : "";

      const legendHtml = legend
        .map(
          (l) =>
            `<tr class="${this._selected === l.tr.key ? "sel" : ""}" data-key="${esc(l.tr.key)}">` +
            `<td><span class="dot" style="background:${l.color}"></span>${esc(l.tr.name)}</td>` +
            `<td>${esc(l.room)}</td><td>${esc(l.nearest)}</td><td>${l.n}</td></tr>`
        )
        .join("");

      const heights = this._editing
        ? `<table class="heights"><tr><th>${t.scanners}</th><th>${t.height} (m)</th></tr>` +
          plan.scanners
            .map(
              (s) =>
                `<tr><td>${esc(s.name)}</td><td><input type="number" step="0.1" min="0" max="5" data-height="${esc(s.key)}" ` +
                `value="${esc(this._heights?.[s.key] ?? s.z)}"></td></tr>`
            )
            .join("") +
          `</table>`
        : "";

      const tip = this._hover
        ? `<div class="tip" style="left:${this._hover.px}px;top:${this._hover.py}px">${this._tipHtml()}</div>`
        : `<div class="tip" style="display:none"></div>`;
      const canEdit = !!this._hass?.user?.is_admin;

      this.shadowRoot.innerHTML = `
        <style>${this._style()}</style>
        <ha-card>
          ${head}
            <div class="btns">
              ${[["rooms", t.rooms], ["scanners", t.scanners], ["trackers", t.trackers]]
                .map(([k, l]) => `<button class="toggle${this._labels[k] ? " on" : ""}" data-toggle="${k}" title="${esc(t.labels)} ${esc(l)}">${esc(l)}</button>`)
                .join("")}
              <button id="rotate" title="${esc(t.rotate)}">⟳ ${rot}°</button>
              ${this._editing
                ? `<button id="cancel">${t.cancel}</button><button id="save" class="primary">${t.save}</button>`
                : this._calibrating
                  ? `<button id="calClose">${t.close}</button>`
                  : canEdit ? `<button id="edit">${t.edit}</button><button id="calibrate">${t.calibrate}</button>` : ""}
            </div>
          </div>
          <div class="body${landscape ? " landscape" : ""}"><div class="map${this._calibrating && !active ? " aim" : ""}">
          <svg viewBox="${-pad} ${-pad} ${vbW + 2 * pad} ${vbH + 2 * pad}" preserveAspectRatio="xMidYMin meet">
            <g id="plan" transform="${planTf}">${rooms}${openings}${circles}${truePos}${scanners}${dots.join("")}</g>
          </svg>${tip}</div><div class="side">
          ${this._calibrating
            ? this._calibrationHtml(active)
            : `<table>
            <tr><th>${t.tracker}</th><th>${t.room}</th><th>${t.nearest}</th><th>${t.count}</th></tr>
            ${legendHtml}
          </table>
          ${heights}
          <div class="hint">${this._editing ? t.hintEdit : t.hint}</div>`}
          </div></div>
        </ha-card>`;

      this._bind();
    }

    // The calibration panel: tracker and true position, start/stop, the runs, the proposal
    _calibrationHtml(active) {
      const t = this._t;
      const fmt = this._n;
      const plan = this._plan;
      const cal = this._cal;
      const trackerName = (key) => plan.trackers.find((x) => x.key === key)?.name || key;
      const scannerName = (key) => plan.scanners.find((x) => x.key === key)?.name || key;
      const options = plan.trackers
        .map((tr) => `<option value="${esc(tr.key)}"${cal.tracker === tr.key ? " selected" : ""}>${esc(tr.name)}</option>`)
        .join("");
      const ready = !active && cal.tracker && cal.x != null && !cal.busy;
      const control = active
        ? `<button id="calStop" class="primary"${cal.busy ? " disabled" : ""}>${t.stop}</button>`
        : `<button id="calStart" class="primary"${ready ? "" : " disabled"}>${t.start}</button>`;
      const posText = cal.x == null ? t.tapPlan : `${fmt(cal.x, 2)} / ${fmt(cal.y, 2)} m`;
      const form = `<div class="cal-form">
          <label>${t.tracker}<select id="calTracker"${active ? " disabled" : ""}><option value=""></option>${options}</select></label>
          <label>${t.height} (m)<input id="calHeight" type="number" step="0.05" min="0" max="3" value="${esc(cal.height ?? "")}"${active ? " disabled" : ""}></label>
          <div class="cal-pos"><span>${t.truePos}</span><b>${esc(posText)}</b></div>
          ${control}
        </div>`;

      const scannerCols = plan.scanners.map((sc) => `<th class="num" title="${esc(sc.name)}">${esc(sc.name)}</th>`).join("");
      const runRows = this._calibration.runs
        .map((r) => {
          const counts = plan.scanners.map((sc) => `<td class="num">${r.counts[sc.key] || 0}</td>`).join("");
          const length = r.running ? t.running : `${Math.round(r.duration)} s`;
          return `<tr class="${r.running ? "live" : ""}"><td>${esc(trackerName(r.tracker))}</td>` +
            `<td class="num">${fmt(r.x)} / ${fmt(r.y)}</td><td class="num">${length}</td>${counts}` +
            `<td><button class="small" data-delete="${esc(r.id)}" title="${esc(t.delete)}"${cal.busy ? " disabled" : ""}>✕</button></td></tr>`;
        })
        .join("");
      const runs = this._calibration.runs.length
        ? `<table class="runs"><tr><th>${t.tracker}</th><th class="num">x / y</th><th class="num">${t.duration}</th>${scannerCols}<th></th></tr>${runRows}</table>`
        : `<div class="hint">${t.noRuns}</div>`;

      const finished = this._calibration.runs.some((r) => !r.running);
      const solveRow = `<div class="cal-solve">
          <label class="check"><input id="calFitN" type="checkbox"${cal.fitN ? " checked" : ""}> ${t.fitExponent}</label>
          <button id="calSolve"${finished && !cal.busy ? "" : " disabled"}>${t.compute}</button>
        </div>`;

      let preview = "";
      const p = cal.proposal;
      if (p) {
        const row = (label, v, extra = "") => {
          const changed = v.old !== v.new;
          return `<tr class="${changed ? "changed" : ""}"><td>${label}</td><td class="num">${fmt(v.old, 1)}</td>` +
            `<td class="num">${fmt(v.new, 1)}</td><td class="num">${extra}</td></tr>`;
        };
        const section = (label) => `<tr class="sec"><td colspan="4">${label}</td></tr>`;
        const rows = [];
        if (p.attenuation) rows.push(section(t.exponent), row("n", { old: p.attenuation.old, new: p.attenuation.new }));
        rows.push(section(t.refPower));
        for (const [k, v] of Object.entries(p.trackers)) rows.push(row(esc(trackerName(k)), v, `${v.runs} / ${v.samples}`));
        rows.push(section(t.offset));
        for (const [k, v] of Object.entries(p.scanners)) rows.push(row(esc(scannerName(k)), v, `${v.runs} / ${v.samples}`));
        rows.push(section(t.pairs));
        for (const [sk, trs] of Object.entries(p.pairs)) {
          for (const [tk, v] of Object.entries(trs)) rows.push(row(`${esc(scannerName(sk))} · ${esc(trackerName(tk))}`, v, `${v.runs} / ${v.samples}`));
        }
        rows.push(section(t.rms), row("RMS", p.rms, `${p.observations} ${t.obs}`));
        preview = `<div class="cal-preview"><h4>${t.preview}</h4>
          <table class="diff"><tr><th></th><th class="num">${t.now}</th><th class="num">${t.proposed}</th><th class="num">${t.runs} / ${t.samples}</th></tr>${rows.join("")}</table>
          <button id="calApply" class="primary"${cal.busy || active ? " disabled" : ""}>${t.apply}</button></div>`;
      }
      const note = cal.error ? `<div class="err">${esc(cal.error)}</div>` : cal.note ? `<div class="ok">${esc(cal.note)}</div>` : "";
      return `<div class="cal">${form}<h4>${t.runs}</h4>${runs}${solveRow}${note}${preview}<div class="hint">${t.hintCal}</div></div>`;
    }

    _style() {
      return `
        ha-card { padding: 12px 16px 16px; }
        .head { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
        .title { font-size: 1.2em; font-weight: 500; }
        .btns { display: flex; gap: 6px; flex-wrap: wrap; }
        button { font: inherit; border: 1px solid var(--divider-color); background: var(--secondary-background-color);
          color: var(--primary-text-color); border-radius: 8px; padding: 4px 10px; cursor: pointer; }
        button.primary { background: var(--primary-color); color: var(--text-primary-color); border-color: transparent; }
        button.toggle { color: var(--secondary-text-color); text-decoration: line-through; }
        button.toggle.on { color: var(--primary-text-color); text-decoration: none; border-color: var(--primary-color); }
        .body { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; margin-top: 8px; }
        .map { flex: 1 1 360px; min-width: 0; position: relative; }
        .body.landscape .map { flex-basis: 100%; }
        .side { flex: 1 1 300px; min-width: 0; }
        svg { width: 100%; max-height: 85vh; display: block; touch-action: none; }
        .room { fill: var(--card-background-color); stroke: var(--primary-text-color); stroke-width: 0.08; stroke-linejoin: miter; }
        .room.outdoor { fill: none; stroke-width: 0.04; stroke-dasharray: 0.25 0.15; opacity: 0.6; }
        .zone { fill: none; stroke: var(--secondary-text-color); stroke-width: 0.03; stroke-dasharray: 0.15 0.12; }
        .gap { stroke: var(--card-background-color); stroke-width: 0.12; }
        .opening { stroke: var(--secondary-text-color); stroke-width: 0.025; stroke-dasharray: 0.1 0.08; }
        .rlabel { font-size: 0.38px; fill: var(--secondary-text-color); text-anchor: middle; dominant-baseline: middle; }
        .scanner rect { fill: var(--primary-text-color); }
        .scanner, .tracker { cursor: default; }
        .scanner.editable { cursor: grab; }
        .scanner.editable rect { fill: var(--primary-color); }
        .slabel { font-size: 0.3px; fill: var(--primary-text-color); text-anchor: middle; }
        .tlabel { font-size: 0.36px; font-weight: 600; text-anchor: middle; }
        .range { fill: none; stroke-width: 0.04; stroke-dasharray: 0.12 0.1; opacity: 0.8; }
        .tip { position: absolute; z-index: 3; pointer-events: none; white-space: nowrap; font-size: 0.85em;
          background: var(--card-background-color); color: var(--primary-text-color);
          border: 1px solid var(--divider-color); border-radius: 8px; padding: 6px 10px;
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3); }
        .tip b { display: block; margin-bottom: 2px; }
        .tip .sub { color: var(--secondary-text-color); }
        .tip table { width: auto; margin-top: 4px; }
        .tip td { padding: 1px 8px 1px 0; border: 0; }
        .tip td.num { text-align: right; }
        .tip tr.ign { color: var(--secondary-text-color); }
        table { width: 100%; border-collapse: collapse; font-size: 0.95em; }
        th, td { text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--divider-color); }
        th { color: var(--secondary-text-color); font-weight: 500; }
        tr[data-key] { cursor: pointer; }
        tr.sel td { background: var(--secondary-background-color); }
        .heights { margin-top: 12px; }
        .heights input { width: 5em; font: inherit; padding: 4px 6px; border-radius: 4px;
          border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
        .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }
        .hint { color: var(--secondary-text-color); font-size: 0.85em; margin-top: 6px; }
        .map.aim svg { cursor: crosshair; }
        .truepos circle { fill: none; stroke: var(--primary-color); stroke-width: 0.06; stroke-dasharray: 0.12 0.08; }
        .truepos line { stroke: var(--primary-color); stroke-width: 0.05; }
        .truepos.live circle { stroke-dasharray: none; stroke-width: 0.08; }
        .cal h4 { margin: 14px 0 6px; font-weight: 500; }
        .cal-form { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 12px; align-items: end; }
        .cal-form label { display: flex; flex-direction: column; gap: 2px; font-size: 0.8em; color: var(--secondary-text-color); }
        .cal-form select, .cal-form input, .cal-form button { font: inherit; padding: 6px 8px; border-radius: 6px;
          border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
        .cal-form button.primary { background: var(--primary-color); color: var(--text-primary-color); border-color: transparent; }
        .cal-form button:disabled, .cal-solve button:disabled, .cal-preview button:disabled { opacity: 0.5; cursor: default; }
        .cal-pos { display: flex; flex-direction: column; font-size: 0.8em; color: var(--secondary-text-color); }
        .cal-pos b { font-size: 1.15em; color: var(--primary-text-color); }
        .runs td.num, .runs th.num, .diff td.num, .diff th.num { text-align: right; white-space: nowrap; }
        .runs th { font-size: 0.85em; max-width: 6em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .runs tr.live td { color: var(--primary-color); }
        button.small { padding: 0 6px; line-height: 1.6; }
        .cal-solve { display: flex; gap: 12px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
        label.check { display: flex; align-items: center; gap: 6px; }
        .diff tr.sec td { color: var(--secondary-text-color); font-size: 0.85em; padding-top: 8px; border: 0; }
        .diff tr.changed td:nth-child(3) { font-weight: 600; color: var(--primary-color); }
        .cal-preview button { margin-top: 10px; }
        .err { color: var(--error-color, #c62828); margin-top: 8px; }
        .ok { color: var(--success-color, #2e7d32); margin-top: 8px; }`;
    }

    _bind() {
      const root = this.shadowRoot;
      root.getElementById("edit")?.addEventListener("click", () => {
        this._editing = true;
        this._dragPos = {};
        this._heights = {};
        this._hover = null;
        this._render();
      });
      root.getElementById("cancel")?.addEventListener("click", () => {
        this._editing = false;
        this._dragPos = null;
        this._heights = null;
        this._render();
      });
      root.getElementById("save")?.addEventListener("click", () => this._save());
      root.querySelectorAll("button[data-toggle]").forEach((b) =>
        b.addEventListener("click", () => {
          this._toggleLabel(b.dataset.toggle);
          this._render();
        })
      );
      root.getElementById("rotate")?.addEventListener("click", () => {
        this._setRot((this._rot + 90) % 360);
        this._hover = null;
        this._render();
      });
      root.querySelectorAll("tr[data-key]").forEach((tr) =>
        tr.addEventListener("click", () => {
          const k = tr.dataset.key;
          this._selected = this._selected === k ? null : k;
          this._render();
        })
      );
      root.querySelectorAll("input[data-height]").forEach((input) =>
        input.addEventListener("change", () => {
          const v = parseFloat(input.value);
          if (Number.isFinite(v)) this._heights[input.dataset.height] = v;
        })
      );
      root.getElementById("calibrate")?.addEventListener("click", () => {
        this._calibrating = true;
        this._cal = { tracker: this._plan.trackers[0]?.key || "", height: this._plan.trackers[0]?.height ?? 0,
          x: null, y: null, fitN: false, proposal: null, busy: false, error: null, note: null };
        this._selected = null;
        this._render();
      });
      root.getElementById("calClose")?.addEventListener("click", () => {
        this._calibrating = false;
        this._cal = null;
        this._render();
      });
      const plan = root.getElementById("plan");
      if (this._calibrating) this._bindCalibration(root, plan);
      if (!this._editing) {
        this._bindHover(root.querySelector(".map"), root.querySelector(".tip"));
        return;
      }
      root.querySelectorAll(".scanner").forEach((g) => {
        g.addEventListener("pointerdown", (ev) => {
          ev.preventDefault();
          this._dragging = true;
          const key = g.dataset.key;
          const B = this._bounds;
          const move = (e) => {
            const pt = plan.ownerSVGElement.createSVGPoint();
            pt.x = e.clientX;
            pt.y = e.clientY;
            const p = pt.matrixTransform(plan.getScreenCTM().inverse());
            const x = Math.round(Math.min(Math.max(p.x, 0), B.w) * 10) / 10;
            const y = Math.round(Math.min(Math.max(p.y, 0), B.h) * 10) / 10;
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
      });
    }

    _bindCalibration(root, plan) {
      const cal = this._cal;
      const active = !!this._calibration.active;
      // A tap on the plan sets the true position of the next run
      root.querySelector("svg")?.addEventListener("click", (e) => {
        if (active || !plan) return;
        const pt = plan.ownerSVGElement.createSVGPoint();
        pt.x = e.clientX;
        pt.y = e.clientY;
        const p = pt.matrixTransform(plan.getScreenCTM().inverse());
        const B = this._bounds;
        cal.x = Math.round(Math.min(Math.max(p.x, 0), B.w) * 20) / 20;
        cal.y = Math.round(Math.min(Math.max(p.y, 0), B.h) * 20) / 20;
        cal.error = null;
        this._render();
      });
      root.getElementById("calTracker")?.addEventListener("change", (e) => {
        cal.tracker = e.target.value;
        const tr = this._plan.trackers.find((x) => x.key === cal.tracker);
        if (tr) cal.height = tr.height;
        this._render();
      });
      root.getElementById("calHeight")?.addEventListener("input", (e) => {
        const v = parseFloat(e.target.value);
        if (Number.isFinite(v)) cal.height = v;
      });
      root.getElementById("calFitN")?.addEventListener("change", (e) => {
        cal.fitN = e.target.checked;
      });
      root.getElementById("calStart")?.addEventListener("click", () =>
        this._calCall({ type: "ble_floorplan/calibration/start", tracker: cal.tracker, x: cal.x, y: cal.y, height: cal.height })
      );
      root.getElementById("calStop")?.addEventListener("click", () => this._calCall({ type: "ble_floorplan/calibration/stop" }));
      root.querySelectorAll("button[data-delete]").forEach((b) =>
        b.addEventListener("click", () => this._calCall({ type: "ble_floorplan/calibration/delete", run_id: b.dataset.delete }))
      );
      root.getElementById("calSolve")?.addEventListener("click", () =>
        this._calCall({ type: "ble_floorplan/calibration/solve", attenuation: cal.fitN }, (result) => {
          cal.proposal = result;
        })
      );
      root.getElementById("calApply")?.addEventListener("click", () => {
        const p = cal.proposal;
        const msg = { type: "ble_floorplan/calibration/apply", trackers: {}, scanners: {}, pairs: {} };
        if (p.attenuation) msg.attenuation = p.attenuation.new;
        for (const [k, v] of Object.entries(p.trackers)) msg.trackers[k] = v.new;
        for (const [k, v] of Object.entries(p.scanners)) msg.scanners[k] = v.new;
        for (const [sk, trs] of Object.entries(p.pairs)) {
          msg.pairs[sk] = {};
          for (const [tk, v] of Object.entries(trs)) msg.pairs[sk][tk] = v.new;
        }
        this._calCall(msg, () => {
          cal.proposal = null;
          cal.note = this._t.applied;
        });
      });
    }

    // One call of the calibration API; the result goes to `then`, an error to the panel
    async _calCall(msg, then) {
      const cal = this._cal;
      cal.busy = true;
      cal.error = null;
      cal.note = null;
      this._render();
      try {
        const result = await this._hass.callWS(msg);
        if (then) then(result);
      } catch (err) {
        cal.error = String(err?.message || err?.code || err);
      }
      cal.busy = false;
      if (this._cal === cal) this._render();
    }

    // Tooltip next to the pointer; content and place survive a redraw
    _bindHover(map, tip) {
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

    // Writes every moved scanner and every changed height to the integration
    async _save() {
      const calls = [];
      for (const s of this._plan.scanners) {
        const moved = this._dragPos[s.key];
        const z = this._heights[s.key];
        if (!moved && z === undefined) continue;
        const [x, y] = moved || [s.x, s.y];
        const msg = { type: "ble_floorplan/set_scanner", key: s.key, x, y };
        if (z !== undefined) msg.z = z;
        calls.push(this._hass.callWS(msg));
      }
      try {
        await Promise.all(calls);
      } catch (err) {
        this._error = String(err?.message || err);
      }
      this._editing = false;
      this._dragPos = null;
      this._heights = null;
      this._render();
    }
  }

  customElements.define("ble-floorplan-card", BleFloorplanCard);

  // Visual editor (dashboard → edit → card): the display options only. The plan,
  // the scanners and the trackers live in the integration.
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

    get _t() {
      const lang = (this._hass?.language || "en").slice(0, 2);
      return TEXTS[lang] || TEXTS.en;
    }

    // Plain inputs: ha-textfield is not reliably loaded in the editor dialog
    _field(path, label, value, type = "text") {
      return (
        `<div><label>${esc(label)}</label><input data-path="${esc(path)}" type="${type}"` +
        `${type === "number" ? ' step="any"' : ""} value="${esc(value ?? "")}"></div>`
      );
    }

    _check(path, label, value) {
      return (
        `<label class="check"><input data-path="${esc(path)}" type="checkbox"${value === false ? "" : " checked"}>` +
        ` ${esc(label)}</label>`
      );
    }

    _render() {
      const c = this._config;
      const t = this._t;
      const de = (this._hass?.language || "en").startsWith("de");
      const L = de
        ? { title: "Titel", rotation: "Drehung", labels: "Beschriftungen", hint: "Vorgaben; die Knöpfe auf der Karte überstimmen sie je Browser. Grundriss, Scanner und Tracker werden in der Integration gepflegt." }
        : { title: "Title", rotation: "Rotation", labels: "Labels", hint: "Defaults; the buttons on the card override them per browser. The plan, the scanners and the trackers live in the integration." };
      const rotation = [0, 90, 180, 270]
        .map((v) => `<option value="${v}"${(c.rotation ?? 0) === v ? " selected" : ""}>${v}°</option>`)
        .join("");
      this.shadowRoot.innerHTML = `
        <style>
          .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 12px; }
          h3 { margin: 16px 0 6px; font-weight: 500; }
          input, select { width: 100%; box-sizing: border-box; font: inherit; padding: 10px; border-radius: 4px;
            border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
          input:focus, select:focus { outline: 2px solid var(--primary-color); border-color: transparent; }
          label { display: block; font-size: 0.75em; color: var(--secondary-text-color); margin-bottom: 2px; }
          label.check { font-size: 1em; color: var(--primary-text-color); display: flex; align-items: center; gap: 8px; padding: 8px 0; }
          input[type="checkbox"] { width: 18px; height: 18px; padding: 0; accent-color: var(--primary-color); }
          .hint { color: var(--secondary-text-color); font-size: 0.85em; }
        </style>
        <div class="grid">
          ${this._field("title", L.title, c.title)}
          <div><label>${L.rotation}</label><select data-path="rotation">${rotation}</select></div>
        </div>
        <h3>${L.labels}</h3>
        <div class="grid">
          ${this._check("show_room_labels", t.rooms, c.show_room_labels)}
          ${this._check("show_scanner_labels", t.scanners, c.show_scanner_labels)}
          ${this._check("show_tracker_labels", t.trackers, c.show_tracker_labels)}
        </div>
        <p class="hint">${L.hint}</p>`;
      this.shadowRoot.querySelectorAll("[data-path]").forEach((el) => {
        el.addEventListener("change", () =>
          el.type === "checkbox"
            ? this._update(el.dataset.path, el.checked, "bool")
            : this._update(el.dataset.path, el.value, el.tagName === "SELECT")
        );
      });
    }

    _update(path, value, numeric) {
      const config = { ...this._config };
      const n = parseFloat(value);
      if (numeric === "bool") config[path] = value;
      else if (numeric && Number.isFinite(n)) config[path] = n;
      else if (numeric || value === "") delete config[path];
      else config[path] = value;
      this._config = config;
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
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
