// BLE Floorplan card: where the trackers are, for every user (STANDARD §7, the
// dashboard card). Two views of one card:
//
// - "overview" (default) reads entities only: every tracker with its room, how
//   many are home. Found by the integration's own keys, in the size its space
//   allows.
// - "plan" draws the floor plan with the trackers live. The positions are in no
//   entity (each would write a recorder row a second), so this view, and only
//   this one, loads the plan module and its one subscription
//   (ble_floorplan/subscribe). It is open to every user, changes nothing, and
//   gives users who are no administrators no readings of the scanners.
//
// The card changes nothing and uses none of the administrators' commands;
// setting up, calibrating and the timeline live on the page BLE Floorplan.
const DOMAIN = "ble_floorplan";
const TAG = "ble-floorplan-card";
const PLAN_MODULE = "./ble-floorplan-plan.js?v=0.36.3";
// The overview from most to least: what does not fit is left out in this order
const SIZES = ["large", "medium", "small"];
const LEVEL_KEY = "ble-floorplan-card-level";

const TEXTS = {
    en: {
      name: "BLE Floorplan",
      description: "Which tracker is in which room, or the floor plan with the trackers live.",
      title: "BLE Floorplan",
      missing: "BLE Floorplan is not set up.",
      homeNone: "None home",
      homeCount: "{count} home",
      problemOne: "1 scanner unreachable",
      problemMany: "{count} scanners unreachable",
      titleField: "Title",
      mode: "View",
      modeOverview: "Overview: which tracker is where",
      modePlan: "Floor plan, live",
      size: "Size of the overview",
      sizeAuto: "By the space the card gets",
      sizeSmall: "Small",
      sizeMedium: "Medium",
      sizeLarge: "Large",
      parts: "Overview: what to show",
      show_summary: "Number of trackers at home",
      show_trackers: "Trackers",
      show_room: "Room of each tracker",
      show_away: "Trackers that are away",
      show_problem: "Unreachable scanners",
      plan: "Floor plan: what to show",
      rotation: "Rotation",
      show_room_labels: "Room names",
      show_tracker_labels: "Tracker names",
      show_scanners: "Scanners",
      show_scanner_labels: "Scanner names",
    },
    de: {
      name: "BLE Floorplan",
      description: "Welcher Tracker in welchem Raum ist, oder der Grundriss mit den Trackern live.",
      title: "BLE Floorplan",
      missing: "BLE Floorplan ist nicht eingerichtet.",
      homeNone: "Keiner zu Hause",
      homeCount: "{count} zu Hause",
      problemOne: "1 Scanner nicht erreichbar",
      problemMany: "{count} Scanner nicht erreichbar",
      titleField: "Titel",
      mode: "Ansicht",
      modeOverview: "Übersicht: welcher Tracker wo ist",
      modePlan: "Grundriss, live",
      size: "Größe der Übersicht",
      sizeAuto: "Nach dem Platz, den die Karte bekommt",
      sizeSmall: "Klein",
      sizeMedium: "Mittel",
      sizeLarge: "Groß",
      parts: "Übersicht: was gezeigt wird",
      show_summary: "Anzahl der Tracker zu Hause",
      show_trackers: "Tracker",
      show_room: "Raum je Tracker",
      show_away: "Abwesende Tracker",
      show_problem: "Nicht erreichbare Scanner",
      plan: "Grundriss: was gezeigt wird",
      rotation: "Drehung",
      show_room_labels: "Raumnamen",
      show_tracker_labels: "Tracker-Namen",
      show_scanners: "Scanner",
      show_scanner_labels: "Scanner-Namen",
    },
};

