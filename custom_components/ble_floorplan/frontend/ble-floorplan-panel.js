// BLE Floorplan panel: the page in the sidebar where administrators set up the
// floor plan, place the scanners, add the trackers, calibrate, look back on
// the timeline and change the settings. The floor plan is on every page but
// the settings: the scanners are placed on it, the true position of a
// calibration run is tapped on it. Everything comes from the integration over
// the WebSocket API. The page is built from Home Assistant's own elements (top
// app bar, cards, buttons, icon buttons, alerts and ha-form with selectors);
// a scanner or a tracker opens as a subpage with a back arrow. The header is
// one row: the integration's icon, its name and the tabs; at its end on
// every page: when the page last got its data, refresh, and the cog to Home
// Assistant's page of the integration.
import {
  COLORS,
  LiveSubscription,
  MDI,
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
  formatter,
  icon,
  iconButton,
  keep,
  loadLabels,
  loadRot,
  navigate,
  planInfo,
  planSvg,
  snap,
  texts,
  toPlan,
  trackerColor,
} from "./ble-floorplan-plan.js?v=0.17.1";

if (!customElements.get("ble-floorplan-panel")) {
  const ROT_KEY = "ble-floorplan-panel-rot";
  // Home Assistant's own page of the integration, behind the cog in the header
  const INTEGRATION_PATH = "/config/integrations/integration/ble_floorplan";
  const LABELS_KEY = "ble-floorplan-panel-labels";

  // Tab, icon, text
  const TABS = [
    ["plan", "plan", "tabPlan"],
    ["scanners", "scanner", "tabScanners"],
    ["trackers", "tracker", "tabTrackers"],
    ["calibration", "calibration", "tabCalibration"],
    ["coverage", "coverage", "tabCoverage"],
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
  // Probe scanners a page may place at once, as the integration takes them
  const MAX_PROBES = 5;
  // Every tracker (measured) or the default values (model): no key of a tracker
  const ANY = "*";
  // The measurement is fetched again this often while it is shown (ms)
  const MEASURED_REFETCH_MS = 60000;
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
      // The coverage: the map shown, for which tracker, the probe scanners, the
      // result and what it was fetched for; `stamp` asks for a fresh measurement
      this._cov = { mode: "model", tracker: ANY, probes: [], data: null, key: null, loading: false, stamp: 0, confirm: false };
      this._note = null;
      this._busy = false;
      this._frameKey = null;
      // The timeline: the moment shown (null = live), zoom, playback, the days fetched
      this._tl = { cursor: null, spp: SPP_START, playing: false, speed: 60, days: {}, loading: new Set(), wasLive: true };
      // The forms on the sheet: id -> {schema, data, onChange}, drawn as ha-form
      this._forms = {};
      // A removal waiting for its confirmation: {act, key, name}
      this._confirm = null;
      // Shown at the bottom: {version, commit}
      this._about = null;
      // The header: when the page last got its data, a refresh on the way
      this._stamp = null;
      this._refreshing = false;
      this._live = new LiveSubscription(
        this,
        (event) => this._onEvent(event),
        (err) => {
          this._error = !err ? null : err.code === "not_loaded" ? this._t.notLoaded : String(err.message || err);
          this._render();
        }
      );
      this._bindOnce();
    }

    set hass(hass) {
      const first = !this._hass;
      this._hass = hass;
      this._live.ensure(hass);
      if (first) {
        this._load();
        this._render();
        this._loadBrand();
      }
      // The menu button follows the sidebar itself; the forms need the new hass
      for (const el of this.shadowRoot.querySelectorAll("ha-menu-button, ha-form")) el.hass = hass;
    }

    // The integration's icon from its brand folder, as Home Assistant serves it to
    // the frontend: an image link needs the brands access token
    async _loadBrand() {
      try {
        const { token } = await this._hass.callWS({ type: "brands/access_token" });
        this._brandSrc = `/api/brands/integration/ble_floorplan/icon.png?token=${encodeURIComponent(token)}`;
        const img = this.shadowRoot.getElementById("brand");
        if (img) img.src = this._brandSrc;
      } catch {
        // Without the icon the name still says which page this is
      }
    }

    set narrow(narrow) {
      this._narrow = narrow;
      const menu = this.shadowRoot.querySelector("ha-menu-button");
      if (menu) menu.narrow = narrow;
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
      this._live.ensure(this._hass);
      // The measurement on the coverage page is fetched again even while no tracker moves
      this._covTimer = window.setInterval(() => {
        if (this._tab === "coverage" && this._cov.mode === "measured") this._render();
      }, MEASURED_REFETCH_MS / 4);
      this._render();
    }

    disconnectedCallback() {
      this._live.close();
      this._tlPause();
      window.clearInterval(this._covTimer);
    }

    get _t() {
      return texts(this._hass);
    }

    get _fmt() {
      return formatter(this._hass);
    }

    _onEvent(event) {
      this._stamp = new Date();
      if (event.floorplan) {
        this._plan = event.floorplan;
        this._bounds = computeBounds(this._plan);
      }
      if (event.positions) this._positions = event.positions;
      if (event.calibration) this._calibration = event.calibration;
      if (event.about) this._about = event.about;
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
        this._confirm = null;
        this._cov.confirm = false;
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

    // The refresh button: everything the page shows fetched again over the
    // WebSocket API, no reload of the page. A floor plan typed but not saved stays.
    async _refresh() {
      if (!this._hass || this._refreshing) return;
      this._refreshing = true;
      this._render();
      try {
        const jobs = [this._hass.callWS({ type: "ble_floorplan/get_floorplan" }).then((snap) => this._onEvent(snap))];
        if (!this._layoutEdited) {
          jobs.push(this._hass.callWS({ type: "ble_floorplan/get_layout" }).then((r) => { this._layout = r.yaml; }));
        }
        if (this._candidates != null || this._tab === "scanners" || this._tab === "trackers") {
          jobs.push(this._hass.callWS({ type: "ble_floorplan/candidates" }).then((r) => { this._candidates = r; }));
        }
        // The timeline fetches the days it shows again, the coverage its map
        this._tl.days = {};
        this._cov.stamp += 1;
        await Promise.all(jobs);
        this._error = null;
      } catch (err) {
        this._note = { kind: "err", text: err?.code === "not_loaded" ? this._t.notLoaded : String(err?.message || err?.code || err) };
      }
      // A subscription that failed tries again now
      this._live.ensure(this._hass);
      this._refreshing = false;
      this._render();
    }

    _stampText() {
      if (!this._stamp) return "";
      const time = this._stamp.toLocaleTimeString(this._hass?.language || "en", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
      return this._t.asOf.replace("{time}", time);
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

    // A redraw while a field has the focus would lose the input; a choice in a
    // drop-down that changes other fields asks for the redraw itself
    _typing() {
      if (this._redraw) return false;
      const el = this.shadowRoot.activeElement;
      return !!el && (el.tagName === "TEXTAREA" || el.tagName === "HA-FORM");
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
      if (this._tab === "coverage") this._covLoad();
      const showMap = this._tab !== "settings" && !!plan?.rooms.length;
      const showSheet = !this._tlOn;
      const sub = this._subpage;
      const key = [this._tab, !!this._narrow, !!plan, showMap, showSheet, this._tlOn, this._hass.language, sub?.key, sub?.name].join("|");
      if (key !== this._frameKey) {
        this._frameKey = key;
        this._frame(plan, showMap, showSheet, sub);
      }
      this._update();
    }

    // A scanner or a tracker opened: a subpage with a back arrow and its name
    get _subpage() {
      const plan = this._plan;
      if (!plan) return null;
      if (this._tab === "scanners" && this._selScanner) return plan.scanners.find((x) => x.key === this._selScanner) || null;
      if (this._tab === "trackers" && this._selTracker) return plan.trackers.find((x) => x.key === this._selTracker) || null;
      return null;
    }

    // The parts that stay while the page is open: top app bar, tabs, map, timeline, sheet
    _frame(plan, showMap, showSheet, sub) {
      const t = this._t;
      const tabs = TABS.map(([id, ic, label]) =>
        `<a class="tab${this._tab === id ? " active" : ""}" data-tab="${id}" href="${PANEL_PATH}/${id}">` +
        `${this._narrow ? icon(ic) : ""}<span>${esc(t[label])}</span></a>`).join("");
      const nav = sub
        ? iconButton("back", t.back, 'slot="navigationIcon" data-act="back"')
        : `<ha-menu-button slot="navigationIcon"></ha-menu-button>`;
      const stage = showMap
        ? `<div class="stage"><div class="map" id="map"><div class="maptools" id="maptools"></div><div id="svg"></div>` +
          `<div class="tip"></div></div>${this._tlOn ? this._tlHtml() : ""}</div>`
        : "";
      const sheet = showSheet ? `<div class="sheet" id="sheet"></div>` : `<div class="about" id="about"></div>`;
      // One header row: the integration's icon, its name and the tabs right after it;
      // a subpage has the back arrow and the name of what it shows instead
      const topTabs = !this._narrow && !sub;
      const brand = sub ? "" : `<img class="brand" id="brand" alt="" width="24" height="24"${this._brandSrc ? ` src="${esc(this._brandSrc)}"` : ""}>`;
      this.shadowRoot.innerHTML = `
        <style>${PLAN_CSS}${STYLE}</style>
        <ha-top-app-bar-fixed>
          ${nav}
          <div slot="title" class="head">${brand}<span class="name">${esc(sub ? sub.name : "BLE Floorplan")}</span>${topTabs ? `<nav class="tabs">${tabs}</nav>` : ""}</div>
          <span class="stamp" slot="actionItems" id="stamp"></span>
          ${iconButton("refresh", t.refresh, 'slot="actionItems" id="refresh" data-act="refresh"')}
          ${iconButton("cog", t.integrationSettings, 'slot="actionItems" id="integration" data-act="integration"')}
          <div class="app${this._narrow ? " narrow" : ""}">
            <div class="content ${this._tab}${showMap ? " withmap" : ""}${showSheet ? "" : " nosheet"}">${stage}${sheet}</div>
            ${this._narrow && !sub ? `<nav class="bottom-tabs">${tabs}</nav>` : ""}
          </div>
        </ha-top-app-bar-fixed>`;
      const menu = this.shadowRoot.querySelector("ha-menu-button");
      if (menu) {
        menu.hass = this._hass;
        menu.narrow = this._narrow;
      }
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
        this._forms = {};
        const html = this._sheet();
        if (html !== this._sheetHtml) {
          this._sheetHtml = html;
          sheet.innerHTML = html;
          this._hydrate(sheet);
        }
        this._redraw = false;
      }
      const about = root.getElementById("about");
      if (about) about.textContent = this._aboutText();
      const stamp = root.getElementById("stamp");
      if (stamp) stamp.textContent = this._stampText();
      root.getElementById("refresh")?.classList.toggle("loading", this._refreshing);
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
      if (this._tab === "coverage") return this._cov.mode === "model" && this._cov.probes.length < MAX_PROBES;
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
      if (tab === "coverage") marks = this._covMarks();
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
      return iconButton("rotate", t.rotate, 'data-act="rotate"') +
        `<span class="menuwrap">${iconButton("label", t.labels, `data-act="labels"${this._labelMenu ? ' class="on"' : ""}`)}${menu}</span>`;
    }

    // ---- Building blocks, as Home Assistant draws them ----

    _card(title, body, actions = "", cls = "") {
      return `<ha-card${title ? ` header="${esc(title)}"` : ""} class="${cls}"><div class="card-content${title ? "" : " top"}">${body}</div>` +
        `${actions ? `<div class="card-actions">${actions}</div>` : ""}</ha-card>`;
    }

    // kind: "" (plain), "filled" (the main action), "danger"
    _btn(act, label, { kind = "", disabled = false, data = "" } = {}) {
      const look = kind === "filled" ? "" : kind === "danger" ? ' appearance="plain" variant="danger"' : ' appearance="plain"';
      return `<ha-button${look} data-act="${act}"${data}${disabled || this._busy ? " disabled" : ""}>${esc(label)}</ha-button>`;
    }

    // A field in metres, dB, seconds: a number selector of Home Assistant
    _num(name, label, unit, extra = {}) {
      return { name, label, selector: { number: { mode: "box", step: "any", ...(unit ? { unit_of_measurement: unit } : {}), ...extra } } };
    }

    // The name of a scanner or a tracker; the integration takes up to 80 characters
    _nameField(label) {
      return { name: "name", label, required: true, selector: { text: {} } };
    }

    // An ha-form with Home Assistant's selectors; drawn after the sheet's HTML.
    // The data is part of the placeholder, so a change from outside redraws it
    _formSlot(id, schema, data, onChange) {
      const clean = Object.fromEntries(Object.entries(data).filter(([, v]) => v !== null && v !== undefined));
      this._forms[id] = { schema, data: clean, onChange };
      return `<div class="haform" data-form="${esc(id)}" data-v="${esc(JSON.stringify(clean))}"></div>`;
    }

    _hydrate(root) {
      for (const slot of root.querySelectorAll("[data-form]")) {
        const spec = this._forms[slot.dataset.form];
        if (!spec) continue;
        const form = document.createElement("ha-form");
        form.hass = this._hass;
        form.schema = spec.schema;
        form.data = spec.data;
        form.computeLabel = (s) => s.label ?? s.name;
        form.computeHelper = (s) => s.helper;
        form.addEventListener("value-changed", (e) => {
          form.data = e.detail.value;
          spec.onChange(e.detail.value);
        });
        slot.append(form);
      }
    }

    _kv(rows) {
      return `<table class="kv">${rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${v}</td></tr>`).join("")}</table>`;
    }

    _alert(kind, text) {
      return `<ha-alert alert-type="${kind}">${esc(text)}</ha-alert>`;
    }

    _noteHtml() {
      if (!this._note) return "";
      return this._alert(this._note.kind === "ok" ? "success" : this._note.kind === "err" ? "error" : "info", this._note.text);
    }

    // Removing asks first, in the card, as Home Assistant's own pages do
    _confirmHtml() {
      const c = this._confirm;
      if (!c) return "";
      return `<ha-alert alert-type="warning">${esc(this._t.confirmRemove.replace("{name}", c.name))}` +
        `<ha-button slot="action" appearance="plain" data-act="confirm-cancel">${esc(this._t.cancel)}</ha-button>` +
        `<ha-button slot="action" variant="danger" data-act="confirm-ok">${esc(this._t.remove)}</ha-button></ha-alert>`;
    }

    // The version, from the integration's manifest, and the commit of a test deployment
    _aboutText() {
      const a = this._about;
      if (!a?.version) return "";
      return (a.commit ? this._t.aboutCommit : this._t.about).replace("{version}", a.version).replace("{commit}", a.commit || "");
    }

    // ---- The sheet of each page ----

    _sheet() {
      const t = this._t;
      if (!this._plan) {
        return (this._error ? this._alert("error", this._error) : this._card("", `<div class="muted">…</div>`)) +
          `<div class="about">${esc(this._aboutText())}</div>`;
      }
      const page = {
        plan: () => this._planSheet(),
        scanners: () => this._scannersSheet(),
        trackers: () => this._trackersSheet(),
        calibration: () => this._calibrationSheet(),
        coverage: () => this._coverageSheet(),
        timeline: () => this._card(t.timeline, `<div class="muted">${esc(t.timelineOff)}</div>`,
          `<span></span>${this._btn("go-settings", t.tabSettings)}`),
        settings: () => this._settingsSheet(),
      }[this._tab];
      const empty = !this._plan.rooms.length && this._tab !== "plan" && this._tab !== "settings"
        ? this._alert("info", t.startHere)
        : "";
      return this._noteHtml() + empty + page() + `<div class="about">${esc(this._aboutText())}</div>`;
    }

    _planSheet() {
      const t = this._t;
      const empty = this._plan.rooms.length ? "" : this._alert("info", t.startHere);
      const body = `<textarea data-f="layout" rows="22" spellcheck="false" wrap="off">${esc(this._layout ?? "…")}</textarea>` +
        `<div class="muted small">${esc(t.layoutHint)}</div>`;
      return empty + this._card(t.plan, body, `<span></span>${this._btn("save-layout", t.save, { kind: "filled", disabled: this._layout == null })}`);
    }

    _item(act, key, lead, headline, supporting, active) {
      return `<div class="item${active ? " active" : ""}" role="button" tabindex="0" data-act="${act}" data-key="${esc(key)}">${lead}` +
        `<span class="text"><span class="headline">${esc(headline)}</span><span class="supporting">${supporting}</span></span>` +
        `<span class="next">${icon("chevron")}</span></div>`;
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
      const pick = { name: "item", label: t.add, required: true, selector: { select: { mode: "dropdown", options: options.map(([v, l]) => ({ value: v, label: l })) } } };
      let schema;
      let data;
      if (kind === "scanner") {
        schema = [pick, this._num("z", t.height, "m")];
        data = { item: chosen, z: this._add.z ?? 1 };
      } else {
        const c = items.find((x) => value(x) === chosen);
        schema = [pick, { name: "name", label: t.name, selector: { text: {} } }, this._num("height", t.height, "m")];
        data = { item: chosen, name: this._add.name ?? c?.name ?? "", height: this._add.height ?? 1 };
      }
      const body = this._formSlot(`add-${kind}`, schema, data, (v) => {
        if (v.item !== this._add[kind]) {
          // Another choice: the name follows it
          this._add[kind] = v.item;
          if (kind === "tracker") this._add.name = null;
          this._redraw = true;
          this._render();
          return;
        }
        if (kind === "scanner") this._add.z = v.z ?? null;
        else {
          this._add.name = v.name ?? "";
          this._add.height = v.height ?? null;
        }
      });
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
      const hears = `<table class="data"><tr><th>${esc(t.tracker)}</th><th class="n">m</th><th class="n">dBm</th></tr>` +
        info.trackers.map((e) => `<tr class="${e.d == null || !e.used ? "ign" : ""}"><td><span class="dot" style="background:${e.color}"></span>${esc(e.name)}</td>` +
          `<td class="n">${e.d == null ? esc(t.notSeen) : fmt(e.d)}</td><td class="n">${e.rssi == null ? "" : fmt(e.rssi, 0)}</td></tr>`).join("") +
        `</table>`;
      let body;
      let actions;
      if (this._form) {
        const f = this._form;
        body = this._formSlot("scanner", [
          this._nameField(t.name),
          { type: "grid", name: "", schema: [this._num("x", "x", "m"), this._num("y", "y", "m"), this._num("z", t.height, "m"), this._num("rssi_offset", t.offset, "dB")] },
        ], f, (v) => {
          for (const k of ["name", "x", "y", "z", "rssi_offset"]) f[k] = v[k] ?? null;
        }) +
          `<div class="subhead">${esc(t.pairs)}</div>` +
          this._formSlot("scanner-pairs", [
            { type: "grid", name: "", schema: plan.trackers.map((tr) => this._num(tr.key, tr.name, "dB")) },
          ], f.pairs, (v) => {
            for (const tr of plan.trackers) f.pairs[tr.key] = v[tr.key] ?? null;
          });
        actions = `<span></span><span>${this._btn("cancel", t.cancel)}${this._btn("save-scanner", t.save, { kind: "filled" })}</span>`;
      } else if (this._mode === "move") {
        const [x, y] = this._scannerPos(s);
        body = this._alert("info", t.hintMove) + this._kv([[t.position, `${fmt(x, 2)} / ${fmt(y, 2)} m`]]);
        actions = `<span></span><span>${this._btn("cancel", t.cancel)}${this._btn("save-move", t.save, { kind: "filled" })}</span>`;
      } else {
        const pairs = plan.trackers.map((tr) => [tr.name, this._pairsText(s.key, tr.key)]).filter(([, v]) => v);
        body = this._confirmHtml() + this._kv([
          [t.position, `${fmt(s.x)} / ${fmt(s.y)} m`],
          [t.height, `${fmt(s.z)} m`],
          [t.offset, `${s.rssi_offset > 0 ? "+" : ""}${fmt(s.rssi_offset)} dB`],
          [t.pairs, pairs.length ? pairs.map(([n, v]) => `${esc(n)} ${v}`).join(" · ") : esc(t.none)],
        ]) + `<div class="subhead">${esc(t.hears)}</div>${hears}`;
        actions = this._btn("remove-scanner", t.remove, { kind: "danger", disabled: !!this._confirm }) +
          `<span>${this._btn("move", t.move)}${this._btn("edit-scanner", t.edit)}</span>`;
      }
      return this._card("", body, actions);
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
        body = this._formSlot("tracker", [
          this._nameField(t.name),
          { type: "grid", name: "", schema: [
            this._num("height", t.height, "m"),
            { ...this._num("ref_power", t.refPower, "dBm"), helper: `${t.default} ${fmt(plan.settings.ref_power_default, 0)} dBm` },
          ] },
        ], f, (v) => {
          f.name = v.name ?? null;
          f.height = v.height ?? null;
          f.ref_power = v.ref_power ?? null;
        }) +
          `<div class="subhead">${esc(t.pairs)}</div>` +
          this._formSlot("tracker-pairs", [
            { type: "grid", name: "", schema: plan.scanners.map((sc) => this._num(sc.key, sc.name, "dB")) },
          ], f.pairs, (v) => {
            for (const sc of plan.scanners) f.pairs[sc.key] = v[sc.key] ?? null;
          });
        actions = `<span></span><span>${this._btn("cancel", t.cancel)}${this._btn("save-tracker", t.save, { kind: "filled" })}</span>`;
      } else {
        const ref = tr.ref_power == null ? `${esc(t.default)} (${fmt(plan.settings.ref_power_default, 0)} dBm)` : `${fmt(tr.ref_power)} dBm`;
        const pairs = plan.scanners.map((s) => [s.name, this._pairsText(s.key, tr.key)]).filter(([, v]) => v);
        body = this._confirmHtml() + `<div class="status"><span class="dot" style="background:${info.color}"></span>${status}</div>` + this._kv([
          [t.height, `${fmt(tr.height, 2)} m`],
          [t.refPower, ref],
          [t.pairs, pairs.length ? pairs.map(([n, v]) => `${esc(n)} ${v}`).join(" · ") : esc(t.none)],
        ]) + `<div class="subhead">${esc(t.heardBy)}</div>${readings}`;
        actions = this._btn("remove-tracker", t.remove, { kind: "danger", disabled: !!this._confirm }) +
          `<span>${this._btn("measure-tracker", t.measure)}${this._btn("edit-tracker", t.edit)}</span>`;
      }
      return this._card("", body, actions);
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
        run = this._card(`${t.measure} · ${t.running}`,
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
          this._formSlot("measure", [
            { name: "tracker", label: t.pickTracker, required: true, selector: { select: { mode: "dropdown", options: plan.trackers.map((x) => ({ value: x.key, label: x.name })) } } },
            this._num("height", t.height, "m"),
          ], { tracker: m.tracker, height: m.height }, (v) => {
            if (v.tracker !== m.tracker) {
              // Another tracker: its height is the start
              m.tracker = v.tracker;
              m.height = plan.trackers.find((x) => x.key === v.tracker)?.height ?? 1;
              this._redraw = true;
              this._render();
              return;
            }
            m.height = v.height ?? m.height;
          }) +
          (ready ? this._kv([[t.runAt, `${fmt(m.x, 2)} / ${fmt(m.y, 2)} m`]]) : this._alert("info", t.hintMeasure)),
          `<span></span>${this._btn("cal-start", t.start, { kind: "filled", disabled: !ready })}`);
      }
      const runs = this._calibration.runs;
      const cols = plan.scanners.map((s) => `<th class="n" title="${esc(s.name)}">${esc(s.name)}</th>`).join("");
      const rows = runs.map((r) => {
        const counts = plan.scanners.map((s) => `<td class="n">${r.counts?.[s.key] || 0}</td>`).join("");
        const length = r.running ? esc(t.running) : `${Math.round(r.duration)} s`;
        return `<tr class="${r.running ? "live" : ""}"><td class="nowrap"><span class="dot" style="background:${trackerColor(plan, r.tracker)}"></span>${esc(name(r.tracker))}</td>` +
          `<td class="n">${fmt(r.x)} / ${fmt(r.y)}</td><td class="n">${length}</td>${counts}` +
          `<td>${iconButton("delete", t.delete, `class="small" data-act="cal-delete" data-key="${esc(r.id)}"${this._busy ? " disabled" : ""}`)}</td></tr>`;
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
        this._formSlot("fit", [{ name: "fitN", label: t.fitExponent, selector: { boolean: {} } }], { fitN: this._cal.fitN }, (v) => {
          this._cal.fitN = !!v.fitN;
        }) + preview,
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
        (sections[sec] ||= []).push(
          kind === "bool" ? { name: key, label: t[label], selector: { boolean: {} } } : this._num(key, t[label], null)
        );
      }
      const form = (sec) => this._formSlot(`settings-${sec}`, sections[sec], f, (v) => {
        this._settings = { ...(this._settings || plan.settings) };
        for (const field of sections[sec]) this._settings[field.name] = v[field.name] ?? null;
      });
      const save = `<span></span>${this._btn("save-settings", t.save, { kind: "filled" })}`;
      return ["engine", "motion", "roomRules", "robust", "timeline"]
        .map((id) => this._card(t[id], form(id) + (id === "timeline" ? `<div class="muted small">${esc(t.timelineHint)}</div>` : ""), save))
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

    // ---- Coverage ----

    // What the map shown depends on: for the model the scanners and the
    // engine's values, for the measurement a refresh, a reset or the minute
    _covKey() {
      const c = this._cov;
      const plan = this._plan;
      const tracker = c.tracker === ANY ? null : c.tracker;
      // The measurement grows while the page is open: fetched again every minute
      if (c.mode === "measured") return JSON.stringify(["measured", tracker, c.stamp, Math.floor(Date.now() / MEASURED_REFETCH_MS)]);
      return JSON.stringify(["model", tracker, c.probes, c.stamp, plan.scanners, plan.trackers, plan.settings, plan.pair_offsets, plan.rooms]);
    }

    async _covLoad() {
      const c = this._cov;
      if (!this._plan || c.loading) return;
      if (c.tracker !== ANY && !this._plan.trackers.some((x) => x.key === c.tracker)) c.tracker = ANY;
      const key = this._covKey();
      if (key === c.key) return;
      c.loading = true;
      const msg = { type: `ble_floorplan/coverage/${c.mode}` };
      if (c.tracker !== ANY) msg.tracker = c.tracker;
      if (c.mode === "model") msg.probes = c.probes;
      try {
        c.data = { mode: c.mode, ...(await this._hass.callWS(msg)) };
      } catch (err) {
        c.data = null;
        this._note = { kind: "err", text: String(err?.message || err?.code || err) };
      }
      c.key = key;
      c.loading = false;
      // Changed meanwhile: _render fetches again
      this._render();
    }

    _covMarks() {
      const d = this._cov.data;
      const t = this._t;
      const fmt = this._fmt;
      let out = "";
      if (d && d.mode === this._cov.mode) {
        const size = d.cell;
        const B = this._bounds || computeBounds(this._plan);
        out = d.cells.map((c) => {
          const [ix, iy, lvl] = c;
          let tip;
          let up = false;
          if (d.mode === "model") {
            tip = t.covCellModel.replace("{good}", c[3]).replace("{hdop}", c[4] == null ? t.unknown : fmt(c[4], 1));
            up = c.length > 5 && lvl > c[5];
          } else {
            tip = t.covCellMeasured.replace("{good}", fmt(c[3], 1)).replace("{miss}", fmt(c[4], 1)).replace("{time}", this._covTime(c[5]));
          }
          // A cell on the far edge ends at the outer wall
          const x = ix * size;
          const y = iy * size;
          const w = Math.min(size, B.w - x);
          const h = Math.min(size, B.h - y);
          return `<rect class="cov l${lvl}${up ? " up" : ""}" x="${x}" y="${y}" width="${w}" height="${h}"><title>${esc(tip)}</title></rect>`;
        }).join("");
      }
      if (this._cov.mode === "model") {
        out += this._cov.probes.map((p, i) =>
          `<g class="probe"><rect x="${p.x - 0.25}" y="${p.y - 0.25}" width="0.5" height="0.5" rx="0.08"/>` +
          `<text x="${p.x}" y="${p.y}">P${i + 1}</text></g>`).join("");
      }
      return out;
    }

    // Seconds as minutes or hours, for a cell or a room of the measurement
    _covTime(s) {
      const fmt = this._fmt;
      return s >= 3600 ? `${fmt(s / 3600, 1)} h` : `${Math.max(1, Math.round(s / 60))} min`;
    }

    _covSwatch(lvl) {
      return `<span class="covsw l${lvl}"></span>`;
    }

    _coverageSheet() {
      const t = this._t;
      const fmt = this._fmt;
      const plan = this._plan;
      const c = this._cov;
      const d = c.data && c.data.mode === c.mode ? c.data : null;
      const options = [{ value: ANY, label: c.mode === "model" ? t.covDefault : t.covAll }, ...plan.trackers.map((x) => ({ value: x.key, label: x.name }))];
      const form = this._formSlot("coverage", [
        { name: "mode", label: t.covMode, required: true, selector: { select: { mode: "box", options: [{ value: "model", label: t.covModel }, { value: "measured", label: t.covMeasured }] } } },
        { name: "tracker", label: t.tracker, required: true, selector: { select: { mode: "dropdown", options } } },
      ], { mode: c.mode, tracker: c.tracker }, (v) => {
        c.mode = v.mode || c.mode;
        c.tracker = v.tracker || ANY;
        this._redraw = true;
        this._render();
      });
      const legend = `<div class="covlegend">` +
        [[2, t.covGood], [1, t.covFair], [0, t.covPoor]].map(([l, label]) => `<div>${this._covSwatch(l)}${esc(label)}</div>`).join("") +
        (c.mode === "model" && c.probes.length ? `<div><span class="covsw up"></span>${esc(t.covUp)}</div>` : "") + `</div>`;
      const hint = c.mode === "model"
        ? t.covModelHint.replace("{rssi}", fmt(d?.good_rssi ?? -85))
        : t.covMeasuredHint;
      let summary = "";
      if (d && d.mode === "model" && d.cells.length) {
        const n = [0, 0, 0];
        for (const cell of d.cells) n[cell[2]] += 1;
        const pct = (k) => Math.round((100 * n[k]) / d.cells.length);
        summary = `<div class="subhead">${esc(t.covSummary.replace("{good}", pct(2)).replace("{fair}", pct(1)).replace("{poor}", pct(0)))}</div>`;
      }
      const main = this._card(t.coverage, form + summary + legend + `<div class="muted small">${esc(hint)}</div>`);
      return main + (c.mode === "model" ? this._probesCard(d) : this._measuredCard(d)) + this._covRoomsCard(d);
    }

    _probesCard(d) {
      const t = this._t;
      const fmt = this._fmt;
      const c = this._cov;
      const rows = c.probes.map((p, i) =>
        `<tr><td>P${i + 1}</td><td class="n">${fmt(p.x, 2)} / ${fmt(p.y, 2)} m</td>` +
        `<td>${iconButton("delete", t.remove, `class="small" data-act="cov-probe-del" data-key="${i}"`)}</td></tr>`).join("");
      const body = (c.probes.length < MAX_PROBES ? this._alert("info", t.probeHint) : "") +
        (rows ? `<table class="data"><tr><th></th><th class="n">x / y</th><th></th></tr>${rows}</table>` : "") +
        (d ? `<div class="muted small">${esc(t.probeOffset.replace("{offset}", fmt(d.probe_offset, 1)))}</div>` : "");
      return this._card(t.probes, body, c.probes.length ? `<span></span>${this._btn("cov-probes-clear", t.removeAll)}` : "");
    }

    _measuredCard(d) {
      const t = this._t;
      const c = this._cov;
      let body = "";
      if (d && !d.recording) body += this._alert("info", t.covOff);
      if (d) {
        body += d.days.length
          ? `<div>${esc(t.covDays.replace("{n}", d.days.length).replace("{first}", new Date(`${d.days[0]}T00:00:00Z`).toLocaleDateString(this._hass.language)))}</div>`
          : `<div class="muted">${esc(t.covNone)}</div>`;
      } else {
        body += `<div class="muted">…</div>`;
      }
      if (c.confirm) {
        body += `<ha-alert alert-type="warning">${esc(t.covResetAsk)}` +
          `<ha-button slot="action" appearance="plain" data-act="cov-reset-cancel">${esc(t.cancel)}</ha-button>` +
          `<ha-button slot="action" variant="danger" data-act="cov-reset-ok">${esc(t.covReset)}</ha-button></ha-alert>`;
      }
      const actions = d && !d.recording ? `<span></span>${this._btn("go-settings", t.tabSettings)}` : "";
      return this._card(t.covMeasured, body,
        `${actions || "<span></span>"}${this._btn("cov-reset", t.covReset, { kind: "danger", disabled: !d?.days.length || c.confirm })}`);
    }

    _covRoomsCard(d) {
      const t = this._t;
      const fmt = this._fmt;
      if (!d || !d.rooms.length) return "";
      let rows;
      let head;
      if (d.mode === "model") {
        // Worst first: the share of poor cells, then of fair ones
        const rooms = d.rooms.map((r) => {
          const total = r.cells[0] + r.cells[1] + r.cells[2];
          return { name: r.name, p: r.cells.map((k) => Math.round((100 * k) / total)) };
        }).sort((a, b) => b.p[0] - a.p[0] || b.p[1] - a.p[1]);
        head = `<tr><th>${esc(t.room)}</th>${[2, 1, 0].map((l) => `<th class="n">${this._covSwatch(l)}</th>`).join("")}</tr>`;
        rows = rooms.map((r) => `<tr><td>${esc(r.name)}</td>${[2, 1, 0].map((l) => `<td class="n">${r.p[l]} %</td>`).join("")}</tr>`).join("");
      } else {
        const rooms = [...d.rooms].sort((a, b) => a.level - b.level);
        head = `<tr><th>${esc(t.room)}</th><th>${esc(t.covLevel)}</th><th class="n">${esc(t.covGoodScanners)}</th><th class="n">${esc(t.covTime)}</th></tr>`;
        rows = rooms.map((r) => {
          const lvl = r.level >= 1.5 ? 2 : r.level >= 0.5 ? 1 : 0;
          return `<tr><td>${esc(r.name)}</td><td>${this._covSwatch(lvl)}</td><td class="n">${fmt(r.good, 1)}</td><td class="n">${this._covTime(r.seconds)}</td></tr>`;
        }).join("");
      }
      return this._card(t.covRooms, `<div class="scroll"><table class="data">${head}${rows}</table></div>`);
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
      // A list item opens with Enter or Space, as a button would
      root.addEventListener("keydown", (e) => {
        const item = e.target.closest?.(".item[data-act]");
        if (!item || e.target !== item || (e.key !== "Enter" && e.key !== " ")) return;
        e.preventDefault();
        this._act(item.dataset.act, item);
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
      });
      root.addEventListener("pointerdown", (e) => this._dragStart(e));
    }

    // The floor plan as YAML; every other field is an ha-form with its own handler
    _input(el) {
      if (el.dataset?.f === "layout") {
        this._layout = el.value;
        this._layoutEdited = true;
      }
    }

    _mapClick(e) {
      const plan = this._plan;
      if (!plan || e.target.closest?.(".maptools")) return;
      if (this._aiming) {
        const [x, y] = toPlan(this.shadowRoot, e, this._bounds);
        if (this._tab === "calibration") {
          this._measure.x = snap(x);
          this._measure.y = snap(y);
        } else if (this._tab === "coverage") {
          this._cov.probes = [...this._cov.probes, { x: snap(x), y: snap(y) }];
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
        case "refresh":
          this._refresh();
          break;
        case "integration":
          navigate(INTEGRATION_PATH);
          break;
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
          this._confirm = null;
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
            this._layoutEdited = false;
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
          this._form = { name: s.name, x: s.x, y: s.y, z: s.z, rssi_offset: s.rssi_offset, pairs };
          this._note = null;
          break;
        }
        case "save-scanner": {
          const s = plan.scanners.find((x) => x.key === this._selScanner);
          const f = this._form;
          this._call({
            type: "ble_floorplan/set_scanner", key: s.key, name: (f.name ?? "").trim() || s.name,
            x: f.x ?? s.x, y: f.y ?? s.y, z: f.z ?? s.z,
            rssi_offset: f.rssi_offset ?? s.rssi_offset, pair_offsets: f.pairs,
          }, saved);
          return;
        }
        case "edit-tracker": {
          const tr = plan.trackers.find((x) => x.key === this._selTracker);
          const pairs = {};
          for (const s of plan.scanners) pairs[s.key] = plan.pair_offsets?.[s.key]?.[tr.key] ?? null;
          this._form = { name: tr.name, height: tr.height, ref_power: tr.ref_power ?? null, pairs };
          this._note = null;
          break;
        }
        case "save-tracker": {
          const tr = plan.trackers.find((x) => x.key === this._selTracker);
          const f = this._form;
          this._call({
            type: "ble_floorplan/set_tracker", key: tr.key, name: (f.name ?? "").trim() || tr.name,
            height: f.height ?? tr.height, ref_power: f.ref_power, pair_offsets: f.pairs,
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
          const k = act === "remove-scanner" ? this._selScanner : this._selTracker;
          const item = (act === "remove-scanner" ? plan.scanners : plan.trackers).find((x) => x.key === k);
          this._confirm = { act, key: k, name: item?.name || k };
          this._note = null;
          break;
        }
        case "confirm-cancel":
          this._confirm = null;
          break;
        case "confirm-ok": {
          const c = this._confirm;
          if (!c) return;
          this._confirm = null;
          const isScanner = c.act === "remove-scanner";
          const k = c.key;
          this._call({ type: `ble_floorplan/${c.act.replace("-", "_")}`, key: k }, () => {
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
        case "cov-probe-del":
          this._cov.probes = this._cov.probes.filter((_, i) => String(i) !== key);
          this._render();
          return;
        case "cov-probes-clear":
          this._cov.probes = [];
          this._render();
          return;
        case "cov-reset":
          this._cov.confirm = true;
          this._render();
          return;
        case "cov-reset-cancel":
          this._cov.confirm = false;
          this._render();
          return;
        case "cov-reset-ok":
          this._cov.confirm = false;
          this._call({ type: "ble_floorplan/coverage/reset" }, () => {
            this._cov.stamp += 1;
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
          <div class="tlrow">${iconButton("minus", t.zoomOut, 'class="small" data-tlzoom="-10"')}<input id="tlzoom" type="range" min="0" max="100" value="${v}">${iconButton("plus", t.zoomIn, 'class="small" data-tlzoom="10"')}</div>
          <div class="tlrow">${iconButton("play", t.play, 'class="small" id="tlplay"')}<select id="tlspeed" title="${esc(t.speed)}">${speeds}</select></div>
          <ha-button size="small" appearance="plain" id="tllive">${esc(t.backToLive)}</ha-button>
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
        play.path = MDI[tl.playing ? "pause" : "play"];
        play.label = tl.playing ? t.pause : t.play;
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
      root.querySelectorAll("[data-tlzoom]").forEach((b) => b.addEventListener("click", () => {
        const v = Math.min(100, Math.max(0, Number(zoom.value) + Number(b.dataset.tlzoom)));
        zoom.value = v;
        this._tlZoom(SPP_MAX * Math.pow(SPP_MIN / SPP_MAX, v / 100), false);
        this._tlFrame();
      }));
      root.getElementById("tlplay")?.addEventListener("click", () => {
        if (tl.cursor == null) return;
        if (tl.playing) this._tlPause();
        else this._tlPlay();
        this._tlFrame();
      });
      root.getElementById("tlspeed")?.addEventListener("change", (e) => {
        tl.speed = Number(e.target.value);
        e.target.blur();
      });
      root.getElementById("tllive")?.addEventListener("click", () => {
        if (tl.cursor == null) return;
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

  // Home Assistant's elements bring their own look; this lays them out and
  // draws what Home Assistant has no element for (tabs, tables, the timeline),
  // in the colours and sizes of the active theme
  const STYLE = `
    /* The panel's own container has no height of its own: the page takes the window */
    :host { display: block; height: 100vh; height: 100dvh; background: var(--primary-background-color); color: var(--primary-text-color);
      font-family: var(--ha-font-family-body, Roboto, Noto, sans-serif); font-size: var(--ha-font-size-m, 14px); line-height: 1.5;
      -webkit-font-smoothing: antialiased; }
    * { box-sizing: border-box; }
    /* Like the settings and other panels: the header in the sidebar's colour, with a line */
    ha-top-app-bar-fixed { height: 100%;
      --app-header-background-color: var(--sidebar-background-color, var(--card-background-color));
      --app-header-text-color: var(--sidebar-text-color, var(--primary-text-color));
      --app-header-border-bottom: 1px solid var(--divider-color); }
    /* One header row: icon, name, tabs; the tabs fill the bar's height for their line */
    .head { display: flex; align-items: center; height: var(--header-height, 56px); min-width: 0; }
    .brand { width: 24px; height: 24px; flex: none; margin-inline-end: 12px; object-fit: contain; }
    .name { flex: none; white-space: nowrap; }
    /* The header's actions, as on every page of Nico's apps and integrations: stamp,
       refresh, settings */
    .stamp { color: var(--secondary-text-color); font-size: var(--ha-font-size-m, 14px);
      white-space: nowrap; align-self: center; margin-inline-end: 4px; }
    #refresh.loading { animation: spin 1s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    @media (max-width: 600px) { .stamp { display: none; } }
    .app { display: flex; flex-direction: column;
      height: calc(100vh - var(--header-height, 56px) - var(--safe-area-inset-top, 0px));
      height: calc(100dvh - var(--header-height, 56px) - var(--safe-area-inset-top, 0px)); }
    .tabs { display: flex; flex: 0 1 auto; min-width: 0; height: 100%; margin-inline-start: 24px; overflow-x: auto; scrollbar-width: none;
      font-size: var(--ha-font-size-m, 14px); line-height: 1.5; }
    .tab { display: flex; align-items: center; justify-content: center; height: 100%; padding: 0 20px; position: relative;
      color: var(--sidebar-text-color, var(--primary-text-color)); text-decoration: none; font-weight: var(--ha-font-weight-medium, 500);
      white-space: nowrap; opacity: 0.8; }
    .tab:hover { background: color-mix(in srgb, var(--primary-text-color) 5%, transparent); }
    .tab.active { color: var(--primary-color); opacity: 1; }
    .tabs .tab.active::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 2px; background: var(--primary-color); }
    .bottom-tabs { display: flex; flex: none; justify-content: space-around; background: var(--sidebar-background-color, var(--card-background-color));
      border-top: 1px solid var(--divider-color); padding-bottom: env(safe-area-inset-bottom); }
    .bottom-tabs .tab { flex: 1 1 0; flex-direction: column; gap: 2px; height: 56px; padding: 6px 2px 4px;
      font-size: var(--ha-font-size-xs, 11px); min-width: 0; }
    .bottom-tabs .tab span { overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
    .bottom-tabs .tab ha-svg-icon { padding: 2px 12px; border-radius: 14px; box-sizing: content-box; }
    .bottom-tabs .tab.active ha-svg-icon { background: color-mix(in srgb, var(--primary-color) 15%, transparent); }
    .content { flex: 1 1 auto; min-height: 0; display: flex; }
    .stage { flex: 1 1 auto; min-width: 0; display: flex; gap: 12px; padding: 16px; }
    .map { flex: 1 1 auto; height: 100%; display: flex; flex-direction: column; padding: 4px 8px 12px; background: var(--card-background-color);
      border-radius: var(--ha-card-border-radius, 12px); border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color)); }
    #svg { flex: 1 1 auto; min-height: 0; }
    .maptools { display: flex; justify-content: flex-end; flex: none; }
    .menuwrap { position: relative; }
    .sheet { flex: 0 0 min(420px, 45%); overflow-y: auto; padding: 16px 16px 0 0; }
    .content:not(.withmap) .sheet { flex: 1 1 auto; padding: 16px 16px 0; }
    .content.settings .sheet > *, .content:not(.withmap) .sheet > * { max-width: 720px; margin-left: auto; margin-right: auto; }
    .content.nosheet { flex-direction: column; }
    .content.nosheet .stage { min-height: 0; padding-bottom: 0; }
    .about { text-align: center; color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 12px); padding: 8px 0 24px; }
    .content.nosheet .about { flex: none; padding: 8px 0; }
    .narrow .content { display: block; overflow-y: auto; }
    .narrow .stage { padding: 8px 8px 0; }
    .narrow .map { height: auto; }
    .narrow .map svg:not(.mdi) { height: auto; max-height: 62vh; }
    .narrow .content.nosheet { display: flex; overflow: hidden; }
    .narrow .content.nosheet .stage { flex: 1 1 auto; }
    .narrow .content.nosheet .map { height: 100%; }
    .narrow .content.nosheet .map svg:not(.mdi) { height: 100%; max-height: none; }
    .narrow .sheet { padding: 8px 8px 0; overflow: visible; }
    ha-card { display: block; margin-bottom: 16px; overflow: hidden; }
    .narrow ha-card { margin-bottom: 8px; }
    .card-content { padding: 0 16px 16px; }
    .card-content.top { padding-top: 16px; }
    ha-card.list .card-content { padding: 0 0 8px; }
    .card-actions { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 8px;
      border-top: 1px solid var(--divider-color); }
    .card-actions > span { display: flex; gap: 8px; flex-wrap: wrap; }
    ha-alert { display: block; margin-bottom: 16px; }
    ha-card ha-alert { margin: 0 0 12px; }
    ha-alert ha-button { margin-inline-start: 8px; }
    ha-icon-button.small { --mdc-icon-button-size: 32px; --mdc-icon-size: 20px; }
    .haform + .subhead { margin-top: 16px; }
    .item { display: flex; align-items: center; gap: 16px; width: 100%; min-height: 64px; padding: 8px 16px; border: 0;
      background: none; color: var(--primary-text-color); font: inherit; text-align: left; cursor: pointer; }
    .item:hover { background: var(--secondary-background-color); }
    .icon-bg { display: flex; padding: 8px; border-radius: 50%; color: var(--text-primary-color, #fff); background: var(--primary-color); flex: none;
      --mdc-icon-size: 20px; }
    .text { display: flex; flex: 1; flex-direction: column; min-width: 0; }
    .headline { font-size: var(--ha-font-size-l, 16px); line-height: 24px; }
    .supporting { font-size: var(--ha-font-size-m, 14px); line-height: 20px; color: var(--secondary-text-color); }
    .next { color: var(--secondary-text-color); }
    .muted { color: var(--secondary-text-color); }
    .small { font-size: var(--ha-font-size-s, 12px); line-height: 16px; margin-top: 8px; }
    .status { display: flex; align-items: center; color: var(--secondary-text-color); margin-bottom: 8px; }
    .subhead { margin: 16px 0 4px; font-weight: var(--ha-font-weight-medium, 500); }
    table { border-collapse: collapse; width: 100%; }
    table.kv th { width: 40%; text-align: left; font-weight: 400; color: var(--secondary-text-color); padding: 8px 16px 8px 0; vertical-align: top; }
    table.kv td { padding: 8px 0; }
    table.kv tr + tr th, table.kv tr + tr td { border-top: 1px solid var(--divider-color); }
    table.data th { text-align: left; font-size: var(--ha-font-size-s, 12px); font-weight: var(--ha-font-weight-medium, 500); padding: 8px 12px 8px 0; white-space: nowrap; }
    table.data td { padding: 6px 12px 6px 0; border-top: 1px solid var(--divider-color); }
    table.data td:last-child, table.data th:last-child { padding-right: 0; }
    .n { text-align: right !important; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .nowrap { white-space: nowrap; }
    tr.ign td { color: var(--secondary-text-color); }
    tr.live td { color: var(--primary-color); }
    .runs th { max-width: 6em; overflow: hidden; text-overflow: ellipsis; }
    .runs td { vertical-align: middle; }
    .diff tr.sec td { color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 12px); padding-top: 12px; border: 0; }
    .diff tr.changed td:nth-child(3) { font-weight: 600; color: var(--primary-color); }
    .scroll { overflow-x: auto; }
    td .dot, .nowrap .dot { vertical-align: -1px; }
    .covlegend { display: flex; flex-direction: column; gap: 4px; margin: 12px 0 8px; }
    .covlegend div { display: flex; align-items: center; }
    .covsw { display: inline-block; flex: none; width: 14px; height: 14px; border-radius: 3px; margin-right: 8px; vertical-align: -2px; opacity: 0.75; }
    .covsw.l0 { background: var(--error-color, #db4437); }
    .covsw.l1 { background: var(--warning-color, #ffa600); }
    .covsw.l2 { background: var(--success-color, #43a047); }
    .covsw.up { background: none; border: 1px dashed var(--primary-text-color); }
    th .covsw { margin-right: 0; }
    /* The floor plan as YAML: Home Assistant's code colours, without loading its editor */
    textarea { width: 100%; min-height: 240px; padding: 12px; border: 0; border-radius: 4px 4px 0 0; resize: vertical; outline: 0;
      background: var(--code-editor-background-color, var(--secondary-background-color)); color: var(--primary-text-color);
      border-bottom: 1px solid var(--input-idle-line-color, var(--secondary-text-color));
      font-family: var(--ha-font-family-code, var(--code-font-family, monospace)); font-size: 13px; line-height: 1.5; white-space: pre; }
    textarea:focus { border-bottom: 2px solid var(--primary-color); }
    .tl { flex: 0 0 calc(75px + var(--tlx, 37px)); display: flex; flex-direction: column; font-size: 12px; overflow: hidden; user-select: none; -webkit-user-select: none;
      background: var(--card-background-color); border-radius: var(--ha-card-border-radius, 12px);
      border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color)); }
    .tlhead { padding: 8px 6px 6px; display: flex; flex-direction: column; gap: 4px; border-bottom: 1px solid var(--divider-color); }
    .tldate { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 0 2px; }
    .tlrow { display: flex; gap: 2px; align-items: center; }
    .tlrow ha-icon-button { flex: none; color: var(--primary-text-color); }
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
