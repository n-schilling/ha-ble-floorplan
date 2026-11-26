// BLE Floorplan panel: the page in the sidebar where administrators watch the
// trackers live and on the timeline, manage the scanners and trackers,
// calibrate, check the coverage and the scanner quality, and set everything
// up. Five areas (Live, Devices, Calibration, Analysis, Setup), each with its
// pages as tabs below the header, in Home Assistant's own frame for pages with
// tabs (hass-tabs-subpage): the areas in the header, at the bottom on a phone.
// A scanner or a tracker opens as a subpage with a back arrow. The floor plan
// is beside most pages. Explanations sit behind an (i) with Home Assistant's
// tooltip; what stays on the page is state and the one line that asks for a
// tap on the plan. Everything comes from the integration over the WebSocket API.
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
  errorText,
  esc,
  fieldNumber,
  formatter,
  numOrNull,
  icon,
  iconButton,
  keep,
  loadLabels,
  floorAt,
  floorOf,
  levelOfFloor,
  levelSwitch,
  levelsOf,
  loadNumber,
  loadRot,
  navigate,
  positionLevel,
  shownLevel,
  planInfo,
  planSvg,
  snap,
  texts,
  toPlan,
  trackerColor,
} from "./ble-floorplan-plan.js?v=0.36.2";
import { EDITOR_CSS, PlanEditor } from "./ble-floorplan-editor.js?v=0.36.2";