// What informs is on; what only matters in a problem or to an administrator is off
const DEFAULTS = {
  mode: "overview",
  size: "auto",
  show_summary: true,
  show_trackers: true,
  show_room: true,
  show_away: true,
  show_problem: false,
  rotation: 0,
  show_room_labels: true,
  show_tracker_labels: true,
  show_scanners: false,
  show_scanner_labels: true,
};
const OVERVIEW_PARTS = ["show_summary", "show_trackers", "show_room", "show_away", "show_problem"];
const PLAN_PARTS = ["show_room_labels", "show_tracker_labels", "show_scanners", "show_scanner_labels"];
const ROTATIONS = [0, 90, 180, 270];

// The language of the last card that got its data, for the editor's labels
let language = "en";
const texts = (lang) => TEXTS[(lang || "en").split("-")[0]] || TEXTS.en;
const fill = (text, values = {}) => text.replace(/\{(\w+)\}/g, (_, key) => String(values[key] ?? ""));
const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);

// The plan module: loaded once, by the first card in the mode "plan"
let planModule = null;
let planLoading = null;
const loadPlan = () => {
  planLoading = planLoading || import(PLAN_MODULE).then((module) => (planModule = module));
  return planLoading;
};

const STYLE = `
  :host { display: block; height: 100%; }
  ha-card { height: 100%; box-sizing: border-box; overflow: hidden; padding: 14px 16px; }
  .content.fill { height: 100%; }
  .head { display: flex; align-items: center; gap: 8px; }
  .head ha-icon { color: var(--secondary-text-color); --mdc-icon-size: 20px; }
  .title { flex: 1; font-size: var(--ha-font-size-l); font-weight: var(--ha-font-weight-medium); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pill { font-size: var(--ha-font-size-s); padding: 2px 10px; border-radius: 999px; white-space: nowrap;
    background: rgba(var(--rgb-primary-text-color), 0.06); color: var(--secondary-text-color); }
  .row { display: flex; align-items: center; gap: 12px; padding: 8px 0; border-top: 1px solid var(--divider-color); cursor: pointer; }
  .row ha-icon { color: var(--secondary-text-color); --mdc-icon-size: 20px; flex: none; }
  .row.slim { padding: 6px 0; }
  .head + .row, .head + .line { margin-top: 10px; }
  .who { flex: 1; min-width: 0; }
  .name { font-size: var(--ha-font-size-m); font-weight: var(--ha-font-weight-medium); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .row.slim .name { flex: 1; min-width: 0; }
  .away .name { font-weight: var(--ha-font-weight-normal); color: var(--secondary-text-color); }
  .place { font-size: var(--ha-font-size-s); color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .row.slim .place { font-size: var(--ha-font-size-m); flex: none; max-width: 60%; }
  .line { padding-top: 10px; margin-top: 10px; border-top: 1px solid var(--divider-color); font-size: var(--ha-font-size-s); color: var(--secondary-text-color); }
  .line.problem { color: var(--warning-color); }
  .line ha-icon { --mdc-icon-size: 16px; margin-right: 6px; }
  .small { display: flex; align-items: center; gap: 10px; height: 100%; }
  .small ha-icon { color: var(--secondary-text-color); flex: none; }
  .small .sub { font-size: var(--ha-font-size-s); color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .missing { color: var(--secondary-text-color); font-size: var(--ha-font-size-m); }
  ha-card.plan { padding: 12px 16px 16px; }
  ha-card.plan .map { margin-top: 8px; }
  ha-card.plan #svg { position: relative; }
  ha-card.plan .map svg:not(.mdi) { max-height: 85vh; }
  ha-card.plan.fixed { display: flex; flex-direction: column; }
  ha-card.plan.fixed .map { flex: 1; min-height: 0; }
  ha-card.plan.fixed #svg { height: 100%; }
  ha-card.plan.fixed .map svg:not(.mdi) { max-height: none; }
  .info { position: relative; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--divider-color); font-size: var(--ha-font-size-m); }
  .info ha-icon-button { position: absolute; right: -8px; top: 0; }
`;

class BleFloorplanCard extends HTMLElement {
  static getStubConfig() {
    return {};
  }

