// BLE Floorplan panel: the page in the sidebar where administrators set up the
// floor plan, place the scanners, add the trackers, calibrate, look back on
// the timeline and change the settings. The floor plan is on every page but
// the settings: the scanners are placed on it, the true position of a
// calibration run is tapped on it. Everything comes from the integration over
// the WebSocket API, the page looks like Home Assistant's own.
import {
  COLORS,
  PANEL_PATH,
  PLAN_CSS,
  PlanZoom,
  VERSION,
  bindHover,
  computeBounds,
  crosshair,
  detailHtml,
  dotHtml,
  esc,
  fieldNumber,
  formatter,
  icon,
  keep,
  loadLabels,
  loadRot,
  navigate,
  numOrNull,
  planInfo,
  planSvg,
  snap,
  texts,
  toPlan,
  trackerColor,
} from "./ble-floorplan-plan.js?v=0.11.1";

if (!customElements.get("ble-floorplan-panel")) {
  const ROT_KEY = "ble-floorplan-panel-rot";
  const LABELS_KEY = "ble-floorplan-panel-labels";

  // Tab, icon, text
  const TABS = [
    ["plan", "plan", "tabPlan"],
    ["scanners", "scanner", "tabScanners"],
    ["trackers", "tracker", "tabTrackers"],
    ["calibration", "calibration", "tabCalibration"],
    ["timeline", "timeline", "tabTimeline"],
    ["settings", "settings", "tabSettings"],
  ];

  // Section, setting, text, kind ("num" or "bool")
  const SETTING_FIELDS = [
    ["engine", "attenuation", "attenuation", "num"],
    ["engine", "ref_power_default", "refDefault", "num"],
    ["engine", "max_distance", "maxDistance", "num"],
    ["engine", "smoothing_seconds", "smoothing", "num"],
    ["engine", "min_move", "minMove", "num"],
    ["engine", "clamp", "clamp", "bool"],
    ["engine", "clamp_outdoor", "clampOutdoor", "bool"],
    ["motion", "max_speed", "maxSpeed", "num"],
    ["motion", "jump_distance", "jumpDistance", "num"],
    ["motion", "jump_confirm_seconds", "jumpConfirm", "num"],
    ["motion", "walls", "walls", "bool"],
    ["roomRules", "away_seconds", "awaySeconds", "num"],
    ["roomRules", "room_hold_seconds", "roomHold", "num"],
    ["roomRules", "room_margin", "roomMargin", "num"],
    ["robust", "robust_residual", "robustResidual", "num"],
    ["timeline", "history_days", "historyDays", "num"],
  ];

  // The timeline: newer moments above, the playhead this far below the top (px)
  const PLAYHEAD = 44;
  // Seconds per pixel: zoomed in, zoomed out, at the start
  const SPP_MIN = 0.25;
  const SPP_MAX = 900;
  const SPP_START = 4;
  const SPEEDS = [1, 10, 60, 300, 1800];
  // Tick spacing in seconds, the first that leaves enough room is taken
  const TICKS = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400];
  // Two points this close in time are joined by a straight move, farther apart the first holds
  const LERP_MAX = 10;
  // The way behind a tracker drawn on the plan (s)
  const TRAIL = 120;
  // Today's tracks are fetched again after this long (s)
  const REFETCH = 30;
  const utcDay = (t) => new Date(t * 1000).toISOString().slice(0, 10);
  const dayStart = (d) => Date.parse(`${d}T00:00:00Z`) / 1000;
  const nowS = () => Date.now() / 1000;

  class BleFloorplanPanel extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._tab = "plan";
      this._plan = null;
      this._positions = {};
      this._calibration = { active: null, runs: [] };
      this._rot = loadRot(ROT_KEY, 0);
      this._labels = loadLabels(LABELS_KEY, { rooms: true, scanners: true, trackers: true });
      this._labelMenu = false;
      // The scanner and the tracker open on their pages
      this._selScanner = null;
      this._selTracker = null;
      // Scanner page: null or "move" (tap or drag the scanner to its place)
      this._mode = null;
      this._dragPos = null;
      // The form of the scanner or tracker being edited, of the settings
      this._form = null;
      this._settings = null;
      this._add = {};
      this._candidates = null;
      this._layout = null;
      // The next calibration run: tracker, height, true position
      this._measure = { tracker: null, height: null, x: null, y: null };
      this._cal = { fitN: false, proposal: null };
      this._note = null;
      this._busy = false;
      this._frameKey = null;
      // The timeline: the moment shown (null = live), zoom, playback, the days fetched
      this._tl = { cursor: null, spp: SPP_START, playing: false, speed: 60, days: {}, loading: new Set(), wasLive: true };
      this._bindOnce();
    }

    set hass(hass) {
      const first = !this._hass;
      this._hass = hass;
      if (first) {
        this._subscribe();
        this._load();
      }
      // The menu button follows the sidebar; nothing else needs a redraw
      if (first || this._menuShown !== this._showMenu) this._render();
    }

    set narrow(narrow) {
      this._narrow = narrow;
      this._render();
    }

    set route(route) {
      const tab = (route?.path || "").split("/")[1] || "plan";
      const valid = TABS.some(([id]) => id === tab);
      const key = new URLSearchParams(window.location.search).get("key");
      this._setTab(valid ? tab : "plan", key);
    }

    set panel(panel) {
      this._panelInfo = panel;
    }

    connectedCallback() {
      if (this._hass && !this._unsub) this._subscribe();
      this._render();
    }

    disconnectedCallback() {
      this._unsubscribe();
      this._tlPause();
    }

    get _t() {
      return texts(this._hass);
    }

    get _fmt() {
      return formatter(this._hass);
    }

    get _showMenu() {
      return !!this._narrow || this._hass?.dockedSidebar === "always_hidden";
    }

    async _subscribe() {
      if (this._subscribing || this._unsub || !this._hass) return;
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
        this._bounds = computeBounds(this._plan);
      }
      if (event.positions) this._positions = event.positions;
      if (event.calibration) this._calibration = event.calibration;
      this._render();
    }

    // Changing the page: from a tab, from the address (a link of the card)
    _setTab(tab, key = null) {
      const changed = tab !== this._tab;
      this._tab = tab;
      if (changed || key) {
        this._mode = null;
        this._dragPos = null;
        this._form = null;
        this._note = null;
        this._labelMenu = false;
      }
      if (tab === "scanners" && key) this._selScanner = key;
      if (tab === "trackers" && key) this._selTracker = key;
      if (tab !== "timeline") {
        this._tlPause();
        this._tl.cursor = null;
      }
      this._load();
      this._render();
    }

    _go(tab) {
      navigate(`${PANEL_PATH}/${tab}`);
    }

    // What a page loads once when it opens
    async _load() {
      if (!this._hass) return;
      if (this._tab === "plan" && this._layout == null && !this._loadingLayout) {
        this._loadingLayout = true;
        try {
          this._layout = (await this._hass.callWS({ type: "ble_floorplan/get_layout" })).yaml;
        } catch (err) {
          this._note = { kind: "err", text: String(err?.message || err) };
        }
        this._loadingLayout = false;
        this._render();
      }
      if ((this._tab === "scanners" || this._tab === "trackers") && this._candidates == null && !this._loadingCandidates) {
        this._loadingCandidates = true;
        try {
          this._candidates = await this._hass.callWS({ type: "ble_floorplan/candidates" });
        } catch (err) {
          this._note = { kind: "err", text: String(err?.message || err) };
        }
        this._loadingCandidates = false;
        this._render();
      }
    }

    // One call of the API; the result goes to `then`, an error to the page
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

    // A redraw while a field has the focus would lose the input
    _typing() {
      const el = this.shadowRoot.activeElement;
      return !!el && (el.tagName === "TEXTAREA" || el.tagName === "SELECT" || (el.tagName === "INPUT" && el.type === "text"));
    }

    get _tlAllowed() {
      return (this._plan?.settings?.history_days || 0) > 0;
    }

    get _tlOn() {
      return this._tab === "timeline" && this._tlAllowed && !!this._plan?.rooms.length;
    }

    // ---- Drawing ----

    _render() {
      if (!this._hass) return;
      const plan = this._plan;
      const showMap = this._tab !== "settings" && !!plan?.rooms.length;
      const showSheet = !this._tlOn;
      const key = [this._tab, !!this._narrow, this._showMenu, !!plan, showMap, showSheet, this._tlOn, this._hass.language].join("|");
      if (key !== this._frameKey) {
        this._frameKey = key;
        this._menuShown = this._showMenu;
        this._frame(plan, showMap, showSheet);
      }
      this._update();
    }

    // The parts that stay while the page is open: toolbar, tabs, map, timeline, sheet
    _frame(plan, showMap, showSheet) {
      const t = this._t;
      const tabs = TABS.map(([id, ic, label]) =>
        `<a class="tab${this._tab === id ? " active" : ""}" data-tab="${id}" href="${PANEL_PATH}/${id}">` +
        `${this._narrow ? icon(ic) : ""}<span>${esc(t[label])}</span></a>`).join("");
      const menu = this._showMenu
        ? `<button class="icon-button menu-button" data-act="menu" title="${esc(t.menu)}">${icon("menu")}</button>`
        : "";
      const stage = showMap
        ? `<div class="stage"><div class="map" id="map"><div class="maptools" id="maptools"></div><div id="svg"></div>` +
          `<div class="tip"></div></div>${this._tlOn ? this._tlHtml() : ""}</div>`
        : "";
      const sheet = showSheet ? `<div class="sheet" id="sheet"></div>` : "";
      this.shadowRoot.innerHTML = `
        <style>${PLAN_CSS}${STYLE}</style>
        <div class="app${this._narrow ? " narrow" : ""}">
          <div class="toolbar">${menu}<div class="main-title">BLE Floorplan</div>
            ${this._narrow ? "" : `<nav class="tabs">${tabs}</nav>`}</div>
          <div class="content ${this._tab}${showMap ? " withmap" : ""}${showSheet ? "" : " nosheet"}">${stage}${sheet}</div>
          ${this._narrow ? `<nav class="bottom-tabs">${tabs}</nav>` : ""}
        </div>`;
      this._sheetHtml = null;
      this._svgHtml = null;
      this._toolsHtml = null;
      if (showMap) {
        this._zoomer().attach(this.shadowRoot.getElementById("map"));
        this._refreshTip = bindHover(this.shadowRoot.getElementById("map"), this.shadowRoot.querySelector(".tip"),
          (kind, k) => detailHtml(this._info, kind, k, this._t, this._fmt));
      }
      if (this._tlOn) this._tlBind(this.shadowRoot);
    }

    _update() {
      const root = this.shadowRoot;
      const plan = this._plan;
      if (plan) this._info = planInfo(plan, this._shownPositions(), (s) => this._scannerPos(s));
      const map = root.getElementById("map");
      if (map && plan && !this._dragging) {
        map.classList.toggle("aim", this._aiming);
        const svg = this._svg();
        if (svg !== this._svgHtml) {
          this._svgHtml = svg;
          root.getElementById("svg").innerHTML = svg;
        }
        const tools = this._toolsHtmlNow();
        if (tools !== this._toolsHtml) {
          this._toolsHtml = tools;
          root.getElementById("maptools").innerHTML = tools;
        }
        this._refreshTip?.();
      }
      const sheet = root.getElementById("sheet");
      if (sheet && !this._typing()) {
        const html = this._sheet();
        if (html !== this._sheetHtml) {
          this._sheetHtml = html;
          sheet.innerHTML = html;
        }
      }
      this._tlFrame();
    }

    // One zoom for every tab: the view stays when the tab changes
    _zoomer() {
      if (!this._zoom) {
        this._zoom = new PlanZoom({
          geom: () => ({ bounds: this._bounds || computeBounds(this._plan), rot: this._rot }),
          texts: () => this._t,
          wheel: true,
        });
      }
      return this._zoom;
    }

    _scannerPos(s) {
      return (this._dragPos && this._dragPos[s.key]) || [s.x, s.y];
    }

    // The map takes a tap for a place: a new run's true position, a scanner's new place
    get _aiming() {
      if (this._tab === "calibration") return !this._calibration.active && !!this._measure.tracker;
      return this._tab === "scanners" && this._mode === "move";
    }

    _svg() {
      const plan = this._plan;
      const tab = this._tab;
      let marks = "";
      if (tab === "calibration") {
        // Where the runs were taken, coloured by tracker; the next or the running one as a crosshair
        marks = this._calibration.runs
          .filter((r) => !r.running)
          .map((r) => `<circle class="runmark" cx="${r.x}" cy="${r.y}" r="0.16" fill="${trackerColor(plan, r.tracker)}"/>`)
          .join("");
        const active = this._calibration.runs.find((r) => r.id === this._calibration.active);
        if (active) marks += crosshair(active.x, active.y, true);
        else if (this._measure.x != null) marks += crosshair(this._measure.x, this._measure.y, false);
      }
      return planSvg(plan, {
        bounds: this._bounds || computeBounds(plan),
        rot: this._rot,
        labels: this._labels,
        positions: this._shownPositions(),
        scannerPos: (s) => this._scannerPos(s),
        circles: tab === "trackers" ? this._selTracker : null,
        openTracker: tab === "trackers" ? this._selTracker : tab === "calibration" ? this._measure.tracker : null,
        openScanner: tab === "scanners" ? this._selScanner : null,
        movable: tab === "scanners" && this._mode === "move" ? this._selScanner : null,
        marks,
        trails: this._tlTrailsHtml(),
        align: "xMidYMid",
        view: this._zoom?.view,
      });
    }

    _toolsHtmlNow() {
      const t = this._t;
      const menu = this._labelMenu
        ? `<div class="menu">${[["rooms", t.rooms], ["scanners", t.scanners], ["trackers", t.trackers]]
            .map(([k, l]) => `<label><input type="checkbox" data-label="${k}"${this._labels[k] ? " checked" : ""}>${esc(l)}</label>`)
            .join("")}</div>`
        : "";
      return `<button class="icon-button" data-act="rotate" title="${esc(t.rotate)}">${icon("rotate")}</button>` +
        `<span class="menuwrap"><button class="icon-button${this._labelMenu ? " on" : ""}" data-act="labels" title="${esc(t.labels)}">${icon("label")}</button>${menu}</span>`;
    }

    // ---- Building blocks, as Home Assistant draws them ----

    _card(title, body, actions = "", cls = "") {
      return `<div class="card ${cls}">${title ? `<h2>${title}</h2>` : ""}<div class="card-content">${body}</div>` +
        `${actions ? `<div class="card-actions">${actions}</div>` : ""}</div>`;
    }

    _btn(act, label, { kind = "", disabled = false, data = "" } = {}) {
      return `<button class="btn ${kind}" data-act="${act}"${data}${disabled || this._busy ? " disabled" : ""}>${esc(label)}</button>`;
    }

    _field(name, label, value, { text = false, wide = false } = {}) {
      const v = text ? value ?? "" : fieldNumber(this._hass, value);
      return `<label class="field${wide ? " wide" : ""}"><span>${esc(label)}</span>` +
        `<input type="text"${text ? "" : ' inputmode="decimal"'} data-f="${esc(name)}" value="${esc(v)}"></label>`;
    }

    _select(name, label, options, value) {
      return `<label class="field wide"><span>${esc(label)}</span><select data-f="${esc(name)}">` +
        options.map(([v, l]) => `<option value="${esc(v)}"${v === value ? " selected" : ""}>${esc(l)}</option>`).join("") +
        `</select></label>`;
    }

    _kv(rows) {
      return `<table class="kv">${rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${v}</td></tr>`).join("")}</table>`;
    }

    _noteHtml() {
      return this._note ? `<div class="alert ${this._note.kind}">${esc(this._note.text)}</div>` : "";
    }

    // ---- The sheet of each page ----

    _sheet() {
      const t = this._t;
      if (!this._plan) return this._card("", `<div class="muted">${esc(this._error || "…")}</div>`);
      const page = {
        plan: () => this._planSheet(),
        scanners: () => this._scannersSheet(),
        trackers: () => this._trackersSheet(),
        calibration: () => this._calibrationSheet(),
        timeline: () => this._card(t.timeline, `<div class="muted">${esc(t.timelineOff)}</div>`,
          `<span></span>${this._btn("go-settings", t.tabSettings)}`),
        settings: () => this._settingsSheet(),
      }[this._tab];
      const empty = !this._plan.rooms.length && this._tab !== "plan" && this._tab !== "settings"
        ? `<div class="alert info">${esc(t.startHere)}</div>`
        : "";
      return this._noteHtml() + empty + page();
    }

    _planSheet() {
      const t = this._t;
      const empty = this._plan.rooms.length ? "" : `<div class="alert info">${esc(t.startHere)}</div>`;
      const body = `<textarea data-f="layout" rows="22" spellcheck="false" wrap="off">${esc(this._layout ?? "…")}</textarea>` +
        `<div class="muted small">${esc(t.layoutHint)}</div>`;
      return empty + this._card(t.plan, body, `<span></span>${this._btn("save-layout", t.save, { kind: "filled", disabled: this._layout == null })}`);
    }

    _item(act, key, lead, headline, supporting, active) {
      return `<button class="item${active ? " active" : ""}" data-act="${act}" data-key="${esc(key)}">${lead}` +
        `<span class="text"><span class="headline">${esc(headline)}</span><span class="supporting">${supporting}</span></span>` +
        `<span class="next">${icon("chevron")}</span></button>`;
    }

    _addCard(kind) {
      const t = this._t;
      const cand = this._candidates;
      const title = kind === "scanner" ? t.addScanner : t.addTracker;
      if (cand == null) return this._card(title, `<div class="muted">…</div>`);
      const items = kind === "scanner" ? cand.scanners : cand.trackers;
      if (!items.length) return this._card(title, `<div class="muted">${esc(t.allOnPlan)}</div>`);
      const value = (c) => (kind === "scanner" ? c.source : c.device_id ? `device:${c.device_id}` : `address:${c.address}`);
      const options = items.map((c) => [value(c), kind === "scanner" ? `${c.name} (${c.source})` : `${c.name}${c.address ? ` (${c.address})` : ""}`]);
      const chosen = this._add[kind] && options.some(([v]) => v === this._add[kind]) ? this._add[kind] : options[0][0];
      this._add[kind] = chosen;
      let body = this._select(`add:${kind}`, t.add, options, chosen);
      if (kind === "scanner") {
        body += `<div class="fields">${this._field("add:z", `${t.height} (m)`, this._add.z ?? 1)}</div>`;
      } else {
        const c = items.find((x) => value(x) === chosen);
        body += `<div class="fields">${this._field("add:name", t.name, this._add.name ?? c?.name ?? "", { text: true })}` +
          `${this._field("add:height", `${t.height} (m)`, this._add.height ?? 1)}</div>`;
      }
      return this._card(title, body, `<span></span>${this._btn(`add-${kind}`, t.add, { kind: "filled" })}`);
    }

    _pairsText(scannerKey, trackerKey) {
      const v = this._plan.pair_offsets?.[scannerKey]?.[trackerKey];
      return v == null ? null : `${v > 0 ? "+" : ""}${this._fmt(v)}`;
    }

    _scannersSheet() {
      const t = this._t;
      const fmt = this._fmt;
      const plan = this._plan;
      const s = plan.scanners.find((x) => x.key === this._selScanner);
      if (!s) {
        const items = plan.scanners.map((x) => {
          const heard = this._info.scanners[x.key].trackers.filter((e) => e.d != null).length;
          return this._item("sel-scanner", x.key, `<span class="icon-bg">${icon("scanner")}</span>`, x.name,
            `${fmt(x.x)} / ${fmt(x.y)} m · ${t.height} ${fmt(x.z)} m · ${esc(t.hears)} ${esc(t.trackerCount.replace("{n}", heard))}`);
        });
        return this._card(t.scanners, items.join("") || `<div class="muted">${esc(t.none)}</div>`, "", "list") + this._addCard("scanner");
      }
      const info = this._info.scanners[s.key];
      const head = `<div class="card-head"><button class="icon-button" data-act="back" title="${esc(t.back)}">${icon("back")}</button>` +
        `<span>${esc(s.name)}</span></div>`;
      const hears = `<table class="data"><tr><th>${esc(t.tracker)}</th><th class="n">m</th><th class="n">dBm</th></tr>` +
        info.trackers.map((e) => `<tr class="${e.d == null || !e.used ? "ign" : ""}"><td><span class="dot" style="background:${e.color}"></span>${esc(e.name)}</td>` +
          `<td class="n">${e.d == null ? esc(t.notSeen) : fmt(e.d)}</td><td class="n">${e.rssi == null ? "" : fmt(e.rssi, 0)}</td></tr>`).join("") +
        `</table>`;
      let body;
      let actions;
      if (this._form) {
        const f = this._form;
        body = `<div class="fields">${this._field("form:x", "x (m)", f.x)}${this._field("form:y", "y (m)", f.y)}${this._field("form:z", `${t.height} (m)`, f.z)}` +
          `${this._field("form:rssi_offset", `${t.offset} (dB)`, f.rssi_offset)}</div>` +
          `<div class="subhead">${esc(t.pairs)} (dB)</div><div class="fields">` +
          plan.trackers.map((tr) => this._field(`form:pair:${tr.key}`, tr.name, f.pairs[tr.key])).join("") + `</div>`;
        actions = `<span></span><span>${this._btn("cancel", t.cancel)}${this._btn("save-scanner", t.save, { kind: "filled" })}</span>`;
      } else if (this._mode === "move") {
        const [x, y] = this._scannerPos(s);
        body = `<div class="alert info">${esc(t.hintMove)}</div>` + this._kv([[t.position, `${fmt(x, 2)} / ${fmt(y, 2)} m`]]);
        actions = `<span></span><span>${this._btn("cancel", t.cancel)}${this._btn("save-move", t.save, { kind: "filled" })}</span>`;
      } else {
        const pairs = plan.trackers.map((tr) => [tr.name, this._pairsText(s.key, tr.key)]).filter(([, v]) => v);
        body = this._kv([
          [t.position, `${fmt(s.x)} / ${fmt(s.y)} m`],
          [t.height, `${fmt(s.z)} m`],
          [t.offset, `${s.rssi_offset > 0 ? "+" : ""}${fmt(s.rssi_offset)} dB`],
          [t.pairs, pairs.length ? pairs.map(([n, v]) => `${esc(n)} ${v}`).join(" · ") : esc(t.none)],
        ]) + `<div class="subhead">${esc(t.hears)}</div>${hears}`;
        actions = this._btn("remove-scanner", t.remove, { kind: "danger" }) +
          `<span>${this._btn("move", t.move)}${this._btn("edit-scanner", t.edit)}</span>`;
      }
      return `<div class="card">${head}<div class="card-content">${body}</div><div class="card-actions">${actions}</div></div>`;
    }

    _trackersSheet() {
      const t = this._t;
      const fmt = this._fmt;
      const plan = this._plan;
      const tr = plan.trackers.find((x) => x.key === this._selTracker);
      if (!tr) {
        const items = plan.trackers.map((x) => {
          const info = this._info.trackers[x.key];
          const status = info.p ? `${esc(info.room || t.unknown)} · ${esc(t.seenBy.replace("{n}", info.p.scanner_count))}` : esc(t.notSeen);
          return this._item("sel-tracker", x.key, `<span class="icon-bg" style="background:${info.color}">${icon("tracker")}</span>`, x.name, status);
        });
        return this._card(t.trackers, items.join("") || `<div class="muted">${esc(t.none)}</div>`, "", "list") + this._addCard("tracker");
      }
      const info = this._info.trackers[tr.key];
      const head = `<div class="card-head"><button class="icon-button" data-act="back" title="${esc(t.back)}">${icon("back")}</button>` +
        `<span class="dot" style="background:${info.color}"></span><span>${esc(tr.name)}</span></div>`;
      const status = info.p
        ? `${esc(info.room || t.unknown)} · ${fmt(info.p.x)} / ${fmt(info.p.y)} m · ${esc(t.seenBy.replace("{n}", info.p.scanner_count))}`
        : esc(t.notSeen);
      const readings = `<table class="data"><tr><th>${esc(t.scanner)}</th><th class="n">m</th><th class="n">dBm</th></tr>` +
        plan.scanners.map((s) => {
          const r = info.readings[s.key] || {};
          return `<tr class="${r.distance == null || !r.used ? "ign" : ""}"><td>${esc(s.name)}</td>` +
            `<td class="n">${r.distance == null ? esc(t.notSeen) : fmt(r.distance)}</td><td class="n">${r.rssi == null ? "" : fmt(r.rssi, 0)}</td></tr>`;
        }).join("") + `</table>`;
      let body;
      let actions;
      if (this._form) {
        const f = this._form;
        body = `<div class="fields">${this._field("form:height", `${t.height} (m)`, f.height)}` +
          `${this._field("form:ref_power", `${t.refPower} (dBm, ${t.default} ${fmt(plan.settings.ref_power_default, 0)})`, f.ref_power)}</div>` +
          `<div class="subhead">${esc(t.pairs)} (dB)</div><div class="fields">` +
          plan.scanners.map((s) => this._field(`form:pair:${s.key}`, s.name, f.pairs[s.key])).join("") + `</div>`;
        actions = `<span></span><span>${this._btn("cancel", t.cancel)}${this._btn("save-tracker", t.save, { kind: "filled" })}</span>`;
      } else {
        const ref = tr.ref_power == null ? `${esc(t.default)} (${fmt(plan.settings.ref_power_default, 0)} dBm)` : `${fmt(tr.ref_power)} dBm`;
        const pairs = plan.scanners.map((s) => [s.name, this._pairsText(s.key, tr.key)]).filter(([, v]) => v);
        body = `<div class="status">${status}</div>` + this._kv([
          [t.height, `${fmt(tr.height, 2)} m`],
          [t.refPower, ref],
          [t.pairs, pairs.length ? pairs.map(([n, v]) => `${esc(n)} ${v}`).join(" · ") : esc(t.none)],
        ]) + `<div class="subhead">${esc(t.heardBy)}</div>${readings}`;
        actions = this._btn("remove-tracker", t.remove, { kind: "danger" }) +
          `<span>${this._btn("measure-tracker", t.measure)}${this._btn("edit-tracker", t.edit)}</span>`;
      }
      return `<div class="card">${head}<div class="card-content">${body}</div><div class="card-actions">${actions}</div></div>`;
    }

    _calibrationSheet() {
      const t = this._t;
      const fmt = this._fmt;
      const plan = this._plan;
      const name = (key) => plan.trackers.find((x) => x.key === key)?.name || key;
      const sname = (key) => plan.scanners.find((x) => x.key === key)?.name || key;
      const active = this._calibration.runs.find((r) => r.id === this._calibration.active);
      let run;
      if (active) {
        const rows = plan.scanners
          .map((s) => `<tr><td>${esc(s.name)}</td><td class="n">${active.counts?.[s.key] || 0}</td></tr>`)
          .join("");
        run = this._card(`${esc(t.measure)} · ${esc(t.running)}`,
          this._kv([
            [t.tracker, `<span class="dot" style="background:${trackerColor(plan, active.tracker)}"></span>${esc(name(active.tracker))}`],
            [t.runAt, `${fmt(active.x, 2)} / ${fmt(active.y, 2)} m · ${esc(t.height)} ${fmt(active.height, 2)} m`],
          ]) + `<table class="data"><tr><th>${esc(t.scanner)}</th><th class="n">${esc(t.samples)}</th></tr>${rows}</table>`,
          `<span></span>${this._btn("cal-stop", t.stop, { kind: "filled" })}`);
      } else if (!plan.trackers.length) {
        run = this._card(t.newRun, `<div class="muted">${esc(t.none)}</div>`);
      } else {
        const m = this._measure;
        if (!plan.trackers.some((x) => x.key === m.tracker)) {
          m.tracker = plan.trackers[0].key;
          m.height = plan.trackers[0].height;
        }
        const ready = m.x != null;
        run = this._card(t.newRun,
          this._select("measure:tracker", t.pickTracker, plan.trackers.map((x) => [x.key, x.name]), m.tracker) +
          `<div class="fields">${this._field("measure:height", `${t.height} (m)`, m.height)}</div>` +
          (ready ? this._kv([[t.runAt, `${fmt(m.x, 2)} / ${fmt(m.y, 2)} m`]]) : `<div class="alert info">${esc(t.hintMeasure)}</div>`),
          `<span></span>${this._btn("cal-start", t.start, { kind: "filled", disabled: !ready })}`);
      }
      const runs = this._calibration.runs;
      const cols = plan.scanners.map((s) => `<th class="n" title="${esc(s.name)}">${esc(s.name)}</th>`).join("");
      const rows = runs.map((r) => {
        const counts = plan.scanners.map((s) => `<td class="n">${r.counts?.[s.key] || 0}</td>`).join("");
        const length = r.running ? esc(t.running) : `${Math.round(r.duration)} s`;
        return `<tr class="${r.running ? "live" : ""}"><td class="nowrap"><span class="dot" style="background:${trackerColor(plan, r.tracker)}"></span>${esc(name(r.tracker))}</td>` +
          `<td class="n">${fmt(r.x)} / ${fmt(r.y)}</td><td class="n">${length}</td>${counts}` +
          `<td><button class="icon-button small" data-act="cal-delete" data-key="${esc(r.id)}" title="${esc(t.delete)}"${this._busy ? " disabled" : ""}>${icon("delete")}</button></td></tr>`;
      }).join("");
      const table = runs.length
        ? `<div class="scroll"><table class="data runs"><tr><th>${esc(t.tracker)}</th><th class="n">x / y</th><th class="n">${esc(t.duration)}</th>${cols}<th></th></tr>${rows}</table></div>`
        : `<div class="muted">${esc(t.noRuns)}</div>`;
      const finished = runs.some((r) => !r.running);
      let preview = "";
      const pr = this._cal.proposal;
      if (pr) {
        const row = (label, v, extra = "") =>
          `<tr class="${v.old !== v.new ? "changed" : ""}"><td>${label}</td><td class="n">${fmt(v.old, 1)}</td>` +
          `<td class="n">${fmt(v.new, 1)}</td><td class="n">${extra}</td></tr>`;
        const section = (label) => `<tr class="sec"><td colspan="4">${esc(label)}</td></tr>`;
        const out = [];
        if (pr.attenuation) out.push(section(t.exponent), row("n", pr.attenuation));
        out.push(section(`${t.refPower} (dBm)`));
        for (const [k, v] of Object.entries(pr.trackers)) out.push(row(esc(name(k)), v, `${v.runs} / ${v.samples}`));
        out.push(section(`${t.offset} (dB)`));
        for (const [k, v] of Object.entries(pr.scanners)) out.push(row(esc(sname(k)), v, `${v.runs} / ${v.samples}`));
        out.push(section(`${t.pairs} (dB)`));
        for (const [sk, trs] of Object.entries(pr.pairs)) {
          for (const [tk, v] of Object.entries(trs)) out.push(row(`${esc(sname(sk))} · ${esc(name(tk))}`, v, `${v.runs} / ${v.samples}`));
        }
        out.push(section(t.rms), row("RMS", pr.rms, `${pr.observations} ${esc(t.obs)}`));
        preview = `<div class="subhead">${esc(t.preview)}</div><div class="scroll"><table class="data diff"><tr><th></th>` +
          `<th class="n">${esc(t.now)}</th><th class="n">${esc(t.proposed)}</th><th class="n">${esc(t.runs)} / ${esc(t.samples)}</th></tr>${out.join("")}</table></div>`;
      }
      const advanced = this._card(t.advanced,
        `<div class="muted">${esc(t.advancedHint)}</div>` +
        `<label class="setting"><span class="text"><span class="headline">${esc(t.fitExponent)}</span></span>` +
        `<input type="checkbox" class="switch" data-f="cal:fitN"${this._cal.fitN ? " checked" : ""}></label>${preview}`,
        `<span></span><span>${this._btn("cal-solve", t.compute, { disabled: !finished })}` +
        `${pr ? this._btn("cal-apply", t.apply, { kind: "filled", disabled: !!active }) : ""}</span>`);
      return run + this._card(t.runs, `<div class="muted small">${esc(t.calHint)}</div>${table}`) + advanced;
    }

    _settingsSheet() {
      const t = this._t;
      const plan = this._plan;
      const f = this._settings || plan.settings;
      const sections = {};
      for (const [sec, key, label, kind] of SETTING_FIELDS) {
        const control = kind === "bool"
          ? `<input type="checkbox" class="switch" data-f="setting:${key}"${f[key] ? " checked" : ""}>`
          : `<input type="text" class="num" inputmode="decimal" data-f="setting:${key}" value="${esc(fieldNumber(this._hass, f[key]))}">`;
        sections[sec] = (sections[sec] || "") +
          `<label class="setting"><span class="text"><span class="headline">${esc(t[label])}</span></span>${control}</label>`;
      }
      const save = `<span></span>${this._btn("save-settings", t.save, { kind: "filled" })}`;
      return ["engine", "motion", "roomRules", "robust", "timeline"]
        .map((id) => this._card(t[id], sections[id] + (id === "timeline" ? `<div class="muted small">${esc(t.timelineHint)}</div>` : ""), save))
        .join("");
    }

    // What a stop or a delete saved for the tracker
    _fitNote(fit) {
      const t = this._t;
      const fmt = this._fmt;
      if (!fit) return { kind: "err", text: t.fitNone };
      const sname = (key) => this._plan.scanners.find((x) => x.key === key)?.name || key;
      const pairs = Object.entries(fit.pairs)
        .map(([k, v]) => `${sname(k)} ${v.new > 0 ? "+" : ""}${fmt(v.new)}`)
        .join(" · ");
      const text = t.fitSaved
        .replace("{runs}", fit.runs === 1 ? t.runOne : t.runMany.replace("{n}", fit.runs))
        .replace("{ref}", fmt(fit.ref_power.new))
        .replace("{old}", fmt(fit.ref_power.old))
        .replace("{pairs}", pairs || t.none)
        .replace("{rmsOld}", fmt(fit.rms.old))
        .replace("{rmsNew}", fmt(fit.rms.new));
      return { kind: "ok", text };
    }

    // ---- Input ----

    // One listener each on the shadow root: the content under it is redrawn
    _bindOnce() {
      const root = this.shadowRoot;
      root.addEventListener("click", (e) => {
        const tab = e.target.closest?.("a[data-tab]");
        if (tab) {
          e.preventDefault();
          if (tab.dataset.tab !== this._tab || window.location.search) this._go(tab.dataset.tab);
          return;
        }
        const act = e.target.closest?.("[data-act]");
        if (act) {
          if (!act.disabled) this._act(act.dataset.act, act);
          return;
        }
        if (e.target.closest?.("#map")) this._mapClick(e);
      });
      root.addEventListener("input", (e) => this._input(e.target));
      root.addEventListener("change", (e) => {
        const el = e.target;
        if (el.dataset.label) {
          this._labels = { ...this._labels, [el.dataset.label]: el.checked };
          keep(LABELS_KEY, this._labels);
          this._render();
          return;
        }
        this._input(el);
        // A select keeps the focus after the choice, the page would not redraw
        if (el.tagName === "SELECT") {
          el.blur();
          this._render();
        }
        if (el.type === "checkbox") this._render();
      });
      root.addEventListener("pointerdown", (e) => this._dragStart(e));
    }

    _input(el) {
      const name = el.dataset?.f;
      if (!name) return;
      const v = el.type === "checkbox" ? el.checked : el.value;
      const [group, key, sub] = name.split(":");
      if (group === "layout") this._layout = v;
      else if (group === "form") {
        if (key === "pair") this._form.pairs[sub] = numOrNull(v);
        else this._form[key] = numOrNull(v);
      } else if (group === "setting") {
        if (!this._settings) this._settings = { ...this._plan.settings };
        this._settings[key] = el.type === "checkbox" ? v : numOrNull(v);
      } else if (group === "add") {
        if (key === "scanner" || key === "tracker") {
          this._add[key] = v;
          if (key === "tracker") this._add.name = null;
        } else if (key === "name") this._add.name = v;
        else this._add[key] = numOrNull(v);
      } else if (group === "measure") {
        if (key === "tracker") {
          this._measure.tracker = v;
          this._measure.height = this._plan.trackers.find((x) => x.key === v)?.height ?? 1;
        } else this._measure.height = numOrNull(v) ?? this._measure.height;
      } else if (group === "cal") this._cal.fitN = v;
    }

    _mapClick(e) {
      const plan = this._plan;
      if (!plan || e.target.closest?.(".maptools")) return;
      if (this._aiming) {
        const [x, y] = toPlan(this.shadowRoot, e, this._bounds);
        if (this._tab === "calibration") {
          this._measure.x = snap(x);
          this._measure.y = snap(y);
        } else {
          this._dragPos = { [this._selScanner]: [snap(x), snap(y)] };
        }
        this._render();
        return;
      }
      const g = e.target.closest?.(".scanner, .tracker");
      if (!g) return;
      const kind = g.classList.contains("scanner") ? "scanners" : "trackers";
      const key = g.dataset.key;
      if (this._tab === kind) {
        this._form = null;
        this._mode = null;
        this._note = null;
        if (kind === "scanners") this._selScanner = this._selScanner === key ? null : key;
        else this._selTracker = this._selTracker === key ? null : key;
        this._render();
      } else if (this._tab === "calibration" && kind === "trackers" && !this._calibration.active) {
        this._measure.tracker = key;
        this._measure.height = plan.trackers.find((x) => x.key === key)?.height ?? 1;
        this._render();
      } else if (this._tab !== "calibration" && this._tab !== "timeline") {
        navigate(`${PANEL_PATH}/${kind}?key=${encodeURIComponent(key)}`);
      }
    }

    // Drag the scanner being moved
    _dragStart(ev) {
      const g = ev.target.closest?.(".scanner.movable");
      if (!g) return;
      ev.preventDefault();
      this._dragging = true;
      const key = g.dataset.key;
      const rect = g.querySelector("rect");
      const text = g.querySelector("text");
      const move = (e) => {
        const [px, py] = toPlan(this.shadowRoot, e, this._bounds);
        const x = snap(px);
        const y = snap(py);
        this._dragPos = { [key]: [x, y] };
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
        // The click that ends the drag must not place the scanner again
        setTimeout(() => {
          this._dragging = false;
          this._render();
        }, 0);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    }

    _act(act, el) {
      const t = this._t;
      const plan = this._plan;
      const key = el.dataset.key;
      const saved = () => {
        this._form = null;
        this._note = { kind: "ok", text: t.saved };
      };
      switch (act) {
        case "menu":
          this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
          return;
        case "rotate":
          this._rot = (this._rot + 90) % 360;
          keep(ROT_KEY, String(this._rot));
          if (this._zoom) this._zoom.view = null;
          break;
        case "labels":
          this._labelMenu = !this._labelMenu;
          break;
        case "go-settings":
          this._go("settings");
          return;
        case "back":
          if (this._tab === "scanners") this._selScanner = null;
          else this._selTracker = null;
          this._form = null;
          this._mode = null;
          this._dragPos = null;
          this._note = null;
          if (window.location.search) window.history.replaceState(null, "", `${PANEL_PATH}/${this._tab}`);
          break;
        case "sel-scanner":
          this._selScanner = key;
          this._note = null;
          break;
        case "sel-tracker":
          this._selTracker = key;
          this._note = null;
          break;
        case "cancel":
          this._form = null;
          this._mode = null;
          this._dragPos = null;
          break;
        case "save-layout":
          this._call({ type: "ble_floorplan/set_layout", yaml: this._layout }, (result) => {
            this._layout = result.yaml;
            this._note = { kind: "ok", text: t.planSaved };
          });
          return;
        case "move":
          this._mode = "move";
          this._dragPos = {};
          this._note = null;
          break;
        case "save-move": {
          const s = plan.scanners.find((x) => x.key === this._selScanner);
          const [x, y] = this._scannerPos(s);
          this._call({ type: "ble_floorplan/set_scanner", key: s.key, x, y }, () => {
            this._mode = null;
            this._dragPos = null;
            saved();
          });
          return;
        }
        case "edit-scanner": {
          const s = plan.scanners.find((x) => x.key === this._selScanner);
          const pairs = {};
          for (const tr of plan.trackers) pairs[tr.key] = plan.pair_offsets?.[s.key]?.[tr.key] ?? null;
          this._form = { x: s.x, y: s.y, z: s.z, rssi_offset: s.rssi_offset, pairs };
          this._note = null;
          break;
        }
        case "save-scanner": {
          const s = plan.scanners.find((x) => x.key === this._selScanner);
          const f = this._form;
          this._call({
            type: "ble_floorplan/set_scanner", key: s.key, x: f.x ?? s.x, y: f.y ?? s.y, z: f.z ?? s.z,
            rssi_offset: f.rssi_offset ?? s.rssi_offset, pair_offsets: f.pairs,
          }, saved);
          return;
        }
        case "edit-tracker": {
          const tr = plan.trackers.find((x) => x.key === this._selTracker);
          const pairs = {};
          for (const s of plan.scanners) pairs[s.key] = plan.pair_offsets?.[s.key]?.[tr.key] ?? null;
          this._form = { height: tr.height, ref_power: tr.ref_power ?? null, pairs };
          this._note = null;
          break;
        }
        case "save-tracker": {
          const tr = plan.trackers.find((x) => x.key === this._selTracker);
          const f = this._form;
          this._call({
            type: "ble_floorplan/set_tracker", key: tr.key, height: f.height ?? tr.height, ref_power: f.ref_power, pair_offsets: f.pairs,
          }, saved);
          return;
        }
        case "measure-tracker": {
          const tr = plan.trackers.find((x) => x.key === this._selTracker);
          this._measure = { tracker: tr.key, height: tr.height, x: null, y: null };
          this._go("calibration");
          return;
        }
        case "remove-scanner":
        case "remove-tracker": {
          const isScanner = act === "remove-scanner";
          const k = isScanner ? this._selScanner : this._selTracker;
          const item = (isScanner ? plan.scanners : plan.trackers).find((x) => x.key === k);
          if (!window.confirm(t.confirmRemove.replace("{name}", item?.name || k))) return;
          this._call({ type: `ble_floorplan/${act.replace("-", "_")}`, key: k }, () => {
            this._candidates = null;
            if (isScanner) this._selScanner = null;
            else this._selTracker = null;
            this._load();
          });
          return;
        }
        case "add-scanner":
          this._call({ type: "ble_floorplan/add_scanner", source: this._add.scanner, z: this._add.z ?? 1 }, (result) => {
            this._candidates = null;
            this._add = {};
            // A new scanner lands in the middle: straight on to its place
            this._selScanner = result.key;
            this._mode = "move";
            this._dragPos = {};
            this._load();
          });
          return;
        case "add-tracker": {
          const value = this._add.tracker;
          const c = (this._candidates?.trackers || []).find((x) => (x.device_id ? `device:${x.device_id}` : `address:${x.address}`) === value);
          const msg = { type: "ble_floorplan/add_tracker", name: (this._add.name || c?.name || "").trim() || value, height: this._add.height ?? 1 };
          if (value.startsWith("device:")) msg.device_id = value.slice(7);
          else msg.address = value.slice(8);
          this._call(msg, (result) => {
            this._candidates = null;
            this._add = {};
            this._selTracker = result.key;
            this._note = { kind: "ok", text: t.saved };
            this._load();
          });
          return;
        }
        case "cal-start": {
          const m = this._measure;
          this._call({ type: "ble_floorplan/calibration/start", tracker: m.tracker, x: m.x, y: m.y, height: m.height }, () => {
            this._measure = { ...m, x: null, y: null };
          });
          return;
        }
        case "cal-stop":
          this._call({ type: "ble_floorplan/calibration/stop" }, (result) => {
            this._note = this._fitNote(result.fit);
          });
          return;
        case "cal-delete":
          this._call({ type: "ble_floorplan/calibration/delete", run_id: key }, (result) => {
            if (result.fit) this._note = this._fitNote(result.fit);
          });
          return;
        case "cal-solve":
          this._call({ type: "ble_floorplan/calibration/solve", attenuation: this._cal.fitN }, (result) => {
            this._cal.proposal = result;
          });
          return;
        case "cal-apply": {
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
          return;
        }
        case "save-settings": {
          const settings = { ...(this._settings || plan.settings) };
          for (const [, k, , kind] of SETTING_FIELDS) if (kind !== "bool" && settings[k] == null) settings[k] = plan.settings[k];
          this._call({ type: "ble_floorplan/set_settings", settings }, () => {
            this._settings = null;
            this._note = { kind: "ok", text: t.saved };
          });
          return;
        }
        default:
          return;
      }
      this._render();
    }

    // ---- Timeline ----

    // What the map shows: the live positions, or where the trackers were at the moment of the timeline
    _shownPositions() {
      if (!this._tlOn || this._tl.cursor == null) return this._positions;
      const shown = {};
      for (const tr of this._plan.trackers) {
        const p = this._tlAt(tr.key, this._tl.cursor);
        if (p) shown[tr.key] = { ...p, readings: {}, scanner_count: 0 };
      }
      return shown;
    }

    // Index of the last point at or before t, -1 when there is none
    _tlIndex(pts, t) {
      let lo = 0;
      let hi = pts.length - 1;
      let found = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (pts[mid][0] <= t) {
          found = mid;
          lo = mid + 1;
        } else hi = mid - 1;
      }
      return found;
    }

    // Where the tracker was at the unix time t; null when not seen or not fetched
    _tlAt(key, t) {
      const pts = this._tl.days[utcDay(t)]?.tracks[key];
      if (!pts) return null;
      const i = this._tlIndex(pts, t);
      if (i < 0 || pts[i][1] == null) return null;
      const p = pts[i];
      const q = pts[i + 1];
      if (q && q[1] != null && q[0] - p[0] <= LERP_MAX && q[0] > p[0]) {
        const f = (t - p[0]) / (q[0] - p[0]);
        return { x: p[1] + (q[1] - p[1]) * f, y: p[2] + (q[2] - p[2]) * f, room: f < 0.5 ? p[3] : q[3] };
      }
      return { x: p[1], y: p[2], room: p[3] };
    }

    // The way of every tracker over the last TRAIL seconds before the moment shown
    _tlTrailsHtml() {
      if (!this._tlOn || this._tl.cursor == null) return "";
      const t1 = this._tl.cursor;
      const t0 = t1 - TRAIL;
      return this._plan.trackers
        .map((tr, i) => {
          const pts = this._tl.days[utcDay(t1)]?.tracks[tr.key] || [];
          const lines = [];
          let line = [];
          for (let j = Math.max(0, this._tlIndex(pts, t0)); j < pts.length && pts[j][0] <= t1; j++) {
            if (pts[j][1] == null) {
              if (line.length > 1) lines.push(line);
              line = [];
            } else line.push([pts[j][1], pts[j][2]]);
          }
          const now = this._tlAt(tr.key, t1);
          if (now && line.length) line.push([now.x, now.y]);
          if (line.length > 1) lines.push(line);
          const color = COLORS[i % COLORS.length];
          return lines.map((l) => `<polyline class="trail" stroke="${color}" points="${l.map((p) => p.join(",")).join(" ")}"/>`).join("");
        })
        .join("");
    }

    // The earliest moment the timeline reaches
    _tlFirst() {
      return nowS() - (this._plan?.settings?.history_days || 0) * 86400;
    }

    // A moment within the timeline; null (live) at or after now
    _tlClamp(t) {
      const now = nowS();
      if (t >= now - 0.5) return null;
      return Math.max(t, this._tlFirst());
    }

    _tlPause() {
      this._tl.playing = false;
      if (this._raf) cancelAnimationFrame(this._raf);
      this._raf = null;
    }

    _tlPlay() {
      if (this._tl.cursor == null) return;
      this._tl.playing = true;
      let last = performance.now();
      const step = (ts) => {
        if (!this._tl.playing) return;
        // A tab in the background gets few frames; a long pause still does not jump far
        const dt = Math.min((ts - last) / 1000, 1);
        last = ts;
        this._tl.cursor = this._tlClamp(this._tl.cursor + dt * this._tl.speed);
        if (this._tl.cursor == null) this._tl.playing = false;
        this._tlFrame();
        if (this._tl.playing) this._raf = requestAnimationFrame(step);
      };
      this._raf = requestAnimationFrame(step);
    }

    // Fetch the days the axis and the trail need, today again after a while
    _tlEnsure(tFrom, tTo) {
      const first = utcDay(this._tlFirst());
      const today = utcDay(nowS());
      for (let t = dayStart(utcDay(tFrom)); t <= tTo; t += 86400) {
        const d = utcDay(t);
        if (d < first || this._tl.loading.has(d)) continue;
        const have = this._tl.days[d];
        if (!have || (d === today && nowS() - have.fetched > REFETCH)) this._tlFetch(d);
      }
    }

    async _tlFetch(d) {
      this._tl.loading.add(d);
      try {
        const result = await this._hass.callWS({ type: "ble_floorplan/history", day: d });
        this._tl.days[d] = { tracks: result.tracks, fetched: nowS() };
      } catch (err) {
        this._tl.days[d] = { tracks: {}, fetched: nowS() };
      }
      this._tl.loading.delete(d);
      this._tlFrame();
    }

    _tlHtml() {
      const t = this._t;
      const v = Math.round((100 * Math.log(this._tl.spp / SPP_MAX)) / Math.log(SPP_MIN / SPP_MAX));
      const speeds = SPEEDS.map((s) => `<option value="${s}"${s === this._tl.speed ? " selected" : ""}>${s}×</option>`).join("");
      return `<div class="tl">
        <div class="tlhead">
          <div class="tldate" id="tldate"></div>
          <div class="tlrow"><button class="icon-button small" data-zoom="-10" title="${esc(t.zoomOut)}">−</button><input id="tlzoom" type="range" min="0" max="100" value="${v}"><button class="icon-button small" data-zoom="10" title="${esc(t.zoomIn)}">+</button></div>
          <div class="tlrow"><button class="icon-button small" id="tlplay"></button><select id="tlspeed" title="${esc(t.speed)}">${speeds}</select></div>
          <button id="tllive" class="btn small">${esc(t.backToLive)}</button>
        </div>
        <div class="tlaxis" id="tlaxis"></div>
      </div>`;
    }

    // Room for the longest clock label, so a 12-hour clock and seconds fit
    _tlLabelWidth() {
      const lang = this._hass?.language || "en";
      if (this._tlLw?.lang !== lang) {
        const ctx = document.createElement("canvas").getContext("2d");
        const sample = new Date(2026, 0, 1, 22, 58, 58).toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        let w = 45;
        if (ctx) {
          ctx.font = `11px ${getComputedStyle(this).fontFamily}`;
          w = Math.ceil(ctx.measureText(sample).width);
        }
        this._tlLw = { lang, w: Math.max(37, w + 4) };
      }
      return this._tlLw.w;
    }

    _tlLabel(ts, major) {
      const lang = this._hass?.language || "en";
      const d = new Date(ts * 1000);
      if (major >= 86400 || (d.getHours() === 0 && d.getMinutes() === 0 && d.getSeconds() === 0)) {
        return d.toLocaleDateString(lang, { day: "numeric", month: "numeric" });
      }
      return d.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit", ...(major < 60 ? { second: "2-digit" } : {}) });
    }

    // Seen stretches of a tracker between a and b, as [from, to]
    _tlSegments(key, a, b) {
      const segs = [];
      const now = nowS();
      for (let t = dayStart(utcDay(a)); t <= b; t += 86400) {
        const pts = this._tl.days[utcDay(t)]?.tracks[key];
        if (!pts) continue;
        let start = null;
        for (const p of pts) {
          if (p[1] != null && start == null) start = p[0];
          else if (p[1] == null && start != null) {
            segs.push([start, p[0]]);
            start = null;
          }
        }
        if (start != null) segs.push([start, Math.min(t + 86400, now)]);
      }
      return segs.filter(([s, e]) => e > a && s < b).map(([s, e]) => [Math.max(s, a), Math.min(e, b)]);
    }

    _tlAxisHtml(h, w, lw) {
      const tl = this._tl;
      const spp = tl.spp;
      const now = nowS();
      const T = tl.cursor ?? now;
      const y = (ts) => PLAYHEAD + (T - ts) / spp;
      const tTop = T + PLAYHEAD * spp;
      const tBot = T - (h - PLAYHEAD) * spp;
      this._tlEnsure(Math.min(tBot, T - TRAIL), Math.min(tTop, now));
      const html = [];
      if (now < tTop) html.push(`<div class="tlfuture" style="height:${y(now)}px"></div>`);
      const first = this._tlFirst();
      if (first > tBot) html.push(`<div class="tlfuture" style="top:${y(first)}px;bottom:0"></div>`);
      const major = TICKS.find((s) => s / spp >= 56) || 86400;
      const minor = [...TICKS].reverse().find((s) => s <= major / 4 && s / spp >= 8 && major % s === 0);
      const step = minor || major;
      // Ticks on the local clock, each with its own offset: a day may have 23 or 25 hours
      const off = (ts) => -new Date(ts * 1000).getTimezoneOffset() * 60;
      const align = (ts) => Math.floor((ts + off(ts)) / step) * step - off(ts);
      for (let ts = align(tBot); ts <= tTop; ts = Math.max(align(ts + step + 1), ts + 1)) {
        const isMajor = (ts + off(ts)) % major === 0;
        html.push(`<div class="tick${isMajor ? " major" : ""}" style="top:${y(ts)}px"></div>`);
        if (isMajor) html.push(`<div class="ticklabel" style="top:${y(ts)}px">${esc(this._tlLabel(ts, major))}</div>`);
      }
      const trackers = this._plan.trackers;
      const barW = Math.max(2, Math.min(6, (w - lw - 23) / Math.max(trackers.length, 1) - 3));
      trackers.forEach((tr, i) => {
        const left = lw + 21 + i * (barW + 3);
        for (const [a, b] of this._tlSegments(tr.key, tBot, Math.min(tTop, now))) {
          html.push(`<div class="tlbar" style="left:${left}px;width:${barW}px;top:${y(b)}px;height:${Math.max(1, (b - a) / spp)}px;background:${COLORS[i % COLORS.length]}"></div>`);
        }
      });
      const lang = this._hass?.language || "en";
      const badge = tl.cursor == null
        ? this._t.live
        : new Date(T * 1000).toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      html.push(`<div class="tlline" style="top:${PLAYHEAD}px"></div><div class="tlbadge${tl.cursor == null ? " live" : ""}" style="top:${PLAYHEAD}px">${esc(badge)}</div>`);
      return html.join("");
    }

    // Redraw what moves with the timeline: the axis, the moment, the trackers and their way
    _tlFrame() {
      const root = this.shadowRoot;
      if (!this._tlOn) return;
      const t = this._t;
      const tl = this._tl;
      const ax = root.getElementById("tlaxis");
      if (ax) {
        const lw = this._tlLabelWidth();
        ax.parentElement.style.setProperty("--tlx", `${lw}px`);
        ax.innerHTML = this._tlAxisHtml(ax.clientHeight || 400, ax.clientWidth || 104, lw);
      }
      const lang = this._hass?.language || "en";
      const date = root.getElementById("tldate");
      if (date) date.textContent = new Date((tl.cursor ?? nowS()) * 1000).toLocaleDateString(lang, { weekday: "short", day: "numeric", month: "short" });
      const play = root.getElementById("tlplay");
      if (play) {
        play.innerHTML = icon(tl.playing ? "pause" : "play");
        play.title = tl.playing ? t.pause : t.play;
        play.disabled = tl.cursor == null;
      }
      const live = root.getElementById("tllive");
      if (live) live.disabled = tl.cursor == null;
      if (tl.cursor == null && !tl.wasLive) {
        // Back at live: the next redraw shows the live positions
        tl.wasLive = true;
        this._update();
        return;
      }
      tl.wasLive = tl.cursor == null;
      if (tl.cursor == null) return;
      const shown = this._shownPositions();
      const dots = root.getElementById("dots");
      if (dots) {
        dots.innerHTML = this._plan.trackers
          .map((tr, i) => (shown[tr.key] ? dotHtml(tr, i, shown[tr.key], { rot: this._rot, labels: this._labels, open: false }) : ""))
          .join("");
      }
      const trails = root.getElementById("trails");
      if (trails) trails.innerHTML = this._tlTrailsHtml();
      // The next live redraw must not take the frame for unchanged
      this._svgHtml = null;
    }

    _tlBind(root) {
      const tl = this._tl;
      const ax = root.getElementById("tlaxis");
      if (!ax) return;
      ax.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        ax.setPointerCapture?.(e.pointerId);
        this._tlPause();
        this._dragging = true;
        const y0 = e.clientY;
        const c0 = tl.cursor ?? nowS();
        let moved = false;
        const move = (ev) => {
          const dy = ev.clientY - y0;
          if (Math.abs(dy) > 3) moved = true;
          if (!moved) return;
          tl.cursor = this._tlClamp(c0 + dy * tl.spp);
          this._tlFrame();
        };
        const up = (ev) => {
          ax.removeEventListener("pointermove", move);
          ax.removeEventListener("pointerup", up);
          ax.removeEventListener("pointercancel", up);
          this._dragging = false;
          if (!moved) {
            // A tap jumps to the moment under it
            const r = ax.getBoundingClientRect();
            tl.cursor = this._tlClamp(c0 + (PLAYHEAD - (ev.clientY - r.top)) * tl.spp);
          }
          this._svgHtml = null;
          this._update();
        };
        ax.addEventListener("pointermove", move);
        ax.addEventListener("pointerup", up);
        ax.addEventListener("pointercancel", up);
      });
      ax.addEventListener("wheel", (e) => {
        e.preventDefault();
        if (e.ctrlKey) this._tlZoom(tl.spp * Math.exp(e.deltaY / 100));
        else tl.cursor = this._tlClamp((tl.cursor ?? nowS()) - e.deltaY * tl.spp);
        this._tlFrame();
      }, { passive: false });
      const zoom = root.getElementById("tlzoom");
      zoom?.addEventListener("input", () => {
        this._tlZoom(SPP_MAX * Math.pow(SPP_MIN / SPP_MAX, zoom.value / 100), false);
        this._tlFrame();
      });
      root.querySelectorAll("button[data-zoom]").forEach((b) => b.addEventListener("click", () => {
        const v = Math.min(100, Math.max(0, Number(zoom.value) + Number(b.dataset.zoom)));
        zoom.value = v;
        this._tlZoom(SPP_MAX * Math.pow(SPP_MIN / SPP_MAX, v / 100), false);
        this._tlFrame();
      }));
      root.getElementById("tlplay")?.addEventListener("click", () => {
        if (tl.playing) this._tlPause();
        else this._tlPlay();
        this._tlFrame();
      });
      root.getElementById("tlspeed")?.addEventListener("change", (e) => {
        tl.speed = Number(e.target.value);
        e.target.blur();
      });
      root.getElementById("tllive")?.addEventListener("click", () => {
        this._tlPause();
        tl.cursor = null;
        this._svgHtml = null;
        this._update();
      });
    }

    _tlZoom(spp, syncSlider = true) {
      this._tl.spp = Math.min(SPP_MAX, Math.max(SPP_MIN, spp));
      const zoom = syncSlider && this.shadowRoot.getElementById("tlzoom");
      if (zoom) zoom.value = Math.round((100 * Math.log(this._tl.spp / SPP_MAX)) / Math.log(SPP_MIN / SPP_MAX));
    }
  }

  // Home Assistant's look: toolbar and tabs of the settings pages, cards, list
  // items, filled text fields, switches; the colours of the active theme
  const STYLE = `
    /* The panel's own container has no height of its own: the page takes the window */
    :host { display: block; height: 100vh; height: 100dvh; background: var(--primary-background-color); color: var(--primary-text-color);
      font-family: var(--ha-font-family-body, Roboto, Noto, sans-serif); font-size: 14px; line-height: 1.5;
      -webkit-font-smoothing: antialiased; }
    * { box-sizing: border-box; }
    .app { display: flex; flex-direction: column; height: 100%; }
    .toolbar { display: flex; align-items: center; flex: none; height: var(--header-height, 56px); padding: 0 12px;
      background: var(--sidebar-background-color); color: var(--sidebar-text-color, var(--primary-text-color));
      border-bottom: 1px solid var(--divider-color); }
    .menu-button { color: var(--sidebar-icon-color, var(--secondary-text-color)); margin-right: 12px; }
    .main-title { font-size: 20px; font-weight: 400; line-height: 32px; margin-left: 12px; white-space: nowrap; }
    .menu-button + .main-title { margin-left: 0; }
    .tabs { display: flex; height: 100%; margin-left: 24px; overflow-x: auto; scrollbar-width: none; }
    .tab { display: flex; align-items: center; justify-content: center; height: 100%; padding: 0 20px; position: relative;
      color: var(--sidebar-text-color, var(--primary-text-color)); text-decoration: none; font-weight: 500; white-space: nowrap; opacity: 0.8; }
    .tab:hover { background: color-mix(in srgb, var(--primary-text-color) 5%, transparent); }
    .tab.active { color: var(--primary-color); opacity: 1; }
    .tabs .tab.active::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 2px; background: var(--primary-color); }
    .bottom-tabs { display: flex; flex: none; justify-content: space-around; background: var(--sidebar-background-color);
      border-top: 1px solid var(--divider-color); padding-bottom: env(safe-area-inset-bottom); }
    .bottom-tabs .tab { flex: 1 1 0; flex-direction: column; gap: 2px; height: 56px; padding: 6px 2px 4px; font-size: 11px; min-width: 0; }
    .bottom-tabs .tab span { overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
    .bottom-tabs .tab .mdi { padding: 2px 12px; border-radius: 14px; box-sizing: content-box; }
    .bottom-tabs .tab.active .mdi { background: color-mix(in srgb, var(--primary-color) 15%, transparent); }
    .content { flex: 1 1 auto; min-height: 0; display: flex; }
    .stage { flex: 1 1 auto; min-width: 0; display: flex; gap: 12px; padding: 16px; }
    .map { flex: 1 1 auto; height: 100%; display: flex; flex-direction: column; padding: 4px 8px 12px; background: var(--card-background-color);
      border-radius: var(--ha-card-border-radius, 12px); border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color)); }
    #svg { flex: 1 1 auto; min-height: 0; }
    .maptools { display: flex; justify-content: flex-end; flex: none; }
    .menuwrap { position: relative; }
    .sheet { flex: 0 0 min(420px, 45%); overflow-y: auto; padding: 16px 16px 16px 0; }
    .content:not(.withmap) .sheet { flex: 1 1 auto; padding: 16px; }
    .content.settings .sheet > *, .content:not(.withmap) .sheet > * { max-width: 720px; margin-left: auto; margin-right: auto; }
    .narrow .content { display: block; overflow-y: auto; }
    .narrow .stage { padding: 8px 8px 0; }
    .narrow .map { height: auto; }
    .narrow .map svg:not(.mdi) { height: auto; max-height: 62vh; }
    .narrow .content.nosheet .stage { height: 100%; }
    .narrow .content.nosheet .map { height: 100%; }
    .narrow .content.nosheet .map svg:not(.mdi) { height: 100%; max-height: none; }
    .narrow .sheet { padding: 8px; overflow: visible; }
    .card { background: var(--card-background-color); color: var(--primary-text-color);
      border-radius: var(--ha-card-border-radius, 12px); border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
      box-shadow: var(--ha-card-box-shadow, none); margin-bottom: 16px; overflow: hidden; }
    .narrow .card { margin-bottom: 8px; }
    .card h2 { margin: 0; padding: 20px 16px 8px; font-size: 20px; font-weight: 400; line-height: 28px; }
    .card-head { display: flex; align-items: center; gap: 4px; padding: 12px 16px 4px 8px; font-size: 20px; line-height: 28px; }
    .card-head .dot { margin-left: 8px; }
    .card-content { padding: 0 16px 16px; }
    .card.list .card-content { padding: 0 0 8px; }
    .card-actions { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 8px;
      border-top: 1px solid var(--divider-color); }
    .card-actions > span { display: flex; gap: 8px; }
    .btn { display: inline-flex; align-items: center; justify-content: center; height: 36px; padding: 0 16px; border: 0;
      border-radius: 18px; background: none; color: var(--primary-color); font: inherit; font-weight: 500; cursor: pointer; white-space: nowrap; }
    .btn:hover { background: color-mix(in srgb, var(--primary-color) 10%, transparent); }
    .btn.filled { background: var(--primary-color); color: var(--text-primary-color, #fff); }
    .btn.filled:hover { background: color-mix(in srgb, var(--primary-color) 88%, #000); }
    .btn.danger { color: var(--error-color); }
    .btn.danger:hover { background: color-mix(in srgb, var(--error-color) 10%, transparent); }
    .btn.small { height: 28px; padding: 0 8px; font-size: 12px; }
    .btn:disabled, .icon-button:disabled { opacity: 0.4; cursor: default; background: none; }
    .btn.filled:disabled { background: var(--disabled-color, #bdbdbd); color: var(--card-background-color); }
    .icon-button.small { width: 32px; height: 32px; }
    .icon-button.small .mdi { width: 20px; height: 20px; }
    .item { display: flex; align-items: center; gap: 16px; width: 100%; min-height: 64px; padding: 8px 16px; border: 0;
      background: none; color: var(--primary-text-color); font: inherit; text-align: left; cursor: pointer; }
    .item:hover { background: color-mix(in srgb, var(--primary-text-color) 5%, transparent); }
    .icon-bg { display: flex; padding: 8px; border-radius: 50%; color: #fff; background: var(--primary-color); flex: none; }
    .icon-bg .mdi { width: 20px; height: 20px; }
    .text { display: flex; flex: 1; flex-direction: column; min-width: 0; }
    .headline { line-height: 20px; }
    .supporting { font-size: 12px; line-height: 16px; color: var(--secondary-text-color); margin-top: 2px; }
    .next { color: var(--secondary-text-color); }
    .muted { color: var(--secondary-text-color); }
    .small { font-size: 12px; line-height: 16px; margin-top: 8px; }
    .status { color: var(--secondary-text-color); margin-bottom: 8px; }
    .subhead { margin: 16px 0 4px; font-weight: 500; }
    .alert { display: block; padding: 12px 16px; margin-bottom: 16px; border-radius: 8px; line-height: 20px;
      background: color-mix(in srgb, var(--info-color, #039be5) 12%, transparent); }
    .card .alert { margin: 8px 0; }
    .alert.ok { background: color-mix(in srgb, var(--success-color, #43a047) 14%, transparent); }
    .alert.err { background: color-mix(in srgb, var(--error-color, #db4437) 14%, transparent); }
    table { border-collapse: collapse; width: 100%; }
    table.kv th { width: 40%; text-align: left; font-weight: 400; color: var(--secondary-text-color); padding: 8px 16px 8px 0; vertical-align: top; }
    table.kv td { padding: 8px 0; }
    table.kv tr + tr th, table.kv tr + tr td { border-top: 1px solid var(--divider-color); }
    table.data th { text-align: left; font-size: 12px; font-weight: 500; padding: 8px 12px 8px 0; white-space: nowrap; }
    table.data td { padding: 6px 12px 6px 0; border-top: 1px solid var(--divider-color); }
    table.data td:last-child, table.data th:last-child { padding-right: 0; }
    .n { text-align: right !important; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .nowrap { white-space: nowrap; }
    tr.ign td { color: var(--secondary-text-color); }
    tr.live td { color: var(--primary-color); }
    .runs th { max-width: 6em; overflow: hidden; text-overflow: ellipsis; }
    .runs td { vertical-align: middle; }
    .diff tr.sec td { color: var(--secondary-text-color); font-size: 12px; padding-top: 12px; border: 0; }
    .diff tr.changed td:nth-child(3) { font-weight: 600; color: var(--primary-color); }
    .scroll { overflow-x: auto; }
    td .dot, .nowrap .dot { vertical-align: -1px; }
    .fields { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 150px), 1fr)); gap: 12px; margin-top: 12px; }
    .field { display: flex; flex-direction: column; min-width: 0; padding: 6px 12px 4px; border-radius: 4px 4px 0 0;
      background: var(--input-fill-color, color-mix(in srgb, var(--primary-text-color) 5%, transparent));
      border-bottom: 1px solid var(--input-idle-line-color, var(--secondary-text-color)); }
    .field.wide { margin-top: 8px; }
    .field:hover { border-bottom-color: var(--input-hover-line-color, var(--primary-text-color)); }
    .field:focus-within { border-bottom: 2px solid var(--primary-color); padding-bottom: 3px; }
    .field > span { font-size: 12px; line-height: 16px; color: var(--input-label-ink-color, var(--secondary-text-color));
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .field:focus-within > span { color: var(--primary-color); }
    .field input, .field select { border: 0; outline: 0; background: none; padding: 2px 0; width: 100%; min-width: 0;
      color: var(--input-ink-color, var(--primary-text-color)); font: inherit; font-size: 16px; }
    .field select option { background: var(--card-background-color); color: var(--primary-text-color); }
    textarea { width: 100%; min-height: 240px; padding: 12px; border: 0; border-radius: 4px 4px 0 0; resize: vertical; outline: 0;
      background: var(--code-editor-background-color, var(--secondary-background-color)); color: var(--primary-text-color);
      border-bottom: 1px solid var(--input-idle-line-color, var(--secondary-text-color));
      font-family: var(--ha-font-family-code, var(--code-font-family, monospace)); font-size: 13px; line-height: 1.5; white-space: pre; }
    textarea:focus { border-bottom: 2px solid var(--primary-color); }
    .setting { display: flex; align-items: center; gap: 16px; min-height: 56px; padding: 4px 0; cursor: pointer; }
    .setting + .setting { border-top: 1px solid var(--divider-color); }
    .setting .text { flex: 1 1 auto; }
    .setting input.num { flex: 0 0 96px; width: 96px; padding: 6px 8px; text-align: right; border: 0; outline: 0; border-radius: 4px 4px 0 0;
      background: var(--input-fill-color, color-mix(in srgb, var(--primary-text-color) 5%, transparent)); color: var(--primary-text-color);
      border-bottom: 1px solid var(--input-idle-line-color, var(--secondary-text-color)); font: inherit; font-size: 16px; }
    .setting input.num:focus { border-bottom: 2px solid var(--primary-color); }
    input.switch { appearance: none; -webkit-appearance: none; position: relative; flex: none; width: 36px; height: 14px; margin: 0 4px;
      border-radius: 7px; cursor: pointer; background: var(--switch-unchecked-track-color, #9e9e9e); opacity: 1; }
    input.switch::before { content: ""; position: absolute; top: -3px; left: -4px; width: 20px; height: 20px; border-radius: 50%;
      background: var(--switch-unchecked-button-color, #fafafa); box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4); transition: transform 0.15s; }
    input.switch:checked { background: color-mix(in srgb, var(--switch-checked-track-color, var(--primary-color)) 50%, transparent); }
    input.switch:checked::before { transform: translateX(20px); background: var(--switch-checked-button-color, var(--primary-color)); }
    .tl { flex: 0 0 calc(75px + var(--tlx, 37px)); display: flex; flex-direction: column; font-size: 12px; overflow: hidden; user-select: none; -webkit-user-select: none;
      background: var(--card-background-color); border-radius: var(--ha-card-border-radius, 12px);
      border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color)); }
    .tlhead { padding: 8px 6px 6px; display: flex; flex-direction: column; gap: 4px; border-bottom: 1px solid var(--divider-color); }
    .tldate { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 0 2px; }
    .tlrow { display: flex; gap: 2px; align-items: center; }
    .tlrow .icon-button { flex: none; font-size: 18px; color: var(--primary-text-color); }
    .tlrow input[type=range] { flex: 1 1 auto; min-width: 0; width: 30px; margin: 0; accent-color: var(--primary-color); }
    .tlrow select { font: inherit; flex: 1 1 auto; min-width: 0; padding: 2px; border-radius: 4px; border: 0;
      background: var(--input-fill-color, color-mix(in srgb, var(--primary-text-color) 5%, transparent)); color: var(--primary-text-color); }
    .tlaxis { position: relative; flex: 1 1 auto; overflow: hidden; cursor: grab; touch-action: none; }
    .tlaxis:active { cursor: grabbing; }
    .tlfuture { position: absolute; left: 0; right: 0; top: 0; background: var(--secondary-background-color); opacity: 0.6; }
    .tick { position: absolute; left: calc(var(--tlx, 37px) + 7px); width: 6px; height: 1px; background: var(--divider-color); }
    .tick.major { left: calc(var(--tlx, 37px) + 3px); width: 12px; background: var(--secondary-text-color); }
    .ticklabel { position: absolute; right: calc(100% - var(--tlx, 37px)); transform: translateY(-50%); color: var(--secondary-text-color);
      font-size: 11px; white-space: nowrap; font-variant-numeric: tabular-nums; }
    .tlbar { position: absolute; border-radius: 3px; opacity: 0.85; }
    .tlline { position: absolute; left: 0; right: 0; height: 2px; margin-top: -1px; background: var(--primary-color); pointer-events: none; }
    .tlbadge { position: absolute; left: 4px; transform: translateY(-50%); background: var(--primary-color); color: var(--text-primary-color, #fff);
      border-radius: 6px; padding: 1px 6px; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; pointer-events: none; }
    .narrow .tl { flex-basis: calc(59px + var(--tlx, 37px)); }
  `;

  customElements.define("ble-floorplan-panel", BleFloorplanPanel);
  console.info(`ble-floorplan-panel ${VERSION}`);
}