if (!customElements.get("ble-floorplan-panel")) {
  const ROT_KEY = "ble-floorplan-panel-rot";
  // Home Assistant's own page of the integration, behind the cog in the header
  const INTEGRATION_PATH = "/config/integrations/integration/ble_floorplan";
  const LABELS_KEY = "ble-floorplan-panel-labels";
  // How the floor plan is edited: drawn or as YAML, kept across visits
  const PLAN_MODE_KEY = "ble-floorplan-panel-planmode";
  // The level shown, kept across visits
  const LEVEL_KEY = "ble-floorplan-panel-level";
  // The system details of the open scanner are fetched again after this long
  const SYSTEM_REFETCH_MS = 10000;
  // The scanner quality changes slowly: fetched again after a minute
  const QUALITY_REFETCH_MS = 60000;

  // The five areas and their pages: area, icon, text, pages (page, text)
  const AREAS = [
    ["live", "tracker", "tabLive", [["now", "subNow"], ["history", "subHistory"]]],
    ["devices", "scanner", "tabDevices", [["scanners", "scanners"], ["trackers", "trackers"]]],
    ["calibration", "calibration", "tabCalibration", [["measure", "subMeasure"], ["runs", "runs"], ["tuning", "subTuning"]]],
    ["analysis", "coverage", "tabAnalysis", [["coverage", "coverage"], ["quality", "subQuality"]]],
    ["setup", "settings", "tabSetup", [["overview", "subOverview"], ["plan", "plan"], ["location", "subLocation"], ["recording", "subRecording"]]],
  ];
  // The addresses of the pages before the areas, as bookmarks still have them
  const OLD_PAGES = {
    plan: "setup/plan", scanners: "devices/scanners", trackers: "devices/trackers", calibration: "calibration/measure",
    coverage: "analysis/coverage", timeline: "live/history", settings: "setup/location",
  };
  const areaOf = (page) => AREAS.find((a) => a[3].some(([p]) => p === page)) || AREAS[0];
  const pagePath = (page) => `${PANEL_PATH}/${areaOf(page)[0]}/${page}`;
  // Pages without the floor plan beside them
  const NO_MAP = new Set(["overview", "location", "recording", "quality", "tuning", "runs"]);
  // The pages of a scanner: view, text
  const SCANNER_VIEWS = [["overview", "subOverview"], ["quality", "qTitle"], ["system", "subSystem"]];
  // The settings of the page Recording; the others are on Positioning
  const RECORDING = new Set(["timeline", "qualitySec"]);
  // The setup counts as done with this many scanners and this share of the area good in the model
  const MIN_SCANNERS = 3;
  const COVERAGE_DONE = 80;

  // Section, setting, text, kind ("num" or "bool"), unit
  const SETTING_FIELDS = [
    ["engine", "attenuation", "attenuation", "num"],
    ["engine", "wall_loss", "wallLoss", "num", "dB"],
    ["engine", "ref_power_default", "refDefault", "num", "dBm"],
    ["engine", "max_distance", "maxDistance", "num", "m"],
    ["engine", "smoothing_seconds", "smoothing", "num", "s"],
    ["engine", "min_move", "minMove", "num", "m"],
    ["engine", "clamp", "clamp", "bool"],
    ["engine", "clamp_outdoor", "clampOutdoor", "bool"],
    ["engine", "height_uncertainty", "heightUncertainty", "bool"],
    ["engine", "height_spread", "heightSpread", "num", "m"],
    ["motion", "max_speed", "maxSpeed", "num", "m/s"],
    ["motion", "jump_distance", "jumpDistance", "num", "m"],
    ["motion", "jump_confirm_seconds", "jumpConfirm", "num", "s"],
    ["motion", "walls", "walls", "bool"],
    ["motion", "wall_tolerance", "wallTolerance", "num", "m"],
    ["motion", "exterior_doors", "exteriorDoors", "bool"],
    ["floorsSec", "stairs_only", "stairsOnly", "bool"],
    ["floorsSec", "floor_loss", "floorLoss", "num", "dB"],
    ["floorsSec", "floor_margin", "floorMargin", "num", "m"],
    ["floorsSec", "floor_hold_seconds", "floorHold", "num", "s"],
    ["roomRules", "away_seconds", "awaySeconds", "num", "s"],
    ["roomRules", "room_hold_seconds", "roomHold", "num", "s"],
    ["roomRules", "room_margin", "roomMargin", "num", "m"],
    ["robust", "robust_residual", "robustResidual", "num", "m"],
    ["timeline", "history_days", "historyDays", "num", "d"],
    ["qualitySec", "quality_hours", "qualityHours", "num", "h"],
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
  // Heights a tracker typically has in a run, in metres
  const HEIGHT_PRESETS = [["hFloor", 0], ["hTable", 0.75], ["hPocket", 1], ["hHand", 1.2]];
  const utcDay = (t) => new Date(t * 1000).toISOString().slice(0, 10);
  const dayStart = (d) => Date.parse(`${d}T00:00:00Z`) / 1000;
  const nowS = () => Date.now() / 1000;

  class BleFloorplanPanel extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._tab = "now";
      // The drawing of the floor plan, while it is being edited
      this._editor = new PlanEditor(this);
      window.addEventListener("keydown", (e) => {
        if (!this.isConnected || this._tab !== "plan" || this._typing()) return;
        if (this._editor.key(e)) {
          e.preventDefault();
          this._render();
        }
      });
      this._plan = null;
      this._positions = {};
      this._offline = [];
      this._calibration = { active: null, runs: [] };
      this._rot = loadRot(ROT_KEY, 0);
      this._levelKept = loadNumber(LEVEL_KEY, 0);
      this._labels = loadLabels(LABELS_KEY, { rooms: true, scanners: true, trackers: true });
      // The system details of the open scanner: {key, at, data}, fetched while its page is shown
      this._sys = null;
      this._sysLoading = false;
      // The (i) of the page drawn: a fresh id each
      this._hid = 0;
      // The page of the scanner open: overview, quality or system
      this._sView = "overview";
      // Whether the ignored suggestions are unfolded
      this._ignOpen = false;
      // The coverage model of the setup overview: what it was fetched for, the share good
      this._ov = { key: null, data: null, loading: false };
      // The pair corrections typed on the page Fine-tuning, per scanner and tracker
      this._pairs = null;
      // The cross the arrow keys move on the coverage, where Enter places a test scanner
      this._cursor = null;
      let mode = null;
      try {
        mode = window.localStorage.getItem(PLAN_MODE_KEY);
      } catch {
        // no storage
      }
      this._planMode = mode === "yaml" ? "yaml" : "draw";
      // Scanner quality: the report of the scanner open, the lights of the list
      this._q = { open: null, data: null, at: 0, loading: false };
      this._qList = { data: null, at: 0, loading: false };
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
      this._measure = { tracker: null, height: null, x: null, y: null, auto: true };
      this._cal = { fitN: false, fitWalls: false, proposal: null, confirmClear: false };
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
          this._error = !err ? null : errorText(this._t, err);
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
      }
      // The frame and the forms need the new hass
      for (const el of this.shadowRoot.querySelectorAll("hass-tabs-subpage, ha-form")) el.hass = hass;
    }

    set narrow(narrow) {
      this._narrow = narrow;
      this._render();
    }

    // The address: /<area>/<page>; an old address goes to its new place, an
    // area alone to its first page, nothing to Live (to Setup while there is no plan)
    set route(route) {
      const parts = (route?.path || "").split("/").filter(Boolean);
      const search = window.location.search;
      // An old address; "calibration" is the name of an area as well as of an old page
      if (OLD_PAGES[parts[0]] && !AREAS.some((x) => x[0] === parts[0])) {
        navigate(`${PANEL_PATH}/${OLD_PAGES[parts[0]]}${search}`, true);
        return;
      }
      const area = AREAS.find((a) => a[0] === parts[0]);
      if (!area) {
        this._defaulted = true;
        navigate(`${PANEL_PATH}/live/now`, true);
        return;
      }
      if (!area[3].some(([p]) => p === parts[1])) {
        navigate(`${PANEL_PATH}/${area[0]}/${area[3][0][0]}${search}`, true);
        return;
      }
      const query = new URLSearchParams(search);
      // The same address again (Home Assistant after the query was read): nothing to do
      if (window.location.pathname + search === this._href && this._tab === parts[1]) return;
      this._href = window.location.pathname + search;
      this._route = { prefix: PANEL_PATH, path: `/${area[0]}/${parts[1]}` };
      this._setTab(parts[1], query.get("key"), query.get("view"));
    }

    set panel(panel) {
      this._panelInfo = panel;
    }

    connectedCallback() {
      this._live.ensure(this._hass);
      // Home Assistant passes a new route only when the path changes: an address that
      // changes only its query (another scanner, ?view=quality) is read here
      this._onLocation = () => {
        const { pathname, search } = window.location;
        if (!pathname.startsWith(`${PANEL_PATH}/`) || pathname + search === this._href) return;
        this.route = { prefix: PANEL_PATH, path: pathname.slice(PANEL_PATH.length) };
      };
      window.addEventListener("location-changed", this._onLocation);
      window.addEventListener("popstate", this._onLocation);
      // The measurement on the coverage page is fetched again even while no tracker moves
      this._covTimer = window.setInterval(() => {
        if (this._tab === "coverage" && this._cov.mode === "measured") this._render();
        if (this._tab === "scanners" && this._selScanner) this._render();
      }, MEASURED_REFETCH_MS / 4);
      this._render();
    }

    disconnectedCallback() {
      window.removeEventListener("location-changed", this._onLocation);
      window.removeEventListener("popstate", this._onLocation);
      this._live.close();
      this._tlPause();
      window.clearInterval(this._covTimer);
    }

    get _t() {
      return texts(this._hass);
    }

    // Whether the plan is being drawn: the draft takes the plan's place on the plan tab
    get _editing() {
      return this._tab === "plan" && this._editor.active;
    }

    // The plan on the map: the draft while drawing
    get _shownPlan() {
      return this._editing ? this._editor.plan() : this._plan;
    }

    // Redraw the map only, while dragging in the drawing
    _drawEditor() {
      const svg = this._svg();
      if (svg !== this._svgHtml) {
        this._svgHtml = svg;
        this.shadowRoot.getElementById("svg").innerHTML = svg;
      }
    }

    // A scanner or tracker opened from a list: its level is shown
    _showLevelOf(tab, key) {
      const plan = this._plan;
      if (!plan) return;
      if (tab === "scanners") {
        const s = plan.scanners.find((x) => x.key === key);
        if (s) this._levelKept = levelOfFloor(plan, s.floor ?? plan.floors?.[0]?.key ?? "");
      } else if (tab === "trackers" && this._positions[key]?.x != null) {
        this._levelKept = positionLevel(plan, this._positions[key]);
      }
    }

    // The level shown: the one chosen, if the plan has it
    get _level() {
      return shownLevel(this._shownPlan, this._levelKept);
    }

    get _fmt() {
      return formatter(this._hass);
    }

    _onEvent(event) {
      this._stamp = new Date();
      if (event.floorplan) {
        this._plan = event.floorplan;
        // A plan changed elsewhere: an untouched drawing starts from it
        if (this._editor.active && !this._editor.dirty) this._editor.start(this._plan);
        this._bounds = computeBounds(this._plan);
      }
      if (event.positions) this._positions = event.positions;
      if (event.offline) this._offline = event.offline;
      if (event.calibration) {
        this._calibration = event.calibration;
        // A run that ended by itself says what it saved, once; a stop on the page says it itself
        const stopped = event.calibration.stopped;
        if (stopped && this._seenStop !== undefined && stopped.run !== this._seenStop && stopped.auto) {
          const note = this._fitNote(stopped.fit);
          this._note = { kind: note.kind, text: this._t.autoStopped + note.text };
        }
        this._seenStop = stopped?.run ?? null;
      }
      if (event.about) this._about = event.about;
      // Opened without an address and there is no plan yet: the setup is where to start
      if (event.floorplan && this._defaulted) {
        this._defaulted = false;
        if (!event.floorplan.rooms.length && this._tab === "now") {
          navigate(`${PANEL_PATH}/setup/overview`, true);
          return;
        }
      }
      this._render();
    }

    // Changing the page: from a tab, from the address (a link of the card)
    _setTab(tab, key = null, view = null) {
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
        this._cursor = null;
      }
      if (tab === "scanners" && key) {
        this._selScanner = key;
        this._sView = SCANNER_VIEWS.some(([v]) => v === view) ? view : "overview";
      }
      if (tab === "trackers" && key) this._selTracker = key;
      if (key) this._showLevelOf(tab, key);
      if (tab !== "history") {
        this._tlPause();
        this._tl.cursor = null;
      }
      this._load();
      this._render();
    }

    _go(page) {
      navigate(pagePath(page));
    }

    // What a page loads once when it opens
    async _load() {
      if (!this._hass) return;
      if (this._tab === "plan" && this._layout == null && !this._loadingLayout) {
        this._loadingLayout = true;
        try {
          this._layout = (await this._hass.callWS({ type: "ble_floorplan/get_layout" })).yaml;
        } catch (err) {
          this._note = this._errNote(err);
        }
        this._loadingLayout = false;
        this._render();
      }
      if (["scanners", "trackers", "now"].includes(this._tab) && this._candidates == null && !this._loadingCandidates) {
        this._loadingCandidates = true;
        try {
          this._candidates = await this._hass.callWS({ type: "ble_floorplan/candidates" });
        } catch (err) {
          this._note = this._errNote(err);
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
        if (this._candidates != null || ["scanners", "trackers", "now"].includes(this._tab)) {
          jobs.push(this._hass.callWS({ type: "ble_floorplan/candidates" }).then((r) => { this._candidates = r; }));
        }
        // The timeline fetches the days it shows again, the coverage its map
        this._tl.days = {};
        this._cov.stamp += 1;
        this._ov.key = null;
        this._qList.at = 0;
        this._q.at = 0;
        await Promise.all(jobs);
        this._error = null;
      } catch (err) {
        this._note = this._errNote(err);
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

    // One call of the API, or several one after the other; the (last) result goes
    // to `then`, an error to the page
    async _call(msg, then) {
      this._busy = true;
      this._note = null;
      this._render();
      try {
        let result;
        for (const one of Array.isArray(msg) ? msg : [msg]) result = await this._hass.callWS(one);
        if (then) then(result);
      } catch (err) {
        this._note = this._errNote(err);
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
      return this._tab === "history" && this._tlAllowed && !!this._plan?.rooms.length;
    }

    // ---- Drawing ----

    _render() {
      if (!this._hass) return;
      const plan = this._plan;
      // Drawing is the plan page's way of editing: the draft is there as soon as the plan is
      if (this._tab === "plan" && this._planMode === "draw" && plan && !this._editor.active) this._editor.start(plan);
      if (this._tab === "coverage") this._covLoad();
      if (this._tab === "overview") this._ovLoad();
      const scanner = this._tab === "scanners" && this._selScanner;
      if (scanner) this._sysLoad(this._selScanner);
      if (scanner && this._sView === "quality") {
        if (this._q.open !== this._selScanner) this._q = { open: this._selScanner, data: null, at: 0, loading: false };
        this._qLoad();
      }
      if (["scanners", "quality", "now", "overview"].includes(this._tab)) this._qListLoad();
      const showMap = !NO_MAP.has(this._tab) && !!plan?.rooms.length;
      const showSheet = !this._tlOn;
      const sub = this._subpage;
      const key = [this._tab, !!this._narrow, !!plan, showMap, showSheet, this._tlOn, this._hass.language, sub?.key, sub?.name,
        scanner ? this._sView : ""].join("|");
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

    // Tabs of Home Assistant's own: the pages of an area, the pages of a scanner
    _tabGroup(id, items, active) {
      const t = this._t;
      return `<ha-tab-group id="${id}" class="subtabs">${items
        .map(([key, label]) => `<ha-tab-group-tab slot="nav" panel="${key}"${key === active ? " active" : ""}>${esc(t[label])}</ha-tab-group-tab>`)
        .join("")}</ha-tab-group>`;
    }

    // The parts that stay while the page is open: Home Assistant's frame with the
    // areas as tabs, the pages of the area, map, timeline, sheet, the save button
    _frame(plan, showMap, showSheet, sub) {
      const t = this._t;
      const area = areaOf(this._tab);
      const stage = showMap
        ? `<div class="stage"><div class="map" id="map" tabindex="0" aria-label="${esc(t.mapLabel)}"><div class="maptools" id="maptools"></div><div id="svg"></div>` +
          `<div class="tip"></div></div>${this._tlOn ? this._tlHtml() : ""}</div>`
        : "";
      const sheet = showSheet ? `<div class="sheet" id="sheet"></div>` : "";
      const tabs = sub
        ? (this._tab === "scanners" ? this._tabGroup("views", SCANNER_VIEWS, this._sView) : "")
        : this._tabGroup("subtabs", area[3], this._tab);
      this.shadowRoot.innerHTML = `
        <style>${PLAN_CSS}${EDITOR_CSS}${STYLE}</style>
        <hass-tabs-subpage id="frame">
          ${sub ? `<div slot="header" class="subname">${esc(sub.name)}</div>` : ""}
          <div slot="toolbar-icon" class="actions"><span class="stamp" id="stamp"></span>
            ${iconButton("refresh", t.refresh, 'id="refresh" data-act="refresh"')}
            ${iconButton("cog", t.integrationSettings, 'id="integration" data-act="integration"')}</div>
          <div class="page${this._narrow ? " narrow" : ""}">
            ${tabs}
            <div class="content ${this._tab}${showMap ? " withmap" : ""}${showSheet ? "" : " nosheet"}">${stage}${sheet}</div>
          </div>
          <ha-button slot="fab" id="save" size="l" data-act="save-settings" hidden>${icon("save").replace("<ha-svg-icon", '<ha-svg-icon slot="start"')}${esc(t.save)}</ha-button>
        </hass-tabs-subpage>`;
      const frame = this.shadowRoot.getElementById("frame");
      frame.hass = this._hass;
      frame.tabs = sub ? [] : AREAS.map(([id, ic, label]) => ({ path: `${PANEL_PATH}/${id}`, name: t[label], iconPath: MDI[ic] }));
      frame.mainPage = !sub;
      frame.backCallback = sub ? () => this._act("back", { dataset: {} }) : undefined;
      frame.route = this._route || { prefix: PANEL_PATH, path: `/${area[0]}/${this._tab}` };
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
      if (plan) this._info = planInfo(plan, this._shownPositions(), (s) => this._scannerPos(s), this._offline);
      const map = root.getElementById("map");
      if (map && plan && !this._dragging) {
        map.classList.toggle("aim", this._aiming);
        map.classList.toggle("drawing", this._editing && this._editor.tool !== "select");
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
      // The save button of the settings: only while something is changed
      const fab = root.getElementById("save");
      if (fab) {
        const show = (this._tab === "location" || this._tab === "recording") && this._settingsDirty;
        fab.hidden = !show;
        fab.disabled = this._busy;
        root.getElementById("frame").hasFab = show;
      }
      const stamp = root.getElementById("stamp");
      if (stamp) stamp.textContent = this._stampText();
      root.getElementById("refresh")?.classList.toggle("loading", this._refreshing);
      this._tlFrame();
    }

    // One zoom for every tab: the view stays when the tab changes
    _zoomer() {
      if (!this._zoom) {
        this._zoom = new PlanZoom({
          geom: () => ({ bounds: this._editing ? this._editor.bounds() : this._bounds || computeBounds(this._plan), rot: this._rot }),
          texts: () => this._t,
          wheel: true,
        });
        // While drawing, a drag on a shape or with a drawing tool is the drawing's, not a pan
        this._zoom.skip = (e) => this._editing && this._editor.takes(e);
      }
      return this._zoom;
    }

    _scannerPos(s) {
      return (this._dragPos && this._dragPos[s.key]) || [s.x, s.y];
    }

    // The map takes a tap for a place: a new run's true position, a scanner's new place
    get _aiming() {
      if (this._tab === "measure") return !this._calibration.active && !!this._measure.tracker;
      if (this._tab === "coverage") return this._cov.mode === "model" && this._cov.probes.length < MAX_PROBES;
      return this._tab === "scanners" && this._mode === "move";
    }

    _svg() {
      const plan = this._shownPlan;
      const tab = this._tab;
      let marks = this._editing ? this._editor.overlay() : "";
      if (tab === "measure" || tab === "runs") {
        // Where the runs were taken on this level, coloured by tracker; the next or the running one as a crosshair
        const level = this._level;
        const mine = (r) => levelOfFloor(plan, r.floor ?? plan.floors?.[0]?.key ?? "") === level;
        marks = this._calibration.runs
          .filter((r) => !r.running && mine(r))
          .map((r) => `<circle class="runmark" cx="${r.x}" cy="${r.y}" r="0.16" fill="${trackerColor(plan, r.tracker)}"/>`)
          .join("");
        const active = this._calibration.runs.find((r) => r.id === this._calibration.active);
        if (active && mine(active)) marks += crosshair(active.x, active.y, true);
        else if (this._measure.x != null) marks += crosshair(this._measure.x, this._measure.y, false);
      }
      if (tab === "coverage") marks = this._covMarks() + (this._cursor && this._aiming ? crosshair(this._cursor.x, this._cursor.y, false) : "");
      return planSvg(plan, {
        level: this._level,
        bounds: this._editing ? this._editor.bounds() : this._bounds || computeBounds(plan),
        rot: this._rot,
        labels: this._labels,
        positions: this._shownPositions(),
        offline: this._offline,
        scannerPos: (s) => this._scannerPos(s),
        circles: tab === "trackers" ? this._selTracker : null,
        openTracker: tab === "trackers" ? this._selTracker : tab === "measure" ? this._measure.tracker : null,
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
      return levelSwitch(this._shownPlan, this._level) + iconButton("rotate", t.rotate, 'data-act="rotate"') +
        `<span class="menuwrap">${iconButton("label", t.labels, `data-act="labels"${this._labelMenu ? ' class="on"' : ""}`)}${menu}</span>`;
    }

    // ---- Building blocks, as Home Assistant draws them ----

    // A card of Home Assistant; its title with an (i) when the card has something to explain
    _card(title, body, actions = "", cls = "", help = "") {
      const head = title ? `<h1 class="card-header">${esc(title)}${this._help(help)}</h1>` : "";
      return `<ha-card class="${cls}">${head}<div class="card-content${title ? "" : " top"}">${body}</div>` +
        `${actions ? `<div class="card-actions">${actions}</div>` : ""}</ha-card>`;
    }

    // The (i): Home Assistant's icon button with its tooltip; a tap or Enter shows it, as hovering does
    _help(text) {
      if (!text) return "";
      const id = `help${++this._hid}`;
      return `<ha-icon-button class="help" id="${id}" path="${MDI.info}" label="${esc(this._t.info)}"></ha-icon-button>` +
        `<ha-tooltip for="${id}" placement="top" trigger="hover click">${esc(text)}</ha-tooltip>`;
    }

    // kind: "" (plain), "filled" (the main action), "danger"
    _btn(act, label, { kind = "", disabled = false, data = "" } = {}) {
      const look = kind === "filled" ? "" : kind === "danger" ? ' appearance="plain" variant="danger"' : ' appearance="plain"';
      return `<ha-button${look} data-act="${act}"${data}${disabled || this._busy ? " disabled" : ""}>${esc(label)}</ha-button>`;
    }

    // A field in metres, dB, seconds: a number selector of Home Assistant
    // A number as Home Assistant's text field, written in the number format of the
    // profile: its number field writes a point whatever the language. Typing takes
    // a point or a comma; the form hands numbers on (_hydrate)
    _num(name, label, unit) {
      return { name, label, num: true, selector: { text: unit ? { suffix: unit } : {} } };
    }

    // The name of a scanner or a tracker; the integration takes up to 80 characters
    _nameField(label) {
      return { name: "name", label, required: true, selector: { text: {} } };
    }

    // An ha-form with Home Assistant's selectors; drawn after the sheet's HTML.
    // The data is part of the placeholder, so a change from outside redraws it
    // aria: the name of a field whose label stands beside it (a settings row)
    _formSlot(id, schema, data, onChange, aria = "") {
      const clean = Object.fromEntries(Object.entries(data).filter(([, v]) => v !== null && v !== undefined));
      this._forms[id] = { schema, data: clean, onChange, aria };
      return `<div class="haform" data-form="${esc(id)}" data-v="${esc(JSON.stringify(clean))}"></div>`;
    }

    // The input deep in Home Assistant's field gets the name the row shows beside it
    async _ariaName(form, name, tries = 10) {
      await form.updateComplete;
      const find = (root) => {
        for (const el of root.querySelectorAll("*")) {
          if (el.tagName === "INPUT" || el.getAttribute("role") === "switch") return el;
          const deep = el.shadowRoot && find(el.shadowRoot);
          if (deep) return deep;
        }
        return null;
      };
      const input = form.shadowRoot && find(form.shadowRoot);
      if (input) input.setAttribute("aria-label", name);
      else if (tries > 0) setTimeout(() => this._ariaName(form, name, tries - 1), 100);
    }

    _hydrate(root) {
      for (const slot of root.querySelectorAll("[data-form]")) {
        const spec = this._forms[slot.dataset.form];
        if (!spec) continue;
        const form = document.createElement("ha-form");
        form.hass = this._hass;
        form.schema = spec.schema;
        // Numbers go into the fields as text in the number format, and come back as numbers
        const nums = new Set();
        const walk = (schema) => {
          for (const f of schema) {
            if (f.num) nums.add(f.name);
            if (f.schema) walk(f.schema);
          }
        };
        walk(spec.schema);
        const shown = (d) => Object.fromEntries(Object.entries(d).map(([k, v]) => [k, nums.has(k) && typeof v === "number" ? fieldNumber(this._hass, v) : v]));
        const read = (d) => Object.fromEntries(Object.entries(d).map(([k, v]) => [k, nums.has(k) ? (v === "" || v == null ? null : numOrNull(v)) : v]));
        form.data = shown(spec.data);
        form.computeLabel = (s) => s.label ?? s.name;
        form.computeHelper = (s) => s.helper;
        if (spec.aria) this._ariaName(form, spec.aria);
        form.addEventListener("value-changed", (e) => {
          form.data = e.detail.value;
          spec.onChange(read(e.detail.value));
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

    // One line of state, the why behind its (i), maybe an action
    _alertHelp(kind, text, help, action = "", cls = "") {
      const end = action || help ? `<span slot="action" class="alertact">${action}${this._help(help)}</span>` : "";
      return `<ha-alert alert-type="${kind}"${cls ? ` class="${cls}"` : ""}>${esc(text)}${end}</ha-alert>`;
    }

    // Settings typed but not saved
    get _settingsDirty() {
      const f = this._settings;
      const p = this._plan?.settings;
      if (!f || !p) return false;
      return SETTING_FIELDS.some(([, k]) => (f[k] ?? null) !== (p[k] ?? null));
    }

    // The quality of a scanner from its reception and fidelity: the worst known;
    // good only "so far" while one of them still lacks data
    _qState(q) {
      if (!q?.rate || !q?.fidelity) return "unknown";
      const parts = [q.rate.state, q.fidelity.state];
      const known = parts.filter((x) => x !== "unknown");
      if (!known.length) return "unknown";
      const worst = known.includes("poor") ? "poor" : known.includes("fair") ? "fair" : "good";
      return worst === "good" && known.length < parts.length ? "prelim" : worst;
    }

    _noteHtml() {
      if (!this._note) return "";
      if (this._note.kind === "err") return this._errHtml(this._note);
      return this._alert(this._note.kind === "ok" ? "success" : "info", this._note.text);
    }

    // An error of a call: the note for the page
    _errNote(err) {
      return { kind: "err", ...errorText(this._t, err) };
    }

    // An error: one line by its kind, what Home Assistant said behind the (i)
    _errHtml(e) {
      return this._alertHelp("error", e.text, e.detail ? `${this._t.errDetail}: ${e.detail}` : "");
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
      this._hid = 0;
      if (!this._plan) {
        return this._error ? this._errHtml(this._error) : this._card("", `<div class="muted">…</div>`);
      }
      const page = {
        now: () => this._nowSheet(),
        history: () => this._historySheet(),
        scanners: () => this._scannersSheet(),
        trackers: () => this._trackersSheet(),
        measure: () => this._measureSheet(),
        runs: () => this._runsSheet(),
        tuning: () => this._tuningSheet(),
        coverage: () => this._coverageSheet(),
        quality: () => this._qualityListSheet(),
        overview: () => this._overviewSheet(),
        plan: () => this._planSheet(),
        location: () => this._settingsSheet("location"),
        recording: () => this._settingsSheet("recording"),
      }[this._tab];
      const empty = !this._plan.rooms.length && !["plan", "overview", "location", "recording"].includes(this._tab)
        ? this._alertHelp("info", t.startHere, "", this._btn("go", t.setUp, { data: ' data-key="setup/overview"' }))
        : "";
      return this._noteHtml() + empty + page();
    }

    // The path of a page within the panel, for a link of the sheet
    _rel(page, query = "") {
      return `${areaOf(page)[0]}/${page}${query}`;
    }

    // ---- Live ----

    // What needs a look, then where the trackers are
    _nowSheet() {
      const t = this._t;
      const plan = this._plan;
      if (!plan.rooms.length) return "";
      const hints = [];
      const hint = (path, cls, ic, text) => this._item("go", path, `<span class="icon-bg ${cls}">${icon(ic)}</span>`, text, "");
      const q = this._qList.data || {};
      for (const s of plan.scanners) {
        if (s.paused) continue;
        const where = `?key=${encodeURIComponent(s.key)}`;
        if (this._info.scanners[s.key]?.offline) hints.push(hint(this._rel("scanners", where), "offline", "scanner", t.hOffline.replace("{name}", s.name)));
        else if (this._qState(q[s.key]) === "poor") hints.push(hint(this._rel("scanners", `${where}&view=quality`), "warn", "scanner", t.hPoor.replace("{name}", s.name)));
      }
      const stale = this._calibration.runs.filter((r) => this._runSetup(r).state === "changed").length;
      if (stale) hints.push(hint(this._rel("runs"), "warn", "calibration", t.hStale.replace("{n}", stale)));
      const cand = this._candidates;
      const fresh = (cand?.scanners.length || 0) + (cand?.trackers.length || 0);
      if (fresh) hints.push(hint(this._rel(cand.scanners.length ? "scanners" : "trackers"), "", "plus", t.hNew.replace("{n}", fresh)));
      const notices = this._card(t.hintsTitle, hints.join("") || `<div class="muted pad">${esc(t.hNone)}</div>`, "", "list", t.i_hints);
      return notices + this._card(t.trackers, this._trackerItems(true) || `<div class="muted pad">${esc(t.none)}</div>`, "", "list");
    }

    // The timeline beside the plan; while it is off, the way to turn it on
    _historySheet() {
      const t = this._t;
      if (this._tlAllowed) return "";
      return this._card(t.timeline, this._alertHelp("info", t.histOff, t.h_history_days),
        `<span></span>${this._btn("go", t.turnOn, { kind: "filled", data: ' data-key="setup/recording"' })}`);
    }

    // Drawn or as YAML, one of the two; the choice is locked while changes are unsaved
    _planSheet() {
      const t = this._t;
      const busy = (this._editor.active && this._editor.dirty) || !!this._layoutEdited;
      const mode = (key, label) =>
        `<ha-button appearance="${this._planMode === key ? "filled" : "plain"}" data-act="plan-mode" data-key="${key}"` +
        `${busy && this._planMode !== key ? " disabled" : ""}>${esc(label)}</ha-button>`;
      const switcher = `<div class="planmode">${mode("draw", t.edEdit)}${mode("yaml", "YAML")}` +
        `${busy ? `<span class="muted small">${esc(t.planModeLocked)}</span>` : ""}</div>`;
      if (this._planMode === "draw") return switcher + (this._editor.active ? this._editor.sheet() : "");
      const body = `<textarea class="layout" data-f="layout" spellcheck="false" wrap="off">${esc(this._layout ?? "…")}</textarea>`;
      return switcher + this._card(t.edYaml, body,
        `<span></span>${this._btn("save-layout", t.save, { kind: "filled", disabled: this._layout == null })}`, "", t.layoutHint);
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
      if (cand == null) return "";
      const items = kind === "scanner" ? cand.scanners : cand.trackers;
      if (!items.length) return "";
      const value = (c) => c.id;
      const options = items.map((c) => [value(c), kind === "scanner" ? `${c.name} (${c.source})` : `${c.name}${c.address ? ` (${c.address})` : ""}`]);
      const chosen = this._add[kind] && options.some(([v]) => v === this._add[kind]) ? this._add[kind] : options[0][0];
      this._add[kind] = chosen;
      const pick = { name: "item", label: t.add, required: true, selector: { select: { mode: "dropdown", options: options.map(([v, l]) => ({ value: v, label: l })) } } };
      let schema;
      let data;
      if (kind === "scanner") {
        schema = [pick, this._num("z", t.mountHeight, "m")];
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
      return this._card(title, body,
        `<span>${this._btn("ignore", t.ignore, { data: ` data-key="${esc(chosen)}"` })}</span>${this._btn(`add-${kind}`, t.add, { kind: "filled" })}`);
    }

    // Below the list: that nothing new was found, and the suggestions ignored, folded away
    _ignoredPanel(kind) {
      const t = this._t;
      const cand = this._candidates;
      if (cand == null) return "";
      const fresh = (kind === "scanner" ? cand.scanners : cand.trackers).length;
      const none = fresh ? "" : `<div class="muted pad">${esc(t.noneNew)}</div>`;
      const items = (cand.ignored || []).filter((c) => c.kind === kind);
      if (!items.length) return none;
      const rows = items.map((c) => {
        const addr = c.source || c.address || "";
        const sub = addr && !String(c.name).includes(addr) ? `<div class="muted small">${esc(addr)}</div>` : "";
        return `<tr><td>${esc(c.name)}${sub}</td><td class="n">${this._btn("unignore", t.unignore, { data: ` data-key="${esc(c.id)}"` })}</td></tr>`;
      }).join("");
      return none + `<ha-expansion-panel class="ignored" outlined${this._ignOpen ? " expanded" : ""} header="${esc(`${t.ignoredTitle} · ${items.length}`)}">` +
        `<span slot="icons">${this._help(t.ignoredHint)}</span><table class="data">${rows}</table></ha-expansion-panel>`;
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
          const info = this._info.scanners[x.key];
          const heard = info.trackers.filter((e) => e.d != null).length;
          const floorName = plan.floors?.length ? `${esc(floorOf(plan, x.floor ?? plan.floors[0].key).name || x.floor)} · ` : "";
          if (x.paused) {
            return this._item("sel-scanner", x.key, `<span class="icon-bg paused">${icon("scanner")}</span>`, x.name,
              `${floorName}${esc(t.paused)}`);
          }
          return info.offline
            ? this._item("sel-scanner", x.key, `<span class="icon-bg offline">${icon("scanner")}</span>`, x.name,
              `${floorName}<span class="offline">${esc(t.offline)}</span>`)
            : this._item("sel-scanner", x.key, `<span class="icon-bg">${icon("scanner")}</span>`, x.name,
              `${this._qDot(x.key)}${floorName}${esc(t.hears)} ${esc(t.trackerCount.replace("{n}", heard))}`);
        });
        return this._addCard("scanner") +
          this._card(t.scanners, (items.join("") || `<div class="muted pad">${esc(t.none)}</div>`) + this._ignoredPanel("scanner"), "", "list");
      }
      if (this._sView === "quality") return this._qualityView(s);
      if (this._sView === "system") return this._card("", this._sysHtml(s.key));
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
          ...(plan.floors?.length
            ? [{ name: "floor", label: t.floor, required: true, selector: { select: { mode: "dropdown", options: plan.floors.map((x) => ({ value: x.key, label: x.name || x.key })) } } }]
            : []),
          { type: "grid", name: "", schema: [this._num("x", "x", "m"), this._num("y", "y", "m"), this._num("z", t.mountHeight, "m"), this._num("rssi_offset", t.offset, "dB")] },
        ], f, (v) => {
          for (const k of ["name", "floor", "x", "y", "z", "rssi_offset"]) f[k] = v[k] ?? null;
        });
        actions = `<span></span><span>${this._btn("cancel", t.cancel)}${this._btn("save-scanner", t.save, { kind: "filled" })}</span>`;
      } else if (this._mode === "move") {
        const [x, y] = this._scannerPos(s);
        body = this._alertHelp("info", t.prMove, t.kbd) + this._kv([[t.position, `${fmt(x, 2)} / ${fmt(y, 2)} m`]]);
        actions = `<span></span><span>${this._btn("cancel", t.cancel)}${this._btn("save-move", t.save, { kind: "filled" })}</span>`;
      } else {
        const pairs = plan.trackers.map((tr) => [tr.name, this._pairsText(s.key, tr.key)]).filter(([, v]) => v);
        const kind = this._sysKind(this._sys?.key === s.key ? this._sys.data : null);
        const state = s.paused ? this._alertHelp("info", t.stPaused, t.pausedScannerHint)
          : info.offline ? this._alertHelp("warning", t.stOffline, t.offlineHint) : "";
        body = (kind ? `<div class="kind">${icon("scanner")}<span>${esc(kind)}</span></div>` : "") +
          this._confirmHtml() + state + this._kv([
          [t.position, `${fmt(s.x)} / ${fmt(s.y)} m`],
          [t.mountHeight, `${fmt(s.z)} m`],
          [t.offset, `${s.rssi_offset > 0 ? "+" : ""}${fmt(s.rssi_offset)} dB`],
          [t.pairs, pairs.length ? pairs.map(([n, v]) => `${esc(n)} ${v}`).join(" · ") : esc(t.none)],
        ]) + `<div class="subhead">${esc(t.hears)}</div>${hears}`;
        actions = this._btn("remove-scanner", t.remove, { kind: "danger", disabled: !!this._confirm }) +
          `<span>${this._btn(s.paused ? "resume-scanner" : "pause-scanner", s.paused ? t.resume : t.pause)}` +
          `${this._btn("move", t.move)}${this._btn("edit-scanner", t.edit)}</span>`;
      }
      return this._card("", body, actions);
    }

    // ---- Scanner quality ----

    // The lights of the list: reception and fidelity of every scanner, once a minute
    async _qListLoad() {
      const q = this._qList;
      if (q.loading || Date.now() - q.at < QUALITY_REFETCH_MS) return;
      q.loading = true;
      try {
        q.data = await this._hass.callWS({ type: "ble_floorplan/scanner_quality" });
      } catch {
        q.data = null;
      }
      q.at = Date.now();
      q.loading = false;
      this._render();
    }

    async _qLoad() {
      const q = this._q;
      if (q.loading || (q.data?.key === q.open && Date.now() - q.at < QUALITY_REFETCH_MS)) return;
      q.loading = true;
      const key = q.open;
      try {
        q.data = { key, ...(await this._hass.callWS({ type: "ble_floorplan/scanner_quality", key })) };
      } catch (err) {
        q.data = { key, error: errorText(this._t, err) };
      }
      q.at = Date.now();
      q.loading = false;
      this._render();
    }

    // In the list: the light of the scanner, with its state as text for a screen reader
    _qDot(key) {
      const state = this._qState(this._qList.data?.[key]);
      if (state === "unknown") return "";
      const label = `${this._t.qTitle}: ${this._t["q_" + state]}`;
      return `<span class="qdot ${state}" role="img" aria-label="${esc(label)}" title="${esc(label)}"></span>`;
    }

    // The scanner's page Quality: the three figures, what they say, since when
    _qualityView(s) {
      const q = this._q;
      const t = this._t;
      const fmt = this._fmt;
      const d = q.data?.key === s.key ? q.data : null;
      let body;
      if (!d) body = `<div class="muted">…</div>`;
      else if (d.error) body = this._errHtml(d.error);
      else {
        const tile = (title, state, value, sub) =>
          `<div class="qtile ${state}"><div class="qhead"><span class="qdot ${state}"></span>${esc(title)}</div>` +
          `<div class="qval">${value}</div><div class="qsub">${esc(sub)}</div><div class="qstate">${esc(t["q_" + state])}</div></div>`;
        const r = d.rate;
        const f = d.fidelity;
        const c = d.contribution;
        const pct = (v) => (v == null ? "–" : `${fmt(v * 100, 0)} %`);
        const tiles = tile(t.qRate, r.state, pct(r.value), t.qRateSub.replace("{n}", r.trackers)) +
          tile(t.qFid, f.state, f.spread == null ? "–" : `± ${fmt(f.spread, 1)} m`,
            f.spread == null ? t.qFewMisses.replace("{n}", f.n) : t.qFidSub.replace("{bias}", `${f.bias > 0 ? "+" : ""}${fmt(f.bias, 1)}`).replace("{out}", pct(f.outliers))) +
          tile(t.qPart, c.state, pct(c.share), t.qPartSub.replace("{worse}", c.worse).replace("{cells}", c.cells));
        const shift = (text) => (f.shift
          ? text.replace("{m}", fmt(f.shift.m, 1)).replace("{dx}", `${f.shift.dx > 0 ? "+" : ""}${fmt(f.shift.dx, 1)}`)
            .replace("{dy}", `${f.shift.dy > 0 ? "+" : ""}${fmt(f.shift.dy, 1)}`)
          : text);
        const findings = d.findings.map((code) => {
          const kind = code === "good" ? "success" : code === "few_data" ? "info" : "warning";
          return this._alertHelp(kind, shift(t["f_t_" + code] || code), shift(t["f_" + code] || ""));
        }).join("");
        const state = this._qState(d);
        const since = d.since ? new Date(d.since * 1000).toLocaleString(this._hass.locale?.language || this._hass.language, { dateStyle: "short", timeStyle: "short" }) : "–";
        const hours = d.hours == null ? "–" : fmt(d.hours, 1);
        body = `<div class="qoverall"><span class="qdot ${state}"></span>${esc(t.qTitle)}: ${esc(t["q_" + state])}</div>` +
          `<div class="qtiles">${tiles}</div>${findings}` +
          `<div class="line muted small">${esc(t.qSinceShort.replace("{time}", since).replace("{h}", hours))}` +
          `${this._help(t.qSince.replace("{time}", since).replace("{h}", hours).replace("{max}", this._plan.settings.quality_hours ?? 24))}</div>`;
      }
      const tryShift = d?.fidelity?.shift ? this._btn("quality-try", t.qTry, { kind: "filled" }) : "";
      return this._card("", body, tryShift ? `<span></span>${tryShift}` : "");
    }

    // The system details of the scanner: fetched when its page opens, then every few seconds
    async _sysLoad(key) {
      const sys = this._sys;
      if (this._sysLoading || (sys?.key === key && Date.now() - sys.at < SYSTEM_REFETCH_MS)) return;
      this._sysLoading = true;
      let data = null;
      try {
        data = await this._hass.callWS({ type: "ble_floorplan/scanner_system", key });
      } catch {
        // Secondary: without them the page still shows the scanner
      }
      this._sys = { key, at: Date.now(), data };
      this._sysLoading = false;
      this._render();
    }

    // What the scanner is, as one line: its model, then the integration or the maker
    _sysKind(d) {
      if (!d?.model && !d?.manufacturer) return "";
      const model = d.model && d.model === d.model.toLowerCase() ? d.model.toUpperCase() : d.model;
      return [model, d.integration || d.manufacturer].filter(Boolean).join(" · ");
    }

    // A span of seconds as days, hours and minutes in the language of the page
    _span(seconds) {
      const lang = this._hass.locale?.language || this._hass.language;
      const unit = (n, u) => new Intl.NumberFormat(lang, { style: "unit", unit: u, unitDisplay: "short" }).format(n);
      const s = Math.max(0, Math.round(seconds));
      const d = Math.floor(s / 86400);
      const h = Math.floor((s % 86400) / 3600);
      const m = Math.floor((s % 3600) / 60);
      if (d) return `${unit(d, "day")} ${unit(h, "hour")}`;
      if (h) return `${unit(h, "hour")} ${unit(m, "minute")}`;
      if (m) return unit(m, "minute");
      return unit(s, "second");
    }

    // The system details, folded away below the scanner's own details: secondary on purpose
    _sysHtml(key) {
      const t = this._t;
      const sys = this._sys?.key === key ? this._sys : null;
      const d = sys?.data;
      let body;
      if (!sys) body = `<div class="muted">…</div>`;
      else if (!d) body = `<div class="muted">${esc(t.none)}</div>`;
      else {
        const lang = this._hass.locale?.language || this._hass.language;
        const dash = "–";
        const age = (Date.now() - sys.at) / 1000;
        const rows = [];
        if (d.started) {
          const at = new Date(d.started);
          const when = at.toLocaleString(lang, { dateStyle: "short", timeStyle: "short" });
          rows.push(d.started_live
            ? [t.sysUptime, `${esc(this._span((Date.now() - at.getTime()) / 1000))} <span class="muted">(${esc(when)})</span>`]
            : [t.sysLastStart, `${esc(when)} <span class="muted">(${esc(t.sysUnavailable)})</span>`]);
        }
        if (d.signal != null) rows.push([t.sysSignal, `${this._fmt(d.signal, 0)} dBm`]);
        if (d.temperature != null) {
          rows.push([t.sysTemperature, `${this._fmt(d.temperature, 1)} ${esc(d.temperature_unit || "°C")}`]);
        }
        if (d.firmware) {
          rows.push([t.sysFirmware, esc(d.firmware) +
            (d.firmware_latest ? `<div class="sysnote">${esc(t.sysUpdate.replace("{v}", d.firmware_latest))}</div>` : "")]);
        }
        rows.push([t.sysLastSeen, d.last_seen == null ? esc(t.sysNotInHa) : esc(t.sysAgo.replace("{t}", this._span(d.last_seen + age)))]);
        rows.push([`${t.sysInRange} (${t.sysInRangeHint})`, d.in_range == null ? dash : `${d.in_range}`]);
        if (d.mode) rows.push([t.sysMode, esc(d.mode === "active" ? t.sysActive : d.mode === "passive" ? t.sysPassive : d.mode)]);
        if (d.connectable != null) {
          rows.push([t.sysSlots, !d.connectable ? esc(t.sysReceiveOnly) : d.slots == null ? dash
            : esc(t.sysSlotsUsed.replace("{used}", d.slots - d.slots_free).replace("{n}", d.slots))]);
        }
        if (d.device_id) {
          rows.push([t.sysDevice, this._btn("sys-device", t.sysOpenDevice, { data: ` data-key="${esc(d.device_id)}"` })]);
        }
        body = this._kv(rows);
      }
      return body;
    }

    // The trackers as list items: opened on their page here, a link to it elsewhere
    _trackerItems(link) {
      const t = this._t;
      return this._plan.trackers.map((x) => {
        const info = this._info.trackers[x.key];
        const status = x.paused ? esc(t.paused)
          : info.p ? `${esc(info.room || t.unknown)} · ${esc(t.seenBy.replace("{n}", info.p.scanner_count))}` : esc(t.notSeen);
        const lead = `<span ${x.paused ? `class="icon-bg paused"` : `class="icon-bg" style="background:${info.color}"`}>${icon("tracker")}</span>`;
        return link
          ? this._item("go", this._rel("trackers", `?key=${encodeURIComponent(x.key)}`), lead, x.name, status)
          : this._item("sel-tracker", x.key, lead, x.name, status);
      }).join("");
    }

    _trackersSheet() {
      const t = this._t;
      const fmt = this._fmt;
      const plan = this._plan;
      const tr = plan.trackers.find((x) => x.key === this._selTracker);
      if (!tr) {
        return this._addCard("tracker") +
          this._card(t.trackers, (this._trackerItems(false) || `<div class="muted pad">${esc(t.none)}</div>`) + this._ignoredPanel("tracker"), "", "list");
      }
      const info = this._info.trackers[tr.key];
      const status = tr.paused ? esc(t.paused) : info.p
        ? `${esc(info.room || t.unknown)} · ${fmt(info.p.x)} / ${fmt(info.p.y)} m · ${esc(t.seenBy.replace("{n}", info.p.scanner_count))}`
        : esc(t.notSeen);
      const readings = `<table class="data"><tr><th>${esc(t.scanner)}</th><th class="n">m</th><th class="n">dBm</th></tr>` +
        plan.scanners.map((s) => {
          const r = info.readings[s.key] || {};
          const off = this._info.scanners[s.key].offline;
          const cell = s.paused ? esc(t.paused) : off ? `<span class="offline">${esc(t.offline)}</span>` : r.distance == null ? esc(t.notSeen) : fmt(r.distance);
          return `<tr class="${r.distance == null || !r.used ? "ign" : ""}"><td>${esc(s.name)}</td>` +
            `<td class="n">${cell}</td><td class="n">${r.rssi == null ? "" : fmt(r.rssi, 0)}</td></tr>`;
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
          // Its own range of heights, only where the height counts as a range
          ...(plan.settings.height_uncertainty === false ? [] : [{ type: "grid", name: "", schema: [
            { ...this._num("height_min", t.heightMin, "m"), helper: `${t.default} ${fmt(Math.max((f.height ?? tr.height) - (plan.settings.height_spread ?? 0.4), 0), 2)} m` },
            { ...this._num("height_max", t.heightMax, "m"), helper: `${t.default} ${fmt((f.height ?? tr.height) + (plan.settings.height_spread ?? 0.4), 2)} m` },
          ] }]),
        ], f, (v) => {
          f.name = v.name ?? null;
          f.height = v.height ?? null;
          f.height_min = v.height_min ?? null;
          f.height_max = v.height_max ?? null;
          f.ref_power = v.ref_power ?? null;
        });
        actions = `<span></span><span>${this._btn("cancel", t.cancel)}${this._btn("save-tracker", t.save, { kind: "filled" })}</span>`;
      } else {
        const ref = tr.ref_power == null ? `${esc(t.default)} (${fmt(plan.settings.ref_power_default, 0)} dBm)` : `${fmt(tr.ref_power)} dBm`;
        const pairs = plan.scanners.map((s) => [s.name, this._pairsText(s.key, tr.key)]).filter(([, v]) => v);
        body = this._confirmHtml() + (tr.paused ? this._alertHelp("info", t.stPaused, t.pausedTrackerHint) : "") +
          `<div class="status"><span class="dot" style="background:${tr.paused ? "var(--disabled-text-color, #9e9e9e)" : info.color}"></span>${status}</div>` + this._kv([
          [t.height, `${fmt(tr.height, 2)} m`],
          [t.refPower, ref],
          [t.pairs, pairs.length ? pairs.map(([n, v]) => `${esc(n)} ${v}`).join(" · ") : esc(t.none)],
        ]) + `<div class="subhead">${esc(t.heardBy)}</div>${readings}`;
        actions = this._btn("remove-tracker", t.remove, { kind: "danger", disabled: !!this._confirm }) +
          `<span>${this._btn(tr.paused ? "resume-tracker" : "pause-tracker", tr.paused ? t.resume : t.pause)}` +
          `${this._btn("measure-tracker", t.measure, { disabled: !!tr.paused })}${this._btn("edit-tracker", t.edit)}</span>`;
      }
      return this._card("", body, actions);
    }

    // Measure: the next run or the one going, and where runs are missing
    _measureSheet() {
      const t = this._t;
      const fmt = this._fmt;
      const plan = this._plan;
      const name = (key) => plan.trackers.find((x) => x.key === key)?.name || key;
      const active = this._calibration.runs.find((r) => r.id === this._calibration.active);
      let run;
      if (active) {
        const prog = this._calibration.progress || { elapsed: 0, auto_stop: false, scanners: {} };
        const states = { done: t.stDone, collecting: t.stCollecting, weak: t.stWeak };
        const rows = plan.scanners.filter((s) => !s.paused).map((s) => {
          const p = prog.scanners[s.key];
          const n = p?.count || 0;
          const state = p ? p.state : "none";
          const share = state === "done" ? 100 : Math.min(95, Math.round((n / (prog.target || 30)) * 100));
          return `<tr class="prog ${state}"><td>${esc(s.name)}</td>` +
            `<td><div class="bar ${state}"><i style="width:${share}%"></i></div></td>` +
            `<td class="n">${n}</td><td class="n">${p?.error != null ? `±${fmt(p.error, 1)}` : ""}</td>` +
            `<td class="nowrap">${esc(states[state] || t.stNone)}</td></tr>`;
        }).join("");
        const secs = Math.floor(prog.elapsed);
        const clock = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
        const max = fmt(prog.max_seconds / 60, 0);
        const until = prog.auto_stop
          ? `${esc(t.autoShort.replace("{max}", max))}${this._help(t.autoUntil.replace("{max}", max))}`
          : esc(t.manualUntil);
        run = this._card(`${t.measure} · ${t.elapsed.replace("{t}", clock)}`,
          this._kv([
            [t.tracker, `<span class="dot" style="background:${trackerColor(plan, active.tracker)}"></span>${esc(name(active.tracker))}`],
            [t.runAt, `${fmt(active.x, 2)} / ${fmt(active.y, 2)} m · ${esc(t.height)} ${fmt(active.height, 2)} m`],
          ]) + `<div class="line">${until}</div>` +
          `<div class="scroll"><table class="data progress"><tr><th>${esc(t.scanner)}</th><th>${esc(t.progressCol)}</th>` +
          `<th class="n">${esc(t.samples)}</th><th class="n">dB</th><th></th></tr>${rows}</table></div>`,
          `<span></span>${this._btn("cal-stop", t.stop, { kind: "filled" })}`);
      } else if (!plan.trackers.length) {
        run = this._card(t.newRun, `<div class="muted">${esc(t.none)}</div>`, "", "", t.i_newRun);
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
            { name: "auto", label: t.autoStop, selector: { boolean: {} } },
          ], { tracker: m.tracker, height: m.height, auto: m.auto }, (v) => {
            if (v.tracker !== m.tracker) {
              // Another tracker: its height is the start
              m.tracker = v.tracker;
              m.height = plan.trackers.find((x) => x.key === v.tracker)?.height ?? 1;
              this._redraw = true;
              this._render();
              return;
            }
            m.height = v.height ?? m.height;
            m.auto = !!v.auto;
          }) +
          `<div class="presets"><span class="muted small">${esc(t.heightPresets)}</span><ha-chip-set>` +
          HEIGHT_PRESETS.map(([label, h]) => `<ha-assist-chip data-act="cal-height" data-key="${h}"` +
            ` label="${esc(`${t[label]} ${fmt(h, (h * 10) % 1 ? 2 : 1)} m`)}"></ha-assist-chip>`).join("") +
          `</ha-chip-set></div>` +
          (ready ? this._kv([[t.runAt, `${fmt(m.x, 2)} / ${fmt(m.y, 2)} m`]]) : this._alertHelp("info", t.prMeasure, t.kbd)),
          `<span></span>${this._btn("cal-start", t.start, { kind: "filled", disabled: !ready })}`, "", t.i_newRun);
      }
      return run + this._guideCard();
    }

    // Runs: every run with the scanner setup it was measured with
    _runsSheet() {
      const t = this._t;
      const fmt = this._fmt;
      const plan = this._plan;
      const name = (key) => plan.trackers.find((x) => x.key === key)?.name || key;
      const runs = this._calibration.runs;
      const lang = this._hass.locale?.language || this._hass.language;
      const cols = plan.scanners.map((s) => `<th class="n" title="${esc(s.name)}">${esc(s.name)}</th>`).join("");
      const setups = runs.map((r) => this._runSetup(r));
      const rows = runs.map((r, i) => {
        const counts = plan.scanners.map((s) => `<td class="n">${r.counts?.[s.key] || 0}</td>`).join("");
        const length = r.running ? esc(t.running) : `${Math.round(r.duration)} s`;
        const when = new Date(r.started).toLocaleString(lang, { dateStyle: "short", timeStyle: "short" });
        const setup = setups[i];
        const note = setup.state === "changed" ? `<div class="setup changed">${esc(setup.text)}</div>`
          : setup.state === "unknown" ? `<div class="setup">${esc(t.setupUnknown)}</div>` : "";
        return `<tr class="${r.running ? "live" : setup.state === "changed" ? "stale" : ""}"><td class="nowrap"><span class="dot" style="background:${trackerColor(plan, r.tracker)}"></span>${esc(name(r.tracker))}${note}</td>` +
          `<td class="nowrap">${esc(when)}</td><td class="n">${fmt(r.x)} / ${fmt(r.y)}</td><td class="n">${length}</td>${counts}` +
          `<td>${iconButton("delete", t.delete, `class="small" data-act="cal-delete" data-key="${esc(r.id)}"${this._busy ? " disabled" : ""}`)}</td></tr>`;
      }).join("");
      const table = runs.length
        ? `<div class="scroll"><table class="data runs"><tr><th>${esc(t.tracker)}</th><th>${esc(t.date)}</th><th class="n">x / y</th><th class="n">${esc(t.duration)}</th>${cols}<th></th></tr>${rows}</table></div>`
        : `<div class="muted">${esc(t.noRuns)}</div>`;
      const stale = setups.filter((x) => x.state === "changed").length;
      const unknown = setups.filter((x) => x.state === "unknown").length;
      const count = (text, n) => text.replace("{n}", n).replace("{m}", runs.length);
      const hints = (stale ? this._alertHelp("warning", count(t.staleShort, stale), count(t.staleRuns, stale)) : "") +
        (unknown ? this._alertHelp("info", count(t.unknownShort, unknown), count(t.unknownRuns, unknown)) : "") +
        (this._cal.confirmClear
          ? `<ha-alert alert-type="warning">${esc(t.confirmClear.replace("{n}", runs.length))}` +
            `<ha-button slot="action" appearance="plain" data-act="cal-clear-cancel">${esc(t.cancel)}</ha-button>` +
            `<ha-button slot="action" variant="danger" data-act="cal-clear-ok">${esc(t.clearRuns)}</ha-button></ha-alert>`
          : "");
      return this._card(t.runs, `${hints}${table}`,
        runs.length ? this._btn("cal-clear", t.clearRuns, { kind: "danger", disabled: this._cal.confirmClear }) : "", "", t.calHint);
    }

    // Fine-tuning: offsets and exponent from all runs, the pair corrections by hand
    _tuningSheet() {
      const t = this._t;
      const fmt = this._fmt;
      const plan = this._plan;
      const name = (key) => plan.trackers.find((x) => x.key === key)?.name || key;
      const sname = (key) => plan.scanners.find((x) => x.key === key)?.name || key;
      const runs = this._calibration.runs;
      const active = runs.find((r) => r.id === this._calibration.active);
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
        if (pr.wall_loss) out.push(section(`${t.wallLoss} (dB)`), row(esc(t.perWall), pr.wall_loss));
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
        this._formSlot("fit", [
          { name: "fitN", label: t.fitExponent, selector: { boolean: {} } },
          { name: "fitWalls", label: t.fitWalls, selector: { boolean: {} } },
        ], { fitN: this._cal.fitN, fitWalls: this._cal.fitWalls }, (v) => {
          this._cal.fitN = !!v.fitN;
          this._cal.fitWalls = !!v.fitWalls;
        }) + preview,
        `<span></span><span>${this._btn("cal-solve", t.compute, { disabled: !finished })}` +
        `${pr ? this._btn("cal-apply", t.apply, { kind: "filled", disabled: !!active }) : ""}</span>`, "", t.advancedHint);
      return advanced + this._pairsCard();
    }

    // The pair corrections of every scanner and tracker, in one place
    _pairsCard() {
      const t = this._t;
      const plan = this._plan;
      if (!plan.scanners.length || !plan.trackers.length) return "";
      const fromPlan = (sk) => Object.fromEntries(plan.trackers.map((tr) => [tr.key, plan.pair_offsets?.[sk]?.[tr.key] ?? null]));
      const body = plan.scanners.map((sc) => `<div class="subhead">${esc(sc.name)}</div>` +
        this._formSlot(`pairs-${sc.key}`, [
          { type: "grid", name: "", schema: plan.trackers.map((tr) => this._num(tr.key, tr.name, "dB")) },
        ], this._pairs?.[sc.key] ?? fromPlan(sc.key), (v) => {
          // The first change keeps what the plan has for every other scanner
          if (!this._pairs) this._pairs = Object.fromEntries(plan.scanners.map((x) => [x.key, fromPlan(x.key)]));
          for (const tr of plan.trackers) this._pairs[sc.key][tr.key] = v[tr.key] ?? null;
        })).join("");
      return this._card(t.pairs, body, `<span></span>${this._btn("save-pairs", t.save, { kind: "filled" })}`, "", t.i_pairs);
    }

    // Per room and tracker the runs that fit the scanners as they stand; a room without one stands out
    _guideCard() {
      const t = this._t;
      const plan = this._plan;
      const guide = this._calibration.guide;
      const trackers = plan.trackers.filter((x) => !x.paused && guide?.[x.key]);
      if (!trackers.length || !guide[trackers[0].key].length) return "";
      const rooms = guide[trackers[0].key].map((r) => r.room);
      const head = trackers.map((x) => `<th class="n" title="${esc(x.name)}"><span class="dot" style="background:${trackerColor(plan, x.key)}"></span>${esc(x.name)}</th>`).join("");
      const rows = rooms.map((room, i) => `<tr><td>${esc(room)}</td>` + trackers.map((x) => {
        const n = guide[x.key][i].runs;
        return `<td class="n ${n ? "has" : "missing"}">${n || "–"}</td>`;
      }).join("") + "</tr>").join("");
      const sums = trackers.map((x) => {
        const done = guide[x.key].filter((r) => r.runs > 0).length;
        return `<td class="n small">${esc(t.guideCount.replace("{n}", done).replace("{m}", rooms.length))}</td>`;
      }).join("");
      return this._card(t.guide,
        `<div class="scroll"><table class="data guide"><tr><th>${esc(t.room)}</th>${head}</tr>${rows}<tr class="sum"><td></td>${sums}</tr></table></div>`,
        "", "", t.guideHint);
    }

    // Whether the scanners stand as they did when the run started: same, changed (with what), unknown
    _runSetup(r) {
      const t = this._t;
      if (!r.scanners) return { state: "unknown" };
      const plan = this._plan;
      const parts = [];
      for (const s of plan.scanners) {
        const p = r.scanners[s.key];
        if (!p) parts.push(t.setupAdded.replace("{name}", s.name));
        else if (Math.abs(p[0] - s.x) > 0.05 || Math.abs(p[1] - s.y) > 0.05 || Math.abs(p[2] - s.z) > 0.05) {
          parts.push(t.setupMoved.replace("{name}", s.name));
        }
      }
      for (const key of Object.keys(r.scanners)) {
        if (!plan.scanners.some((s) => s.key === key)) parts.push(t.setupRemoved.replace("{name}", key));
      }
      return parts.length ? { state: "changed", text: parts.join(", ") } : { state: "same" };
    }

    // Positioning or Recording: a settings row per setting, its (i) beside the
    // name; one save button for all, while something is changed
    _settingsSheet(page) {
      const t = this._t;
      const plan = this._plan;
      const f = this._settings || plan.settings;
      const rows = {};
      for (const [sec, key, label, kind, unit] of SETTING_FIELDS) {
        if (RECORDING.has(sec) !== (page === "recording")) continue;
        const field = kind === "bool"
          ? { name: key, label: "", selector: { boolean: {} } }
          : this._num(key, "", unit);
        const slot = this._formSlot(`set-${key}`, [field], { [key]: f[key] }, (v) => {
          this._settings = { ...(this._settings || plan.settings), [key]: v[key] ?? null };
          this._update();
        }, t[label]);
        (rows[sec] ||= []).push(`<ha-settings-row class="${kind}"${this._narrow ? " narrow" : ""} wrap-heading>` +
          `<span slot="heading" class="heading">${esc(t[label])}${this._help(t["h_" + key])}</span>${slot}</ha-settings-row>`);
      }
      // The floor rules only matter for a plan of several levels
      const secs = page === "recording" ? ["timeline", "qualitySec"]
        : ["engine", "motion", "roomRules", ...(levelsOf(plan).length > 1 ? ["floorsSec"] : []), "robust"];
      return secs.map((id) => this._card(t[id], rows[id].join(""), "", "settings")).join("");
    }

    // ---- Analysis: the quality of every scanner ----

    _qualityListSheet() {
      const t = this._t;
      const fmt = this._fmt;
      const data = this._qList.data;
      const active = this._plan.scanners.filter((x) => !x.paused);
      let body;
      if (!active.length) body = `<div class="muted">${esc(t.none)}</div>`;
      else if (!data) body = `<div class="muted">…</div>`;
      else {
        const cell = (part, text) => `<td class="n nowrap"><span class="qdot ${part?.state || "unknown"}"></span>${text}</td>`;
        const rows = active.map((sc) => {
          const q = data[sc.key];
          const state = this._qState(q);
          const r = q?.rate;
          const f = q?.fidelity;
          const path = this._rel("scanners", `?key=${encodeURIComponent(sc.key)}&view=quality`);
          return `<tr class="link" role="button" tabindex="0" data-act="go" data-key="${esc(path)}"><td>${esc(sc.name)}</td>` +
            cell(r, r?.value == null ? "–" : `${fmt(r.value * 100, 0)} %`) +
            cell(f, f?.spread == null ? "–" : `± ${fmt(f.spread, 1)} m`) +
            `<td class="nowrap"><span class="qdot ${state}"></span>${esc(t["q_" + state])}</td></tr>`;
        }).join("");
        body = `<div class="scroll"><table class="data qlist"><tr><th>${esc(t.scanner)}</th><th class="n">${esc(t.qRate)}</th>` +
          `<th class="n">${esc(t.qFid)}</th><th>${esc(t.qState)}</th></tr>${rows}</table></div>`;
      }
      return this._card(t.qualitySec, body, "", "", t.i_quality);
    }

    // ---- Setup: the steps in their order ----

    // The share of the area good in the coverage model, for the last step
    async _ovLoad() {
      const o = this._ov;
      const plan = this._plan;
      if (!plan || o.loading || !plan.rooms.length || !plan.scanners.length) return;
      const key = JSON.stringify([this._level, plan.scanners, plan.trackers, plan.settings, plan.pair_offsets, plan.rooms]);
      if (key === o.key) return;
      o.loading = true;
      try {
        const d = await this._hass.callWS({ type: "ble_floorplan/coverage/model", level: this._level });
        o.data = d.cells.length ? Math.round((100 * d.cells.filter((c) => c[2] === 2).length) / d.cells.length) : null;
      } catch {
        o.data = null;
      }
      o.key = key;
      o.loading = false;
      this._render();
    }

    _overviewSheet() {
      const t = this._t;
      const plan = this._plan;
      const rooms = plan.rooms.filter((r) => !r.zone).length;
      const active = plan.scanners.filter((x) => !x.paused);
      const off = active.filter((x) => this._info.scanners[x.key]?.offline).length;
      const unseen = plan.trackers.filter((x) => !x.paused && !this._info.trackers[x.key]?.p).length;
      const guide = this._calibration.guide || {};
      const trs = plan.trackers.filter((x) => !x.paused && guide[x.key]?.length);
      const names = trs.length ? guide[trs[0].key].map((r) => r.room) : [];
      const measured = names.filter((_, i) => trs.some((x) => guide[x.key][i]?.runs > 0)).length;
      const stale = this._calibration.runs.filter((r) => this._runSetup(r).state === "changed").length;
      const good = plan.scanners.length && rooms ? this._ov.data : null;
      const steps = [
        ["plan", t.stepPlan, rooms > 0, t.sPlan.replace("{rooms}", rooms).replace("{floors}", plan.floors?.length || 1)],
        ["scanners", t.stepScanners, active.length >= MIN_SCANNERS, t.sScanners.replace("{n}", active.length).replace("{off}", off)],
        ["trackers", t.stepTrackers, plan.trackers.length > 0, t.sTrackers.replace("{n}", plan.trackers.length).replace("{unseen}", unseen)],
        ["measure", t.stepCal, names.length > 0 && measured === names.length && !stale,
          t.sCal.replace("{n}", measured).replace("{m}", names.length) + (stale ? t.sCalStale.replace("{k}", stale) : "")],
        ["coverage", t.stepCov, good != null && good >= COVERAGE_DONE, good == null ? t.sOpen : t.sCov.replace("{good}", good)],
      ];
      const next = steps.find((x) => !x[2]);
      const items = steps.map(([page, title, done, sub], i) => this._item("go", this._rel(page),
        `<span class="icon-bg step${done ? " done" : ""}">${done ? icon("check") : `<b>${i + 1}</b>`}</span>`, title, esc(sub))).join("");
      const actions = next ? `<span></span>${this._btn("go", t.next, { kind: "filled", data: ` data-key="${esc(this._rel(next[0]))}"` })}` : "";
      return this._card(t.setupTitle, items, actions, "list", t.i_setup) + `<div class="about">${esc(this._aboutText())}</div>`;
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
      if (c.mode === "measured") return JSON.stringify(["measured", tracker, this._level, c.stamp, Math.floor(Date.now() / MEASURED_REFETCH_MS)]);
      return JSON.stringify(["model", tracker, this._level, c.probes, c.stamp, plan.scanners, plan.trackers, plan.settings, plan.pair_offsets, plan.rooms]);
    }

    async _covLoad() {
      const c = this._cov;
      if (!this._plan || c.loading) return;
      if (c.tracker !== ANY && !this._plan.trackers.some((x) => x.key === c.tracker)) c.tracker = ANY;
      const key = this._covKey();
      if (key === c.key) return;
      c.loading = true;
      const msg = { type: `ble_floorplan/coverage/${c.mode}`, level: this._level };
      if (c.tracker !== ANY) msg.tracker = c.tracker;
      if (c.mode === "model") msg.probes = c.probes;
      try {
        c.data = { mode: c.mode, ...(await this._hass.callWS(msg)) };
      } catch (err) {
        c.data = null;
        this._note = this._errNote(err);
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
        ? t.covModelHint.replace("{rssi}", fmt(d?.good_rssi ?? -85, 0))
        : t.i_measured;
      let summary = "";
      if (d && d.mode === "model" && d.cells.length) {
        const n = [0, 0, 0];
        for (const cell of d.cells) n[cell[2]] += 1;
        const pct = (k) => Math.round((100 * n[k]) / d.cells.length);
        summary = `<div class="subhead">${esc(t.covSummary.replace("{good}", pct(2)).replace("{fair}", pct(1)).replace("{poor}", pct(0)))}</div>`;
      }
      const main = this._card(t.coverage, form + summary + legend, "", "", hint);
      return main + (c.mode === "model" ? this._probesCard(d) : this._measuredCard(d)) + this._covRoomsCard(d);
    }

    _probesCard(d) {
      const t = this._t;
      const fmt = this._fmt;
      const c = this._cov;
      const rows = c.probes.map((p, i) =>
        `<tr><td>P${i + 1}</td><td class="n">${fmt(p.x, 2)} / ${fmt(p.y, 2)} m</td>` +
        `<td>${iconButton("delete", t.remove, `class="small" data-act="cov-probe-del" data-key="${i}"`)}</td></tr>`).join("");
      const body = (c.probes.length < MAX_PROBES ? this._alertHelp("info", t.prProbe.replace("{n}", MAX_PROBES - c.probes.length), t.kbdProbe) : "") +
        (rows ? `<table class="data"><tr><th></th><th class="n">x / y</th><th></th></tr>${rows}</table>` : "");
      const help = t.probeHint + (d ? ` ${t.probeOffset.replace("{offset}", fmt(d.probe_offset, 1))}` : "");
      return this._card(t.probes, body, c.probes.length ? `<span></span>${this._btn("cov-probes-clear", t.removeAll)}` : "", "", help);
    }

    _measuredCard(d) {
      const t = this._t;
      const c = this._cov;
      let body = "";
      if (d && !d.recording) body += this._alertHelp("info", t.recOff, t.covOff);
      if (d) {
        body += d.days.length
          ? `<div>${esc(t.covDays.replace("{n}", d.days.length).replace("{first}", new Date(`${d.days[0]}T00:00:00Z`).toLocaleDateString(this._hass.language)))}</div>`
          : `<div class="muted">${esc(t.covNone)}</div>`;
        if (d.change) {
          const lang = this._hass.locale?.language || this._hass.language;
          const date = new Date(d.change.at * 1000).toLocaleString(lang, { dateStyle: "short", timeStyle: "short" });
          const reason = d.change.reason === "scanners" ? t.covReasonScanners : t.covReasonCalibration;
          const fill = (text) => text.replace("{n}", d.change.days.length).replace("{m}", d.days.length).replace("{date}", date).replace("{reason}", reason);
          body += this._alertHelp("warning", fill(t.covStaleShort), fill(t.covStale),
            c.confirm ? "" : `<ha-button appearance="plain" data-act="cov-reset">${esc(t.covReset)}</ha-button>`, "covstale");
        }
      } else {
        body += `<div class="muted">…</div>`;
      }
      if (c.confirm) {
        body += `<ha-alert alert-type="warning">${esc(t.covResetAsk)}` +
          `<ha-button slot="action" appearance="plain" data-act="cov-reset-cancel">${esc(t.cancel)}</ha-button>` +
          `<ha-button slot="action" variant="danger" data-act="cov-reset-ok">${esc(t.covReset)}</ha-button></ha-alert>`;
      }
      const actions = d && !d.recording ? `<span></span>${this._btn("go", t.turnOn, { data: ' data-key="setup/recording"' })}` : "";
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
        const word = { 2: t.covG, 1: t.covF, 0: t.covP };
        head = `<tr><th>${esc(t.room)}</th>${[2, 1, 0].map((l) => `<th class="n">${this._covSwatch(l)}${esc(word[l])}</th>`).join("")}</tr>`;
        rows = rooms.map((r) => `<tr><td>${esc(r.name)}</td>${[2, 1, 0].map((l) => `<td class="n">${r.p[l]} %</td>`).join("")}</tr>`).join("");
      } else {
        const rooms = [...d.rooms].sort((a, b) => a.level - b.level);
        head = `<tr><th>${esc(t.room)}</th><th>${esc(t.covLevel)}</th><th class="n">${esc(t.covGoodScanners)}</th><th class="n">${esc(t.covTime)}</th></tr>`;
        rows = rooms.map((r) => {
          const lvl = r.level >= 1.5 ? 2 : r.level >= 0.5 ? 1 : 0;
          return `<tr><td>${esc(r.name)}</td><td class="nowrap">${this._covSwatch(lvl)}${esc([t.covP, t.covF, t.covG][lvl])}</td><td class="n">${fmt(r.good, 1)}</td><td class="n">${this._covTime(r.seconds)}</td></tr>`;
        }).join("");
      }
      return this._card(t.covRooms, `<div class="scroll"><table class="data">${head}${rows}</table></div>`);
    }

    // ---- Input ----

    // One listener each on the shadow root: the content under it is redrawn
    _bindOnce() {
      const root = this.shadowRoot;
      root.addEventListener("click", (e) => {
        const act = e.target.closest?.("[data-act]");
        if (act) {
          if (!act.disabled) this._act(act.dataset.act, act);
          return;
        }
        if (e.target.closest?.("#map")) this._mapClick(e);
      });
      // A list item or a row that opens a page does so with Enter or Space, as a button would
      root.addEventListener("keydown", (e) => {
        if (e.target?.id === "map" && this._mapKey(e)) {
          e.preventDefault();
          return;
        }
        const item = e.target.closest?.(".item[data-act], tr[data-act]");
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
      root.addEventListener("pointerdown", (e) => {
        if (this._editing && e.target.closest?.("#map")) {
          if (this._editor.pointerDown(e)) return;
        }
        this._dragStart(e);
      });
      // The ignored suggestions stay unfolded while the list is redrawn
      root.addEventListener("expanded-changed", (e) => {
        if (!e.target.classList?.contains("ignored") || e.detail.expanded === this._ignOpen) return;
        this._ignOpen = e.detail.expanded;
        // The sheet as it is now, so the open panel is not drawn anew
        this._forms = {};
        this._sheetHtml = this._sheet();
      });
      // Home Assistant's tabs: a page of the area, a page of the scanner
      root.addEventListener("wa-tab-show", (e) => {
        const name = e.detail?.name;
        const group = e.target?.id;
        if (!name) return;
        if (group === "subtabs" && name !== this._tab) this._go(name);
        else if (group === "views" && name !== this._sView && this._selScanner) {
          this._sView = name;
          this._mode = null;
          this._form = null;
          this._confirm = null;
          this._dragPos = null;
          const view = name === "overview" ? "" : `&view=${name}`;
          window.history.replaceState(null, "", `${pagePath("scanners")}?key=${encodeURIComponent(this._selScanner)}${view}`);
          this._href = window.location.pathname + window.location.search;
          this._render();
        }
      });
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
      if (!plan || e.target.closest?.(".maptools") || this._editing) return;
      if (this._aiming) {
        const [x, y] = toPlan(this.shadowRoot, e, this._bounds);
        if (this._tab === "measure") {
          this._measure.x = snap(x);
          this._measure.y = snap(y);
          this._measure.floor = floorAt(plan, this._level, x, y);
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
        if (kind === "scanners") {
          this._selScanner = this._selScanner === key ? null : key;
          this._sView = "overview";
        }
        else this._selTracker = this._selTracker === key ? null : key;
        this._render();
      } else if (this._tab === "measure" && kind === "trackers" && !this._calibration.active) {
        this._measure.tracker = key;
        this._measure.height = plan.trackers.find((x) => x.key === key)?.height ?? 1;
        this._render();
      } else if (this._tab !== "measure" && this._tab !== "history") {
        navigate(`${pagePath(kind)}?key=${encodeURIComponent(key)}`);
      }
    }

    // The plan with the keyboard, where a point is to be placed: the arrow keys move
    // it the way they point on the screen, also on a rotated plan, 10 cm a press or
    // 1 m with Shift; on the coverage they move a cross and Enter places the test scanner
    _mapKey(e) {
      const plan = this._plan;
      if (!plan || !this._aiming || e.altKey || e.ctrlKey || e.metaKey) return false;
      const B = this._bounds || computeBounds(plan);
      const sc = this._tab === "scanners" ? plan.scanners.find((x) => x.key === this._selScanner) : null;
      const from = () => {
        if (this._tab === "measure" && this._measure.x != null) return [this._measure.x, this._measure.y];
        if (sc) return this._scannerPos(sc);
        if (this._tab === "coverage" && this._cursor) return [this._cursor.x, this._cursor.y];
        return [B.w / 2, B.h / 2];
      };
      if (e.key === "Enter" || e.key === " ") {
        if (this._tab !== "coverage") return false;
        const [x, y] = from();
        this._cov.probes = [...this._cov.probes, { x: snap(x), y: snap(y) }];
        this._cursor = null;
        this._render();
        return true;
      }
      const dir = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
      if (!dir) return false;
      let [dx, dy] = dir;
      const m = this.shadowRoot.getElementById("plan")?.getScreenCTM()?.inverse();
      if (m) {
        const px = m.a * dir[0] + m.c * dir[1];
        const py = m.b * dir[0] + m.d * dir[1];
        const len = Math.hypot(px, py) || 1;
        dx = px / len;
        dy = py / len;
      }
      const step = e.shiftKey ? 1 : 0.1;
      const [x0, y0] = from();
      const x = snap(Math.min(Math.max(x0 + dx * step, 0), B.w));
      const y = snap(Math.min(Math.max(y0 + dy * step, 0), B.h));
      if (this._tab === "measure") {
        this._measure.x = x;
        this._measure.y = y;
        this._measure.floor = floorAt(plan, this._level, x, y);
      } else if (sc) this._dragPos = { [sc.key]: [x, y] };
      else this._cursor = { x, y };
      this._render();
      return true;
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
      if (act.startsWith("ed-") && this._editor.active && this._editor.act(act, key)) {
        this._redraw = true;
        this._render();
        return;
      }
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
        case "level":
          this._levelKept = Number(key);
          keep(LEVEL_KEY, key);
          // A chosen point belongs to the level it was chosen on
          this._measure.x = this._measure.y = null;
          this._cov.probes = [];
          break;
        case "rotate":
          this._rot = (this._rot + 90) % 360;
          keep(ROT_KEY, String(this._rot));
          if (this._zoom) this._zoom.view = null;
          break;
        case "labels":
          this._labelMenu = !this._labelMenu;
          break;
        case "go":
          navigate(`${PANEL_PATH}/${key}`);
          return;
        case "back":
          if (this._tab === "scanners") this._selScanner = null;
          else this._selTracker = null;
          this._sView = "overview";
          this._form = null;
          this._mode = null;
          this._dragPos = null;
          this._note = null;
          this._confirm = null;
          if (window.location.search) window.history.replaceState(null, "", pagePath(this._tab));
          this._href = window.location.pathname + window.location.search;
          break;
        case "sys-device":
          navigate(`/config/devices/device/${key}`);
          return;
        case "sel-scanner":
          this._selScanner = key;
          this._sView = "overview";
          this._note = null;
          this._showLevelOf("scanners", key);
          break;
        case "sel-tracker":
          this._selTracker = key;
          this._note = null;
          this._showLevelOf("trackers", key);
          break;
        case "cancel":
          this._form = null;
          this._mode = null;
          this._dragPos = null;
          break;
        case "plan-mode":
          this._planMode = key;
          try {
            window.localStorage.setItem(PLAN_MODE_KEY, key);
          } catch {
            // no storage
          }
          if (key === "yaml") this._editor.stop();
          this._note = null;
          break;
        case "ed-save":
          this._call({ type: "ble_floorplan/set_layout", layout: this._editor.layout() }, (result) => {
            // Drawing goes on from what was saved
            this._plan = result.floorplan;
            this._bounds = computeBounds(this._plan);
            this._editor.start(this._plan);
            this._layout = result.yaml;
            this._layoutEdited = false;
            this._note = { kind: "ok", text: t.planSaved };
          });
          return;
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
        case "quality-try": {
          // Look at the place the misses suggest: the scanner there, to save or to cancel
          const sh = this._q.data?.fidelity?.shift;
          const sc = plan.scanners.find((x) => x.key === this._selScanner);
          if (sh && sc) {
            this._sView = "overview";
            this._mode = "move";
            this._dragPos = { [sc.key]: [snap(sc.x + sh.dx), snap(sc.y + sh.dy)] };
            this._note = null;
            window.history.replaceState(null, "", `${pagePath("scanners")}?key=${encodeURIComponent(sc.key)}`);
            this._href = window.location.pathname + window.location.search;
          }
          break;
        }
        case "ignore":
        case "unignore":
          this._call({ type: "ble_floorplan/ignore", item: key, ignored: act === "ignore" }, (result) => {
            this._candidates = result;
          });
          return;
        case "edit-scanner": {
          const s = plan.scanners.find((x) => x.key === this._selScanner);
          const pairs = {};
          for (const tr of plan.trackers) pairs[tr.key] = plan.pair_offsets?.[s.key]?.[tr.key] ?? null;
          this._form = { name: s.name, floor: s.floor ?? plan.floors?.[0]?.key ?? null, x: s.x, y: s.y, z: s.z, rssi_offset: s.rssi_offset, pairs };
          this._note = null;
          break;
        }
        case "pause-scanner":
        case "resume-scanner":
        case "pause-tracker":
        case "resume-tracker": {
          const [what, kind] = act.split("-");
          const sel = kind === "scanner" ? this._selScanner : this._selTracker;
          this._call({ type: `ble_floorplan/set_${kind}`, key: sel, paused: what === "pause" }, () => {
            this._note = { kind: "ok", text: what === "pause" ? t.pausedNote : t.resumedNote };
          });
          return;
        }
        case "save-scanner": {
          const s = plan.scanners.find((x) => x.key === this._selScanner);
          const f = this._form;
          const msg = {
            type: "ble_floorplan/set_scanner", key: s.key, name: (f.name ?? "").trim() || s.name,
            x: f.x ?? s.x, y: f.y ?? s.y, z: f.z ?? s.z,
            rssi_offset: f.rssi_offset ?? s.rssi_offset, pair_offsets: f.pairs,
          };
          if (f.floor) msg.floor = f.floor;
          this._call(msg, () => {
            saved();
            // Moved to another floor: show it there
            if (f.floor) this._levelKept = levelOfFloor(plan, f.floor);
          });
          return;
        }
        case "edit-tracker": {
          const tr = plan.trackers.find((x) => x.key === this._selTracker);
          const pairs = {};
          for (const s of plan.scanners) pairs[s.key] = plan.pair_offsets?.[s.key]?.[tr.key] ?? null;
          this._form = { name: tr.name, height: tr.height, height_min: tr.height_min ?? null, height_max: tr.height_max ?? null, ref_power: tr.ref_power ?? null, pairs };
          this._note = null;
          break;
        }
        case "save-tracker": {
          const tr = plan.trackers.find((x) => x.key === this._selTracker);
          const f = this._form;
          this._call({
            type: "ble_floorplan/set_tracker", key: tr.key, name: (f.name ?? "").trim() || tr.name,
            height: f.height ?? tr.height, height_min: f.height_min, height_max: f.height_max,
            ref_power: f.ref_power, pair_offsets: f.pairs,
          }, saved);
          return;
        }
        case "measure-tracker": {
          const tr = plan.trackers.find((x) => x.key === this._selTracker);
          this._measure = { tracker: tr.key, height: tr.height, x: null, y: null, auto: this._measure.auto };
          this._go("measure");
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
          // The choice is the suggestion's id: scanner:<source>
          const source = (this._candidates?.scanners || []).find((x) => x.id === this._add.scanner)?.source;
          this._call({ type: "ble_floorplan/add_scanner", source, z: this._add.z ?? 1 }, (result) => {
            this._candidates = null;
            this._add = {};
            // A new scanner lands in the middle: straight on to its place
            this._selScanner = result.key;
            this._sView = "overview";
            this._mode = "move";
            this._dragPos = {};
            this._load();
          });
          return;
        case "add-tracker": {
          const value = this._add.tracker;
          const c = (this._candidates?.trackers || []).find((x) => x.id === value);
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
          const start = { type: "ble_floorplan/calibration/start", tracker: m.tracker, x: m.x, y: m.y, height: m.height, auto_stop: !!m.auto };
          if (m.floor) start.floor = m.floor;
          this._call(start, () => {
            this._measure = { ...m, x: null, y: null };
          });
          return;
        }
        case "cal-height":
          this._measure.height = Number(key);
          this._redraw = true;
          this._render();
          return;
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
        case "cal-clear":
          this._cal.confirmClear = true;
          this._render();
          return;
        case "cal-clear-cancel":
          this._cal.confirmClear = false;
          this._render();
          return;
        case "cal-clear-ok":
          this._cal.confirmClear = false;
          this._cal.proposal = null;
          this._call({ type: "ble_floorplan/calibration/clear" }, () => {
            this._note = { kind: "ok", text: this._t.cleared };
          });
          return;
        case "cal-delete":
          this._call({ type: "ble_floorplan/calibration/delete", run_id: key }, (result) => {
            if (result.fit) this._note = this._fitNote(result.fit);
          });
          return;
        case "cal-solve":
          this._call({ type: "ble_floorplan/calibration/solve", attenuation: this._cal.fitN, walls: this._cal.fitWalls }, (result) => {
            this._cal.proposal = result;
          });
          return;
        case "cal-apply": {
          const pr = this._cal.proposal;
          const msg = { type: "ble_floorplan/calibration/apply", trackers: {}, scanners: {}, pairs: {} };
          if (pr.attenuation) msg.attenuation = pr.attenuation.new;
          if (pr.wall_loss) msg.wall_loss = pr.wall_loss.new;
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
        case "save-pairs": {
          // Every scanner whose corrections changed, one after the other
          const pairs = this._pairs;
          if (!pairs) return;
          const changed = plan.scanners.filter((sc) => plan.trackers.some((tr) =>
            (pairs[sc.key]?.[tr.key] ?? null) !== (plan.pair_offsets?.[sc.key]?.[tr.key] ?? null)));
          this._call(changed.map((sc) => ({ type: "ble_floorplan/set_scanner", key: sc.key, pair_offsets: pairs[sc.key] })), () => {
            this._pairs = null;
            this._note = { kind: "ok", text: t.saved };
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
        const near = f < 0.5 ? p : q;
        return { x: p[1] + (q[1] - p[1]) * f, y: p[2] + (q[2] - p[2]) * f, room: near[3], level: near[4] ?? 0 };
      }
      return { x: p[1], y: p[2], room: p[3], level: p[4] ?? 0 };
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
            // A point on another level breaks the trail like a gap
            if (pts[j][1] == null || (pts[j][4] ?? 0) !== this._level) {
              if (line.length > 1) lines.push(line);
              line = [];
            } else line.push([pts[j][1], pts[j][2]]);
          }
          const now = this._tlAt(tr.key, t1);
          if (now && line.length && now.level === this._level) line.push([now.x, now.y]);
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
          <ha-button size="s" appearance="plain" id="tllive">${esc(t.backToLive)}</ha-button>
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
        play.label = tl.playing ? t.tlPause : t.play;
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
  // draws what Home Assistant has no element for (lists, tables, the timeline),
  // in the colours and sizes of the active theme
  const STYLE = `
    /* The panel's own container has no height of its own: the page takes the window */
    :host { display: block; height: 100vh; height: 100dvh; background: var(--primary-background-color); color: var(--primary-text-color);
      font-family: var(--ha-font-family-body, Roboto, Noto, sans-serif); font-size: var(--ha-font-size-m, 14px); line-height: 1.5;
      -webkit-font-smoothing: antialiased; }
    * { box-sizing: border-box; }
    /* Home Assistant's frame for pages with tabs: the areas in the header, at the bottom on a phone */
    hass-tabs-subpage { height: 100%; }
    .subname { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    /* The header's actions: when the page last got its data, refresh, the integration */
    .actions { display: flex; align-items: center; }
    .stamp { color: var(--secondary-text-color); font-size: var(--ha-font-size-m, 14px);
      white-space: nowrap; align-self: center; margin-inline-end: 4px; }
    #refresh.loading { animation: spin 1s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    @media (max-width: 600px) { .stamp { display: none; } }
    /* Below the header: the pages of the area as Home Assistant's tabs, then plan and sheet */
    .page { display: flex; flex-direction: column; height: 100%; }
    .subtabs { flex: none; padding: 0 16px; }
    .narrow .subtabs { padding: 0 4px; }
    .content { flex: 1 1 auto; min-height: 0; display: flex; }
    .stage { flex: 1 1 auto; min-width: 0; display: flex; gap: 12px; padding: 16px; }
    .map:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
    .map { flex: 1 1 auto; height: 100%; display: flex; flex-direction: column; padding: 4px 8px 12px; background: var(--card-background-color);
      border-radius: var(--ha-card-border-radius, 12px); border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color)); }
    #svg { flex: 1 1 auto; min-height: 0; }
    .maptools { display: flex; justify-content: flex-end; align-items: flex-start; flex: none; }
    .maptools .levels { position: static; flex-direction: row; flex-wrap: wrap; margin-right: auto; box-shadow: none;
      background: color-mix(in srgb, var(--primary-text-color) 5%, transparent); }
    .menuwrap { position: relative; }
    .sheet { flex: 0 0 min(420px, 45%); overflow-y: auto; padding: 16px 16px 0 0; }
    .content:not(.withmap) .sheet { flex: 1 1 auto; padding: 16px 16px 0; }
    .content:not(.withmap) .sheet > * { max-width: 720px; margin-left: auto; margin-right: auto; }
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
    /* The title of a card as Home Assistant draws it, with room for the (i) at its end */
    .card-header { display: flex; align-items: center; gap: 4px; margin: 0; padding: 12px 8px 12px 16px;
      color: var(--ha-card-header-color, var(--primary-text-color)); font-family: var(--ha-card-header-font-family, inherit);
      font-size: var(--ha-card-header-font-size, var(--ha-font-size-2xl, 24px)); font-weight: var(--ha-font-weight-normal, 400);
      line-height: var(--ha-line-height-condensed, 1.2); letter-spacing: -0.012em; min-height: 48px; }
    .card-header ha-icon-button.help { margin-inline-start: auto; }
    ha-icon-button.help { --mdc-icon-button-size: 32px; --mdc-icon-size: 18px; --ha-icon-button-size: 32px; color: var(--secondary-text-color); flex: none; }
    ha-tooltip { --max-width: min(360px, 90vw); }
    .alertact { display: flex; align-items: center; gap: 4px; }
    .line { display: flex; align-items: center; gap: 4px; margin: 8px 0; color: var(--secondary-text-color); }
    .pad { padding: 8px 16px; }
    /* Settings: Home Assistant's rows, the field at the end, below the name on a phone */
    ha-card.settings .card-content { padding: 0 0 8px; }
    ha-settings-row { --settings-row-content-width: 100%; }
    ha-settings-row + ha-settings-row:not([narrow]) { border-top: 1px solid var(--divider-color); }
    ha-settings-row .heading { display: inline-flex; align-items: center; gap: 2px; }
    ha-settings-row.num .haform { width: 180px; max-width: 100%; }
    ha-settings-row[narrow] .haform { width: 100%; }
    ha-settings-row.bool .haform { width: auto; }
    ha-expansion-panel.ignored { display: block; margin: 8px 16px 0; --expansion-panel-summary-padding: 0 8px 0 16px; }
    .icon-bg.warn { background: var(--warning-color); color: var(--text-primary-color, #fff); }
    .icon-bg.step { width: 36px; height: 36px; justify-content: center; align-items: center; padding: 0;
      background: var(--secondary-background-color); color: var(--primary-text-color); }
    .icon-bg.step.done { background: var(--success-color, #43a047); color: var(--text-primary-color, #fff); }
    tr.link { cursor: pointer; }
    tr.link:hover td, tr.link:focus-visible td { background: var(--secondary-background-color); }
    .qoverall { display: flex; align-items: center; margin-bottom: 12px; font-weight: var(--ha-font-weight-medium, 500); }
    .narrow ha-card { margin-bottom: 8px; }
    .card-content { padding: 0 16px 16px; }
    .card-content.top { padding-top: 16px; }
    ha-card.list .card-content { padding: 0 0 8px; }
    /* Left the destructive action, right the others; too narrow, the right group goes
       to a line of its own, aligned right, before its buttons wrap among themselves */
    .card-actions { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 4px 8px; padding: 8px;
      border-top: 1px solid var(--divider-color); }
    .card-actions > span { display: flex; gap: 4px 8px; flex-wrap: wrap; justify-content: flex-end; }
    .card-actions > :last-child { flex: 0 0 auto; max-width: 100%; margin-left: auto; }
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
    .icon-bg.paused { background: var(--disabled-text-color, #9e9e9e); color: var(--text-primary-color, #fff); }
    .icon-bg.offline { background: var(--error-color); color: var(--text-primary-color, #fff); }
    .offline { color: var(--error-color); }
    .text { display: flex; flex: 1; flex-direction: column; min-width: 0; }
    .headline { font-size: var(--ha-font-size-l, 16px); line-height: 24px; }
    .supporting { font-size: var(--ha-font-size-m, 14px); line-height: 20px; color: var(--secondary-text-color); }
    .next { color: var(--secondary-text-color); }
    .muted { color: var(--secondary-text-color); }
    .small { font-size: var(--ha-font-size-s, 12px); line-height: 16px; margin-top: 8px; }
    .status { display: flex; align-items: center; color: var(--secondary-text-color); margin-bottom: 8px; }
    .subhead { margin: 16px 0 4px; font-weight: var(--ha-font-weight-medium, 500); }
    .kind { display: flex; align-items: center; gap: 8px; color: var(--secondary-text-color); margin-bottom: 8px; }
    .kind ha-svg-icon { --mdc-icon-size: 18px; flex: none; }
    .sysnote { color: var(--warning-color); font-size: var(--ha-font-size-s, 12px); }
    table { border-collapse: collapse; width: 100%; }
    table.kv th { width: 40%; text-align: left; font-weight: 400; color: var(--secondary-text-color); padding: 8px 16px 8px 0; vertical-align: top; }
    table.kv td { padding: 8px 0; }
    table.kv tr + tr th, table.kv tr + tr td { border-top: 1px solid var(--divider-color); }
    table.data th { text-align: left; font-size: var(--ha-font-size-s, 12px); font-weight: var(--ha-font-weight-medium, 500); padding: 8px 12px 8px 0; white-space: nowrap; }
    table.data td { padding: 6px 12px 6px 0; border-top: 1px solid var(--divider-color); }
    /* A going run: a bar per scanner, full and green once it has enough */
    /* Scanner quality: lights, the page with its three tiles; good so far as a ring */
    .qdot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; vertical-align: middle;
      background: var(--disabled-text-color, #9e9e9e); }
    .qdot.good { background: var(--success-color, #43a047); }
    .qdot.fair { background: var(--warning-color, #ffa600); }
    .qdot.poor { background: var(--error-color, #db4437); }
    .qdot.prelim { background: transparent; box-shadow: inset 0 0 0 2px var(--success-color, #43a047); }
    .qtiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 12px; }
    @media (max-width: 560px) { .qtiles { grid-template-columns: 1fr; } }
    .qtile { border: 1px solid var(--divider-color); border-radius: 12px; padding: 10px 12px; }
    .qtile.good { border-color: color-mix(in srgb, var(--success-color, #43a047) 50%, transparent); }
    .qtile.fair { border-color: color-mix(in srgb, var(--warning-color, #ffa600) 60%, transparent); }
    .qtile.poor { border-color: color-mix(in srgb, var(--error-color, #db4437) 60%, transparent); }
    .qhead { font-size: var(--ha-font-size-s, 12px); color: var(--secondary-text-color); }
    .qval { font-size: 24px; font-weight: var(--ha-font-weight-medium, 500); margin: 4px 0; }
    .qsub { font-size: var(--ha-font-size-s, 12px); color: var(--secondary-text-color); }
    .qstate { font-size: var(--ha-font-size-s, 12px); margin-top: 4px; }
    .bar { width: 96px; height: 6px; border-radius: 3px; background: var(--divider-color); overflow: hidden; }
    .bar i { display: block; height: 100%; background: var(--primary-color); }
    .bar.done i { background: var(--success-color, #43a047); }
    tr.prog.weak, tr.prog.none { color: var(--secondary-text-color); }
    .presets { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; margin: 8px 0 12px; }
    table.guide td.missing { color: var(--warning-color, #ffa600); font-weight: var(--ha-font-weight-medium, 500); }
    table.guide tr.sum td { color: var(--secondary-text-color); white-space: nowrap; }
    table.data td:last-child, table.data th:last-child { padding-right: 0; }
    .n { text-align: right !important; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .nowrap { white-space: nowrap; }
    tr.ign td { color: var(--secondary-text-color); }
    tr.live td { color: var(--primary-color); }
    .runs th { max-width: 6em; overflow: hidden; text-overflow: ellipsis; }
    .runs td { vertical-align: middle; }
    .runs .setup { font-size: var(--ha-font-size-s, 12px); color: var(--secondary-text-color); white-space: normal; }
    .runs .setup.changed { color: var(--warning-color); }
    tr.stale td { color: var(--secondary-text-color); }
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
    th .covsw { margin-right: 4px; }
    /* The floor plan as YAML: Home Assistant's code colours, without loading its editor */
    .planmode { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; margin-bottom: 12px; }
    .planmode .muted { margin-left: 8px; }
    /* The YAML fills the window and scrolls in itself */
    textarea.layout { height: calc(100vh - 340px); height: calc(100dvh - 340px); }
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