  // A field for every option, the parts of each view in one expandable group
  static getConfigForm() {
    const t = texts(language);
    const bool = (name) => ({ name, selector: { boolean: {} } });
    const pick = (name, options) => ({
      name,
      selector: { select: { mode: "dropdown", options: options.map(([value, label]) => ({ value, label })) } },
    });
    return {
      schema: [
        { name: "title", selector: { text: {} } },
        pick("mode", [["overview", t.modeOverview], ["plan", t.modePlan]]),
        pick("size", [["auto", t.sizeAuto], ["small", t.sizeSmall], ["medium", t.sizeMedium], ["large", t.sizeLarge]]),
        { type: "expandable", name: "parts", title: t.parts, flatten: true, schema: OVERVIEW_PARTS.map(bool) },
        {
          type: "expandable",
          name: "plan",
          title: t.plan,
          flatten: true,
          schema: [
            { name: "rotation", selector: { select: { mode: "dropdown", options: ROTATIONS.map((r) => ({ value: String(r), label: `${r}°` })) } } },
            ...PLAN_PARTS.map(bool),
          ],
        },
      ],
      computeLabel: (field) => texts(language)[field.name === "title" ? "titleField" : field.name] ?? field.name,
    };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = { ...DEFAULTS };
    this._key = null;
    // The mode the shadow root holds a frame of
    this._drawn = null;
    // Plan view: what the subscription sent, and the scanner or tracker tapped ({kind, key})
    this._floorplan = null;
    this._positions = {};
    this._offline = [];
    this._sel = null;
    this._error = null;
  }

  setConfig(config) {
    this._config = { ...DEFAULTS, ...config };
    this._key = null;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    language = hass?.language || language;
    this._render();
  }

  // Home Assistant sets it: "grid" in a sections view, where the card has a fixed height
  set layout(layout) {
    this._layout = layout;
    this._key = null;
    this._render();
  }

  getCardSize() {
    return this._config.mode === "plan" ? 12 : 3;
  }

  // As high as what it shows, until someone gives it fewer rows
  getGridOptions() {
    return this._config.mode === "plan"
      ? { columns: 12, rows: "auto", min_columns: 6, min_rows: 4 }
      : { columns: 6, rows: "auto", min_columns: 3, min_rows: 1 };
  }

  connectedCallback() {
    this._observer = new ResizeObserver(() => {
      this._key = null;
      this._render();
    });
    this._observer.observe(this);
    if (!this._bound) {
      this._bound = true;
      this.shadowRoot.addEventListener("click", (event) => this._click(event));
    }
    this._render();
  }

  disconnectedCallback() {
    this._observer?.disconnect();
    this._live?.close();
  }

  get _t() {
    return texts(this._hass?.language);
  }

  // Nothing here changes anything: a row opens Home Assistant's own dialog of the
  // entity, the plan shows another level or what it knows of a tracker
  _click(event) {
    const row = event.target.closest?.("[data-entity]");
    if (row) {
      this.dispatchEvent(
        new CustomEvent("hass-more-info", { detail: { entityId: row.dataset.entity }, bubbles: true, composed: true }),
      );
      return;
    }
    const el = event.target.closest?.("#close, .scanner, .tracker, [data-level]");
    if (!el || !planModule) return;
    if (el.dataset.level != null) {
      this._level = Number(el.dataset.key);
      planModule.keep(LEVEL_KEY, el.dataset.key);
      this._sel = null;
    } else if (el.id === "close") {
      this._sel = null;
    } else {
      const kind = el.classList.contains("scanner") ? "scanner" : "tracker";
      const same = this._sel?.kind === kind && this._sel.key === el.dataset.key;
      this._sel = same ? null : { kind, key: el.dataset.key };
    }
    this._drawPlan();
  }

