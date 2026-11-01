// BLE Floorplan card: shows the trackers of the BLE Floorplan integration on the
// floor plan, live. The plan, the scanners and the positions come from the
// integration over the WebSocket API; the card only draws. Tapping a tracker
// or a scanner shows its readings, a tracker with its circles. Setting up,
// calibrating and the timeline live in the panel BLE Floorplan in the sidebar.
import {
  PLAN_CSS,
  PlanZoom,
  VERSION,
  bindHover,
  computeBounds,
  detailHtml,
  esc,
  formatter,
  icon,
  keep,
  loadLabels,
  loadRot,
  planInfo,
  planSvg,
  texts,
} from "./ble-floorplan-plan.js?v=0.11.2";

if (!customElements.get("ble-floorplan-card")) {
  const ROT_KEY = "ble-floorplan-card-rot";
  const LABELS_KEY = "ble-floorplan-card-labels";

  class BleFloorplanCard extends HTMLElement {
    setConfig(config) {
      this._config = {
        rotation: 0,
        show_room_labels: true,
        show_scanner_labels: true,
        show_tracker_labels: true,
        ...config,
      };
      this._rot = loadRot(ROT_KEY, this._config.rotation);
      this._labels = loadLabels(LABELS_KEY, {
        rooms: this._config.show_room_labels,
        scanners: this._config.show_scanner_labels,
        trackers: this._config.show_tracker_labels,
      });
      // The scanner or tracker tapped: {kind, key}
      this._sel = null;
      this._labelMenu = false;
      this._zoom = this._zoom || new PlanZoom({
        geom: () => ({ bounds: this._bounds || computeBounds(this._plan), rot: this._rot }),
        texts: () => texts(this._hass),
        wheel: false,
      });
      this._plan = this._plan || null;
      this._positions = this._positions || {};
      if (!this.shadowRoot) this.attachShadow({ mode: "open" });
      this._frame = false;
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
        this._error = err?.code === "not_loaded" ? texts(this._hass).notLoaded : String(err?.message || err);
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
      if (event.floorplan || event.positions) this._render();
    }

    _render() {
      if (!this.shadowRoot || !this._config) return;
      const t = texts(this._hass);
      const plan = this._plan;
      if (!plan || !plan.rooms.length) {
        this._frame = false;
        this.shadowRoot.innerHTML = `<style>${PLAN_CSS}${this._style()}</style><ha-card><div class="head">` +
          `<div class="title">${esc(this._config.title || t.title)}</div></div><div class="hint">${esc(this._error || t.noPlan)}</div></ha-card>`;
        this._bindOnce();
        return;
      }
      // A fixed frame; the redraw every second replaces the plan and the info
      // only, so the tooltip and the open menu stay
      if (!this._frame) {
        this.shadowRoot.innerHTML = `<style>${PLAN_CSS}${this._style()}</style><ha-card>` +
          `<div class="head"><div class="title">${esc(this._config.title || t.title)}</div><div class="btns" id="btns"></div></div>` +
          `<div class="map"><div id="svg"></div><div class="tip"></div></div><div id="info"></div></ha-card>`;
        this._frame = true;
        this._bindOnce();
        this._zoom.attach(this.shadowRoot.querySelector(".map"));
        const fmt = formatter(this._hass);
        this._refreshTip = bindHover(this.shadowRoot.querySelector(".map"), this.shadowRoot.querySelector(".tip"),
          (kind, key) => detailHtml(this._info, kind, key, texts(this._hass), fmt));
      }
      const fmt = formatter(this._hass);
      const scannerPos = (s) => [s.x, s.y];
      this._info = planInfo(plan, this._positions, scannerPos);
      if (this._sel && !this._info[`${this._sel.kind}s`][this._sel.key]) this._sel = null;
      const sel = this._sel;
      const root = this.shadowRoot;
      root.getElementById("svg").innerHTML = planSvg(plan, {
        bounds: this._bounds || computeBounds(plan),
        rot: this._rot,
        labels: this._labels,
        positions: this._positions,
        scannerPos,
        circles: sel?.kind === "tracker" ? sel.key : null,
        openTracker: sel?.kind === "tracker" ? sel.key : null,
        openScanner: sel?.kind === "scanner" ? sel.key : null,
        view: this._zoom.view,
      });
      const labelMenu = this._labelMenu
        ? `<div class="menu">${[["rooms", t.rooms], ["scanners", t.scanners], ["trackers", t.trackers]]
            .map(([k, l]) => `<label><input type="checkbox" data-toggle="${k}"${this._labels[k] ? " checked" : ""}>${esc(l)}</label>`)
            .join("")}</div>`
        : "";
      const btns = `<button id="rotate" class="icon-button" title="${esc(t.rotate)}">${icon("rotate")}</button>` +
        `<span class="menuwrap"><button id="labels" class="icon-button${this._labelMenu ? " on" : ""}" title="${esc(t.labels)}">${icon("label")}</button>${labelMenu}</span>`;
      const btnsEl = root.getElementById("btns");
      if (btnsEl.innerHTML !== btns) btnsEl.innerHTML = btns;
      root.getElementById("info").innerHTML = sel
        ? `<div class="info"><button id="close" class="icon-button" title="${esc(t.close)}">${icon("close")}</button>` +
          `${detailHtml(this._info, sel.kind, sel.key, t, fmt)}</div>`
        : "";
      this._refreshTip?.();
    }

    // One listener each on the shadow root: the content under it is redrawn
    _bindOnce() {
      if (this._bound) return;
      this._bound = true;
      const root = this.shadowRoot;
      root.addEventListener("click", (e) => {
        const el = e.target.closest?.("#rotate, #labels, #close, .scanner, .tracker");
        if (!el) return;
        if (el.id === "rotate") {
          this._rot = (this._rot + 90) % 360;
          keep(ROT_KEY, String(this._rot));
          this._zoom.view = null;
        } else if (el.id === "labels") {
          this._labelMenu = !this._labelMenu;
        } else if (el.id === "close") {
          this._sel = null;
        } else {
          const kind = el.classList.contains("scanner") ? "scanner" : "tracker";
          const same = this._sel?.kind === kind && this._sel.key === el.dataset.key;
          this._sel = same ? null : { kind, key: el.dataset.key };
        }
        this._render();
      });
      root.addEventListener("change", (e) => {
        const cb = e.target.closest?.("input[data-toggle]");
        if (!cb) return;
        this._labels = { ...this._labels, [cb.dataset.toggle]: cb.checked };
        keep(LABELS_KEY, this._labels);
        this._render();
      });
    }

    _style() {
      return `
        ha-card { padding: 12px 16px 16px; }
        .head { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
        .title { font-size: 1.2em; font-weight: 500; }
        .btns { display: flex; gap: 0; align-items: center; margin-right: -8px; }
        .menuwrap { position: relative; }
        .map { margin-top: 8px; }
        .map svg:not(.mdi) { max-height: 85vh; }
        .info { position: relative; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--divider-color); font-size: 13px; }
        .info .icon-button { position: absolute; right: -8px; top: 4px; }
        .hint { color: var(--secondary-text-color); margin-top: 8px; }`;
    }
  }

  customElements.define("ble-floorplan-card", BleFloorplanCard);

  // Visual editor (dashboard → edit → card): the title only. Everything else
  // is set on the card itself or lives in the panel BLE Floorplan.
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
        ? { title: "Titel", hint: "Drehung und Beschriftungen stellt man auf der Karte ein, Grundriss, Scanner, Tracker und Einstellungen im Panel BLE Floorplan." }
        : { title: "Title", hint: "Rotation and labels are set on the card; the plan, the scanners, the trackers and the settings live in the panel BLE Floorplan." };
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