  _render() {
    if (!this._hass || !this.isConnected) return;
    const mode = this._config.mode === "plan" ? "plan" : "overview";
    if (mode !== this._drawn) {
      // Another view: its own frame, and no subscription left behind
      this._drawn = mode;
      this._key = null;
      this._live?.close();
      this._live = null;
      this.shadowRoot.innerHTML = "";
    }
    if (mode === "plan") this._renderPlan();
    else this._renderOverview();
  }

  // ---- Overview: entities only ----

  // What the entities say, found by the integration's own keys so that a renamed
  // entity or another language changes nothing. The trackers come as a list from
  // the summary entity, in the order of the plan.
  _data() {
    const hass = this._hass;
    const own = Object.values(hass.entities || {}).filter((entry) => entry.platform === DOMAIN);
    const states = (key) =>
      own
        .filter((entry) => entry.translation_key === key)
        .map((entry) => hass.states[entry.entity_id])
        .filter(Boolean);
    const summary = states("trackers_home")[0];
    if (!summary) return null;
    const format = (entity) => hass.formatEntityState?.(entity) ?? entity.state;
    const known = (entity) => entity && !["unavailable", "unknown"].includes(entity.state);
    const trackers = [];
    for (const item of summary.attributes.tracker_list || []) {
      const room = hass.states[item.room_entity];
      const presence = hass.states[item.presence_entity];
      // A paused tracker is not measured: its entities are unavailable, it is left out
      const shown = [room, presence].filter((entity) => entity && entity.state !== "unavailable");
      if (!shown.length) continue;
      const home = presence ? presence.state === "home" : known(room);
      const area = known(room) ? hass.areas?.[room.attributes.area_id]?.name : null;
      trackers.push({
        name: item.name,
        entity: (room || presence).entity_id,
        home,
        // The room as Home Assistant names its area, else as the plan names it; away as Home Assistant says it
        place: home && known(room) ? area || format(room) : format(presence || room),
      });
    }
    const problem = states("unreachable")[0];
    return {
      trackers,
      home: trackers.filter((tracker) => tracker.home).length,
      problem: problem?.state === "on" ? (problem.attributes.scanners || []).length || 1 : 0,
    };
  }

  _renderOverview() {
    const data = this._data();
    const fixed = this._layout === "grid";
    const key = JSON.stringify([data, this._config, this._hass.language, fixed, this.clientWidth, this.clientHeight]);
    if (key === this._key) return;
    this._key = key;
    const root = this.shadowRoot;
    let card = root.querySelector("ha-card");
    if (!card) {
      // The frame stays: a new ha-card shows its content only once it has drawn
      // itself, so what is measured right after creating it would be nothing
      root.innerHTML = `<style>${STYLE}</style><ha-card><div class="content"></div></ha-card>`;
      card = root.querySelector("ha-card");
      card.updateComplete?.then(() => {
        this._key = null;
        this._render();
      });
    }
    const content = root.querySelector(".content");
    // Draws the card and says whether its content is higher than the card
    const draw = (html, whole = false) => {
      content.className = `content${whole ? " fill" : ""}`;
      content.innerHTML = html;
      const style = getComputedStyle(card);
      const room = card.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
      return content.scrollHeight > room + 1;
    };
    if (!data) {
      draw(`<div class="missing">${esc(this._t.missing)}</div>`);
      return;
    }
    const wanted = SIZES.includes(this._config.size) ? [this._config.size] : SIZES;
    for (const size of wanted) {
      const overflows = draw(this._view(data, size), size === "small");
      // Only a card with a fixed height can be too small for what it shows
      if (!fixed || !overflows) break;
    }
    // A second line that is cut off gives way to a shorter one. Measured beside the
    // line, to the fraction of a pixel: scrollWidth and clientWidth are whole
    // numbers and call a text that is a hair too wide a fit
    const line = content.querySelector(".sub[data-lines]");
    if (line) {
      const probe = document.createElement("span");
      probe.className = line.className;
      probe.style.cssText = "position: absolute; visibility: hidden; overflow: visible; width: auto; display: inline-block;";
      line.parentElement.appendChild(probe);
      const room = line.getBoundingClientRect().width;
      for (const text of JSON.parse(line.dataset.lines)) {
        line.textContent = text;
        probe.textContent = text;
        if (probe.getBoundingClientRect().width <= room) break;
      }
      probe.remove();
    }
  }

  // The overview in one size. Order of importance: the trackers at home with
  // their rooms, how many are home, the trackers that are away, the unreachable
  // scanners. Every part asks its option first.
  _view(data, size) {
    const t = this._t;
    const c = this._config;
    const title = c.title || t.title;
    const summary = c.show_summary ? (data.home ? fill(t.homeCount, { count: data.home }) : t.homeNone) : "";
    const trackers = c.show_trackers ? data.trackers.filter((tracker) => tracker.home || c.show_away) : [];
    if (size === "small") {
      // The second line from most to least: the first that fits is shown
      const list = trackers
        .filter((tracker) => c.show_room || tracker.home)
        .map((tracker) => (c.show_room ? `${tracker.name}: ${tracker.place}` : tracker.name))
        .join(", ");
      const lines = [list, summary].filter(Boolean);
      return `<div class="small"><ha-icon icon="mdi:floor-plan"></ha-icon><div class="who"><div class="name">${esc(title)}</div>` +
        (lines.length ? `<div class="sub" data-lines="${esc(JSON.stringify(lines))}">${esc(lines[0])}</div>` : "") + `</div></div>`;
    }
    const large = size === "large";
    let html = `<div class="head"><ha-icon icon="mdi:floor-plan"></ha-icon><div class="title">${esc(title)}</div>` +
      (summary ? `<span class="pill">${esc(summary)}</span>` : "") + `</div>`;
    for (const tracker of trackers) {
      const place = c.show_room ? `<div class="place">${esc(tracker.place)}</div>` : "";
      const cls = `row${large ? "" : " slim"}${tracker.home ? "" : " away"}`;
      html += large
        ? `<div class="${cls}" data-entity="${esc(tracker.entity)}"><ha-icon icon="${tracker.home ? "mdi:home-account" : "mdi:home-export-outline"}"></ha-icon>` +
          `<div class="who"><div class="name">${esc(tracker.name)}</div>${place}</div></div>`
        : `<div class="${cls}" data-entity="${esc(tracker.entity)}"><div class="name">${esc(tracker.name)}</div>${place}</div>`;
    }
    if (c.show_problem && data.problem) {
      html += `<div class="line problem"><ha-icon icon="mdi:alert-outline"></ha-icon>` +
        `${esc(data.problem === 1 ? t.problemOne : fill(t.problemMany, { count: data.problem }))}</div>`;
    }
    return html;
  }

  // ---- Plan: the floor plan, live ----

  _renderPlan() {
    if (!planModule) {
      loadPlan().then(
        () => {
          this._key = null;
          this._render();
        },
        () => {},
      );
      return;
    }
    if (!this._live) {
      this._live = new planModule.LiveSubscription(
        this,
        (event) => this._onEvent(event),
        (err) => {
          const error = err ? planModule.errorText(planModule.texts(this._hass), err).text : null;
          if (error === this._error) return;
          this._error = error;
          this._drawPlan();
        },
      );
    }
    this._live.ensure(this._hass);
    const fixed = this._layout === "grid";
    const key = JSON.stringify([this._config, this._hass.language, fixed]);
    if (key === this._key) return;
    this._key = key;
    this._drawPlan();
  }

  _onEvent(event) {
    if (event.floorplan) this._floorplan = event.floorplan;
    if (event.positions) this._positions = event.positions;
    if (event.offline) this._offline = event.offline;
    if (event.floorplan || event.positions || event.offline) this._drawPlan();
  }

  _drawPlan() {
    if (this._drawn !== "plan" || !planModule || !this._hass) return;
    const P = planModule;
    const t = P.texts(this._hass);
    const c = this._config;
    const root = this.shadowRoot;
    const fixed = this._layout === "grid" ? " fixed" : "";
    const head = `<div class="head"><div class="title">${esc(c.title || this._t.title)}</div></div>`;
    const whole = this._floorplan;
    if (!whole || !whole.rooms.length) {
      this._frame = false;
      root.innerHTML = `<style>${P.PLAN_CSS}${STYLE}</style><ha-card class="plan">${head}` +
        `<div class="missing">${esc(this._error || (whole ? t.noPlan : ""))}</div></ha-card>`;
      return;
    }
    // Scanners are an administrator's concern: drawn only where the card is told to
    const plan = c.show_scanners ? whole : { ...whole, scanners: [] };
    const rot = ROTATIONS.includes(Number(c.rotation)) ? Number(c.rotation) : 0;
    const bounds = P.computeBounds(whole);
    this._geom = { bounds, rot };
    // A fixed frame; the redraw every second replaces the plan and the info
    // only, so the tooltip and the zoom stay
    if (!this._frame || !root.querySelector("ha-card.plan #svg")) {
      root.innerHTML = `<style>${P.PLAN_CSS}${STYLE}</style><ha-card class="plan${fixed}">${head}` +
        `<div class="map"><div id="svg"></div><div class="tip"></div></div><div id="info"></div></ha-card>`;
      this._frame = true;
      this._zoom = new P.PlanZoom({ geom: () => this._geom, texts: () => P.texts(this._hass), wheel: false });
      this._zoom.attach(root.querySelector(".map"));
      this._refreshTip = P.bindHover(root.querySelector(".map"), root.querySelector(".tip"), (kind, key) => this._detail(kind, key));
      if (this._level === undefined) this._level = P.loadNumber(LEVEL_KEY, 0);
    }
    root.querySelector("ha-card").className = `plan${fixed}`;
    root.querySelector(".title").textContent = c.title || this._t.title;
    // The readings an administrator gets name every scanner, drawn or not
    this._info = P.planInfo(whole, this._positions, (s) => [s.x, s.y], this._offline);
    if (this._sel && !this._info[`${this._sel.kind}s`][this._sel.key]) this._sel = null;
    const sel = this._sel;
    const level = P.shownLevel(whole, this._level);
    root.getElementById("svg").innerHTML = P.levelSwitch(whole, level, "data-level") + P.planSvg(plan, {
      level,
      bounds,
      rot,
      labels: { rooms: c.show_room_labels, scanners: c.show_scanner_labels, trackers: c.show_tracker_labels },
      positions: this._positions,
      offline: this._offline,
      scannerPos: (s) => [s.x, s.y],
      circles: sel?.kind === "tracker" ? sel.key : null,
      openTracker: sel?.kind === "tracker" ? sel.key : null,
      openScanner: sel?.kind === "scanner" ? sel.key : null,
      view: this._zoom.view,
    });
    root.getElementById("info").innerHTML = sel
      ? `<div class="info">${P.iconButton("close", t.close, 'id="close"')}${this._detail(sel.kind, sel.key)}</div>`
      : "";
    this._refreshTip?.();
  }

  // What the plan knows of a tracker or a scanner. Users who are no
  // administrators get positions without readings: the name and the room then
  _detail(kind, key) {
    const P = planModule;
    const plain = Object.values(this._positions).some((position) => !("readings" in position));
    return P.detailHtml(this._info, kind, key, P.texts(this._hass), P.formatter(this._hass), plain);
  }
}

if (!customElements.get(TAG)) customElements.define(TAG, BleFloorplanCard);
window.customCards = window.customCards || [];
if (!window.customCards.some((entry) => entry.type === TAG)) {
  window.customCards.push({ type: TAG, name: TEXTS.en.name, description: TEXTS.en.description, preview: true });
}
