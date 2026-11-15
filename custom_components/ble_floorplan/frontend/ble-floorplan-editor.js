// BLE Floorplan: the drawing of the floor plan on the page. A draft of the
// floors, rooms, openings and stairs is edited on the plan of one level and
// saved as a whole; scanners, trackers and settings are not touched. Tools:
// select (move a room or stairs, drag a corner, add a corner at an edge's
// middle), rectangle, polygon, door (on the nearest wall) and stairs.
import {
  computeBounds,
  esc,
  floorsOf,
  levelsOf,
  roomPoints,
  snap,
  toPlan,
} from "./ble-floorplan-plan.js?v=0.28.2";

// A door is this wide when placed, in metres
const DOOR_WIDTH = 0.9;
// A click this close to a wall places a door on it
const DOOR_REACH = 0.6;
// A point this close to a corner takes the corner
const CORNER_SNAP = 0.25;
// A rectangle smaller than this is taken as a click
const MIN_SIZE = 0.3;
// Floors above each other are this far apart when added
const STOREY = 2.8;
// The drawing reaches this far beyond the rooms, so a new building has room
const MARGIN = 6;
const UNDO_MAX = 50;

const clone = (v) => JSON.parse(JSON.stringify(v));
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const round2 = (v) => Math.round(v * 100) / 100;

// The closest point on the segment a-b to p, and how far along (0..1)
const onSegment = (p, a, b) => {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const f = len2 ? Math.min(Math.max(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2, 0), 1) : 0;
  return { q: [a[0] + f * dx, a[1] + f * dy], f };
};

// A key for a new floor from its name: lower case letters, digits and _
export const floorKey = (name, taken) => {
  const base = (name || "")
    .toLowerCase()
    .replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "") || "floor";
  let key = base;
  for (let i = 2; taken.includes(key); i++) key = `${base}_${i}`;
  return key;
};

export class PlanEditor {
  // host: the page, for its texts, forms, buttons, plan, level and WebSocket
  constructor(host) {
    this.host = host;
    this.draft = null;
    this.tool = "select";
    this.sel = null;
    this.poly = [];
    this.preview = null;
    this.undo = [];
    this.dirty = false;
    this.confirmCancel = false;
    this._edited = false;
  }

  get active() {
    return this.draft != null;
  }

  // ---- Draft ----

  start(plan) {
    const firstKey = plan.floors?.[0]?.key ?? "";
    this.draft = {
      floors: clone(plan.floors || []),
      rooms: plan.rooms.map((r) => ({ ...clone(r), floor: r.floor ?? firstKey })),
      openings: (plan.openings || []).map((o) => [o[0], o[1], o[2], o[3], o[4] ?? firstKey]),
      stairs: clone(plan.stairs || []),
    };
    this.tool = "select";
    this.sel = null;
    this.poly = [];
    this.preview = null;
    this.undo = [];
    this.dirty = false;
    this.confirmCancel = false;
  }

  stop() {
    this.draft = null;
    this.sel = null;
    this.poly = [];
    this.preview = null;
  }

  // The draft as the data set_layout takes: no floor keys on a plan without floors
  layout() {
    const d = clone(this.draft);
    if (!d.floors.length) {
      for (const r of d.rooms) delete r.floor;
      d.openings = d.openings.map((o) => o.slice(0, 4));
    }
    return d;
  }

  _save() {
    this.undo.push(JSON.stringify(this.draft));
    if (this.undo.length > UNDO_MAX) this.undo.shift();
    this.dirty = true;
  }

  // The plan drawn while editing: the draft's parts with the plan's scanners and trackers
  plan() {
    const plan = this.host._plan;
    const d = this.draft;
    return { ...plan, floors: d.floors, rooms: d.rooms, openings: d.openings, stairs: d.stairs };
  }

  // Room to draw in: the rooms and some metres around them
  bounds() {
    const b = computeBounds(this.plan());
    return { w: Math.max(b.w + MARGIN, 12), h: Math.max(b.h + MARGIN, 10) };
  }

  // The floor new things go on: the selected floor if it lies on the level shown, else the level's first
  get floor() {
    const level = this.host._level;
    const floors = floorsOf(this.plan()).filter((f) => (f.elevation ?? 0) === level);
    if (this.sel?.kind === "floor") {
      const f = this.draft.floors[this.sel.i];
      if (f && (f.elevation ?? 0) === level) return f.key;
    }
    return floors[0]?.key ?? "";
  }

  _onLevel(floorKey) {
    const f = floorsOf(this.plan()).find((x) => x.key === floorKey) || floorsOf(this.plan())[0];
    return (f.elevation ?? 0) === this.host._level;
  }

  // ---- Snapping ----

  // The level under the one shown (above it for the lowest): drawn faintly, its corners snap
  _guideLevel() {
    const levels = levelsOf(this.plan());
    const level = this.host._level;
    const below = levels.filter((l) => l < level);
    if (below.length) return below[below.length - 1];
    return levels.find((l) => l > level) ?? null;
  }

  _guideRooms() {
    const g = this._guideLevel();
    if (g == null) return [];
    const keys = new Set(floorsOf(this.plan()).filter((f) => (f.elevation ?? 0) === g).map((f) => f.key));
    return this.draft.rooms.filter((r) => !r.zone && keys.has(r.floor));
  }

  _corners() {
    const pts = [];
    this.draft.rooms.forEach((r, i) => {
      if (!this._onLevel(r.floor)) return;
      roomPoints(r).forEach((p, v) => pts.push({ p, i, v }));
    });
    for (const r of this._guideRooms()) for (const p of roomPoints(r)) pts.push({ p, i: -2, v: null });
    return pts;
  }

  // A point on the grid, or the corner of a room on the level close by (not the one dragged)
  _snap(x, y, skip = null) {
    let best = null;
    let bestD = CORNER_SNAP;
    for (const c of this._corners()) {
      if (skip && c.i === skip.i && (skip.v == null || c.v === skip.v)) continue;
      const d = dist(c.p, [x, y]);
      if (d < bestD) {
        bestD = d;
        best = c.p;
      }
    }
    return best ? [best[0], best[1]] : [snap(x), snap(y)];
  }

  _point(e, skip) {
    const [x, y] = toPlan(this.host.shadowRoot, e, this.bounds());
    return this._snap(x, y, skip);
  }

  // ---- Drawing on the plan ----

  // Hit areas, the selection with its handles, what is being drawn
  overlay() {
    if (!this.active) return "";
    const d = this.draft;
    const out = this._guideRooms().map((r) => `<polygon class="eghost" points="${roomPoints(r).map((p) => p.join(",")).join(" ")}"/>`);
    d.rooms.forEach((r, i) => {
      if (!this._onLevel(r.floor)) return;
      out.push(`<polygon class="ehit" data-kind="room" data-i="${i}" points="${roomPoints(r).map((p) => p.join(",")).join(" ")}"/>`);
    });
    d.stairs.forEach((s, i) => {
      if (!this._onLevel(s.floor) && !this._onLevel(s.to)) return;
      out.push(`<polygon class="ehit" data-kind="stairs" data-i="${i}" points="${s.points.map((p) => p.join(",")).join(" ")}"/>`);
    });
    d.openings.forEach((o, i) => {
      if (!this._onLevel(o[4])) return;
      out.push(`<line class="ehit line" data-kind="opening" data-i="${i}" x1="${o[0]}" y1="${o[1]}" x2="${o[2]}" y2="${o[3]}"/>`);
    });
    const sel = this.sel;
    if (sel?.kind === "room" && d.rooms[sel.i]) {
      const pts = roomPoints(d.rooms[sel.i]);
      out.push(`<polygon class="esel" points="${pts.map((p) => p.join(",")).join(" ")}"/>`);
      out.push(...this._handles(pts, true));
    } else if (sel?.kind === "stairs" && d.stairs[sel.i]) {
      const pts = d.stairs[sel.i].points;
      out.push(`<polygon class="esel" points="${pts.map((p) => p.join(",")).join(" ")}"/>`);
      out.push(...this._handles(pts, true));
    } else if (sel?.kind === "opening" && d.openings[sel.i]) {
      const o = d.openings[sel.i];
      out.push(`<line class="esel door" x1="${o[0]}" y1="${o[1]}" x2="${o[2]}" y2="${o[3]}"/>`);
      out.push(...this._handles([[o[0], o[1]], [o[2], o[3]]], false));
    }
    if (this.poly.length) {
      out.push(`<polyline class="epoly" points="${this.poly.map((p) => p.join(",")).join(" ")}"/>`);
      this.poly.forEach((p, i) => out.push(`<circle class="ept${i === 0 ? " first" : ""}" cx="${p[0]}" cy="${p[1]}" r="0.12"/>`));
    }
    if (this.preview) {
      const { a, b } = this.preview;
      const x = Math.min(a[0], b[0]);
      const y = Math.min(a[1], b[1]);
      out.push(`<rect class="epreview" x="${x}" y="${y}" width="${Math.abs(b[0] - a[0])}" height="${Math.abs(b[1] - a[1])}"/>`);
    }
    return `<g class="editor">${out.join("")}</g>`;
  }

  _handles(pts, closed) {
    const out = pts.map((p, v) => `<circle class="ehandle" data-v="${v}" cx="${p[0]}" cy="${p[1]}" r="0.16"/>`);
    if (closed) {
      pts.forEach((p, v) => {
        const q = pts[(v + 1) % pts.length];
        const m = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
        out.push(`<rect class="emid" data-m="${v}" x="${m[0] - 0.09}" y="${m[1] - 0.09}" width="0.18" height="0.18"/>`);
      });
    }
    return out;
  }

  // Whether the editor takes the pointer, so the map does not pan
  takes(e) {
    if (!this.active) return false;
    if (this.tool !== "select") return true;
    return !!e.target.closest?.(".ehandle, .emid, .ehit");
  }

  // ---- Pointer ----

  pointerDown(e) {
    if (!this.active || (e.pointerType === "mouse" && e.button !== 0)) return false;
    if (e.target.closest?.(".maptools, .zoombtns, .levels")) return false;
    const tool = this.tool;
    if (tool === "rect" || tool === "stairs") return this._dragRect(e);
    if (tool === "poly") return this._polyClick(e);
    if (tool === "door") return this._door(e);
    return this._select(e);
  }

  _drag(e, onMove, onUp) {
    e.preventDefault();
    this.host._dragging = true;
    const move = (ev) => {
      onMove(ev);
      this.host._drawEditor();
    };
    const up = (ev) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      onUp?.(ev);
      setTimeout(() => {
        this.host._dragging = false;
        this.host._render();
      }, 0);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return true;
  }

  _dragRect(e) {
    const a = this._point(e);
    this.preview = { a, b: a };
    return this._drag(
      e,
      (ev) => {
        this.preview.b = this._point(ev);
      },
      () => {
        const { a: p, b: q } = this.preview;
        this.preview = null;
        const w = Math.abs(q[0] - p[0]);
        const h = Math.abs(q[1] - p[1]);
        if (w < MIN_SIZE || h < MIN_SIZE) return;
        const x = round2(Math.min(p[0], q[0]));
        const y = round2(Math.min(p[1], q[1]));
        this._save();
        if (this.tool === "stairs") {
          const to = this._stairsTarget(this.floor);
          if (to == null) return;
          this.draft.stairs.push({ floor: this.floor, to, points: [[x, y], [x + w, y], [x + w, y + h], [x, y + h]].map((pt) => pt.map(round2)) });
          this.sel = { kind: "stairs", i: this.draft.stairs.length - 1 };
        } else {
          this.draft.rooms.push({ name: this._newName(), x, y, w: round2(w), h: round2(h), floor: this.floor });
          this.sel = { kind: "room", i: this.draft.rooms.length - 1 };
        }
        this.tool = "select";
      }
    );
  }

  _polyClick(e) {
    e.preventDefault();
    const p = this._point(e);
    if (this.poly.length >= 3 && dist(p, this.poly[0]) <= CORNER_SNAP) {
      this.finishPoly();
    } else {
      this.poly.push(p);
    }
    this.host._render();
    return true;
  }

  finishPoly() {
    if (this.poly.length < 3) return;
    this._save();
    this.draft.rooms.push({ name: this._newName(), points: this.poly.map((p) => p.map(round2)), floor: this.floor });
    this.sel = { kind: "room", i: this.draft.rooms.length - 1 };
    this.poly = [];
    this.tool = "select";
  }

  // A door on the closest wall of a room of the level, centred where clicked
  _door(e) {
    e.preventDefault();
    const [x, y] = toPlan(this.host.shadowRoot, e, this.bounds());
    let best = null;
    this.draft.rooms.forEach((r) => {
      if (r.zone || !this._onLevel(r.floor)) return;
      const pts = roomPoints(r);
      pts.forEach((a, i) => {
        const b = pts[(i + 1) % pts.length];
        const { q } = onSegment([x, y], a, b);
        const d = dist(q, [x, y]);
        if (d <= DOOR_REACH && (!best || d < best.d)) best = { d, a, b, q, floor: r.floor };
      });
    });
    if (!best) {
      this.host._note = { kind: "err", text: this.host._t.edNoWall };
      this.host._render();
      return true;
    }
    const len = dist(best.a, best.b);
    const half = Math.min(DOOR_WIDTH, len) / 2;
    const ux = (best.b[0] - best.a[0]) / len;
    const uy = (best.b[1] - best.a[1]) / len;
    // Kept on the wall: the door slides in from its ends
    const along = Math.min(Math.max(dist(best.a, best.q), half), len - half);
    const c = [best.a[0] + ux * along, best.a[1] + uy * along];
    this._save();
    this.draft.openings.push([c[0] - ux * half, c[1] - uy * half, c[0] + ux * half, c[1] + uy * half].map(round2).concat([best.floor]));
    this.sel = { kind: "opening", i: this.draft.openings.length - 1 };
    this.tool = "select";
    this.host._render();
    return true;
  }

  _select(e) {
    const d = this.draft;
    const handle = e.target.closest?.(".ehandle");
    const mid = e.target.closest?.(".emid");
    const hit = e.target.closest?.(".ehit");
    const sel = this.sel;
    if ((handle || mid) && sel) {
      this._save();
      let v = Number(handle ? handle.dataset.v : mid.dataset.m);
      if (mid) {
        // A new corner in the middle of the edge; a rectangle becomes a polygon for it
        const item = sel.kind === "room" ? d.rooms[sel.i] : d.stairs[sel.i];
        const pts = item.points || roomPoints(item);
        const q = pts[(v + 1) % pts.length];
        const m = [round2((pts[v][0] + q[0]) / 2), round2((pts[v][1] + q[1]) / 2)];
        const next = [...pts.slice(0, v + 1), m, ...pts.slice(v + 1)];
        this._setPoints(sel, next);
        v += 1;
      }
      return this._drag(e, (ev) => this._moveVertex(sel, v, this._point(ev, { i: sel.kind === "room" ? sel.i : -1, v })));
    }
    if (!hit) {
      this.sel = null;
      this.host._render();
      return false;
    }
    const kind = hit.dataset.kind;
    const i = Number(hit.dataset.i);
    this.sel = { kind, i };
    this._edited = false;
    if (kind === "opening") {
      this.host._render();
      return true;
    }
    // Drag the whole room or stairs; a click without moving only selects
    const start = toPlan(this.host.shadowRoot, e, this.bounds());
    const item = kind === "room" ? d.rooms[i] : d.stairs[i];
    const before = clone(item);
    let moved = false;
    return this._drag(
      e,
      (ev) => {
        const p = toPlan(this.host.shadowRoot, ev, this.bounds());
        const dx = snap(p[0] - start[0]);
        const dy = snap(p[1] - start[1]);
        if (!moved && Math.hypot(dx, dy) < 0.1) return;
        if (!moved) this._save();
        moved = true;
        if (before.points) item.points = before.points.map((q) => [round2(q[0] + dx), round2(q[1] + dy)]);
        else {
          item.x = round2(before.x + dx);
          item.y = round2(before.y + dy);
        }
        if (before.lx != null) {
          item.lx = round2(before.lx + dx);
          item.ly = round2(before.ly + dy);
        }
      }
    );
  }

  _setPoints(sel, pts) {
    const d = this.draft;
    if (sel.kind === "room") {
      const r = d.rooms[sel.i];
      delete r.x;
      delete r.y;
      delete r.w;
      delete r.h;
      r.points = pts;
    } else d.stairs[sel.i].points = pts;
  }

  _moveVertex(sel, v, p) {
    const d = this.draft;
    if (sel.kind === "opening") {
      const o = d.openings[sel.i];
      o[v * 2] = round2(p[0]);
      o[v * 2 + 1] = round2(p[1]);
      return;
    }
    const item = sel.kind === "room" ? d.rooms[sel.i] : d.stairs[sel.i];
    if (!item.points) {
      // A rectangle keeps its shape: the dragged corner and the opposite one span it
      const pts = roomPoints(item);
      const o = pts[(v + 2) % 4];
      const w = Math.abs(p[0] - o[0]);
      const h = Math.abs(p[1] - o[1]);
      if (w < MIN_SIZE || h < MIN_SIZE) return;
      item.x = round2(Math.min(p[0], o[0]));
      item.y = round2(Math.min(p[1], o[1]));
      item.w = round2(w);
      item.h = round2(h);
      return;
    }
    item.points[v] = [round2(p[0]), round2(p[1])];
  }

  _newName() {
    const t = this.host._t;
    const names = new Set(this.draft.rooms.map((r) => r.name));
    let n = this.draft.rooms.length + 1;
    while (names.has(`${t.edRoom} ${n}`)) n++;
    return `${t.edRoom} ${n}`;
  }

  // Where stairs from a floor lead: the floor of the next level of the same building, else any other
  _stairsTarget(from) {
    const floors = this.draft.floors;
    const here = floors.find((f) => f.key === from);
    if (!here) return null;
    const others = floors.filter((f) => f.key !== from);
    const same = others.filter((f) => (f.building || "") === (here.building || "")).sort((a, b) => (a.elevation ?? 0) - (b.elevation ?? 0));
    const up = same.find((f) => (f.elevation ?? 0) > (here.elevation ?? 0));
    return (up || same[same.length - 1] || others[0])?.key ?? null;
  }

  // ---- Floors ----

  addFloor(newBuilding) {
    const t = this.host._t;
    const d = this.draft;
    this._save();
    if (!d.floors.length) {
      // The plan's one floor becomes the ground floor of the main building
      d.floors.push({ key: "eg", name: t.edGround, building: "", elevation: 0 });
      for (const r of d.rooms) r.floor = "eg";
      d.openings = d.openings.map((o) => [o[0], o[1], o[2], o[3], "eg"]);
    }
    const keys = d.floors.map((f) => f.key);
    const ref = this.sel?.kind === "floor" ? d.floors[this.sel.i] : d.floors[0];
    let floor;
    if (newBuilding) {
      const names = new Set(d.floors.map((f) => f.building));
      let n = 1;
      while (names.has(`${t.edBuilding} ${n}`)) n++;
      const building = `${t.edBuilding} ${n}`;
      floor = { key: floorKey(building, keys), name: building, building, elevation: 0 };
    } else {
      const same = d.floors.filter((f) => (f.building || "") === (ref.building || ""));
      const top = Math.max(...same.map((f) => f.elevation ?? 0));
      const name = `${t.edFloor} ${same.length}`;
      floor = { key: floorKey(name, keys), name, building: ref.building || "", elevation: round2(top + STOREY) };
    }
    d.floors.push(floor);
    this.sel = { kind: "floor", i: d.floors.length - 1 };
    this.host._levelKept = floor.elevation;
  }

  // Whether anything lies on the floor: rooms, openings, stairs, scanners
  _used(key) {
    const d = this.draft;
    return (
      d.rooms.some((r) => r.floor === key) ||
      d.openings.some((o) => o[4] === key) ||
      d.stairs.some((s) => s.floor === key || s.to === key) ||
      this.host._plan.scanners.some((s) => (s.floor ?? d.floors[0]?.key) === key)
    );
  }

  // ---- Sheet ----

  sheet() {
    const h = this.host;
    const t = h._t;
    const tools = [
      ["select", t.edSelect],
      ["rect", t.edRect],
      ["poly", t.edPoly],
      ["door", t.edDoor],
      ["stairs", t.edStairs],
    ];
    const canStairs = this.draft.floors.length > 1;
    const toolRow = `<div class="edtools">${tools
      .map(([k, label]) => `<ha-button appearance="${this.tool === k ? "filled" : "plain"}" data-act="ed-tool" data-key="${k}"` +
        `${k === "stairs" && !canStairs ? " disabled" : ""}>${esc(label)}</ha-button>`)
      .join("")}</div>`;
    const hint = { select: t.edHintSelect, rect: t.edHintRect, poly: t.edHintPoly, door: t.edHintDoor, stairs: t.edHintStairs }[this.tool];
    const polyBtns = this.tool === "poly" && this.poly.length
      ? `${h._btn("ed-poly-done", t.edFinish, { disabled: this.poly.length < 3 })}${h._btn("ed-poly-cancel", t.cancel)}`
      : "";
    const head = h._card(t.edTitle, toolRow + `<div class="muted small">${esc(hint)}</div>` + (this.dirty ? "" : ""),
      `<span>${h._btn("ed-undo", t.edUndo, { disabled: !this.undo.length })}${polyBtns}</span>` +
      `<span>${h._btn("ed-cancel", t.edDiscardYes, { disabled: !this.dirty })}${h._btn("ed-save", t.save, { kind: "filled", disabled: !this.dirty })}</span>`);
    const confirm = this.confirmCancel
      ? `<ha-alert alert-type="warning">${esc(t.edDiscard)}` +
        `<ha-button slot="action" appearance="plain" data-act="ed-cancel-no">${esc(t.cancel)}</ha-button>` +
        `<ha-button slot="action" variant="danger" data-act="ed-cancel-yes">${esc(t.edDiscardYes)}</ha-button></ha-alert>`
      : "";
    return confirm + head + this._selectionCard() + this._floorsCard();
  }

  _selectionCard() {
    const h = this.host;
    const t = h._t;
    const d = this.draft;
    const sel = this.sel;
    if (!sel || sel.kind === "floor") return "";
    const floorOptions = d.floors.map((f) => ({ value: f.key, label: f.name || f.key }));
    const floorField = (name, label) => ({ name, label, required: true, selector: { select: { mode: "dropdown", options: floorOptions } } });
    const touch = () => {
      if (!this._edited) this._save();
      this._edited = true;
      this.dirty = true;
      h._drawEditor();
    };
    let title;
    let body;
    if (sel.kind === "room") {
      const r = d.rooms[sel.i];
      if (!r) return "";
      title = t.edRoomTitle;
      const schema = [
        { name: "name", label: t.name, selector: { text: {} } },
        { name: "area", label: t.edArea, selector: { area: {} } },
        ...(d.floors.length ? [floorField("floor", t.floor)] : []),
        { type: "grid", name: "", schema: [
          { name: "zone", label: t.edZone, selector: { boolean: {} } },
          { name: "outdoor", label: t.edOutdoor, selector: { boolean: {} } },
          { name: "label", label: t.edLabel, selector: { boolean: {} } },
        ] },
        ...(r.points ? [] : [{ type: "grid", name: "", schema: ["x", "y", "w", "h"].map((k) => h._num(k, k, "m")) }]),
      ];
      const data = { name: r.name, area: r.area ?? null, floor: r.floor || null, zone: !!r.zone, outdoor: !!r.outdoor, label: r.label !== false, x: r.x, y: r.y, w: r.w, h: r.h };
      body = h._formSlot("ed-room", schema, data, (v) => {
        touch();
        r.name = v.name ?? "";
        if (v.area) r.area = v.area;
        else delete r.area;
        if (v.floor) r.floor = v.floor;
        for (const k of ["zone", "outdoor"]) {
          if (v[k]) r[k] = true;
          else delete r[k];
        }
        if (v.label === false) r.label = false;
        else delete r.label;
        if (!r.points) {
          for (const k of ["x", "y"]) if (Number.isFinite(v[k])) r[k] = v[k];
          for (const k of ["w", "h"]) if (Number.isFinite(v[k]) && v[k] > 0) r[k] = v[k];
        }
      });
    } else if (sel.kind === "opening") {
      const o = d.openings[sel.i];
      if (!o) return "";
      title = t.edDoorTitle;
      const width = round2(dist([o[0], o[1]], [o[2], o[3]]));
      const schema = [h._num("width", t.edWidth, "m"), ...(d.floors.length ? [floorField("floor", t.floor)] : [])];
      body = h._formSlot("ed-opening", schema, { width, floor: o[4] || null }, (v) => {
        touch();
        if (v.floor) o[4] = v.floor;
        if (Number.isFinite(v.width) && v.width > 0.1) {
          const c = [(o[0] + o[2]) / 2, (o[1] + o[3]) / 2];
          const len = dist([o[0], o[1]], [o[2], o[3]]) || 1;
          const ux = (o[2] - o[0]) / len;
          const uy = (o[3] - o[1]) / len;
          const half = v.width / 2;
          [o[0], o[1], o[2], o[3]] = [c[0] - ux * half, c[1] - uy * half, c[0] + ux * half, c[1] + uy * half].map(round2);
        }
      });
    } else {
      const s = d.stairs[sel.i];
      if (!s) return "";
      title = t.edStairsTitle;
      body = h._formSlot("ed-stairs", [floorField("floor", t.edFrom), floorField("to", t.edTo)], { floor: s.floor, to: s.to }, (v) => {
        touch();
        if (v.floor && v.floor !== v.to) s.floor = v.floor;
        if (v.to && v.to !== s.floor) s.to = v.to;
      });
    }
    return h._card(title, body, `<span></span>${h._btn("ed-delete", t.delete, { kind: "danger" })}`);
  }

  _floorsCard() {
    const h = this.host;
    const t = h._t;
    const d = this.draft;
    if (!d.floors.length) {
      return h._card(t.edFloors, `<div class="muted small">${esc(t.edOneFloor)}</div>`,
        `<span></span><span>${h._btn("ed-add-floor", t.edAddFloor)}${h._btn("ed-add-building", t.edAddBuilding)}</span>`);
    }
    const level = h._level;
    const rows = d.floors
      .map((f, i) => ({ f, i }))
      .sort((a, b) => (a.f.building || "").localeCompare(b.f.building || "") || (b.f.elevation ?? 0) - (a.f.elevation ?? 0))
      .map(({ f, i }) => {
        const on = this.sel?.kind === "floor" && this.sel.i === i;
        const shown = (f.elevation ?? 0) === level;
        return `<tr class="edfloor${on ? " on" : ""}${shown ? " shown" : ""}" data-act="ed-floor" data-key="${i}">` +
          `<td>${esc(f.building || t.edMain)}</td><td>${esc(f.name || f.key)}</td><td class="n">${h._fmt(f.elevation ?? 0, 2)} m</td></tr>`;
      })
      .join("");
    let form = "";
    if (this.sel?.kind === "floor" && d.floors[this.sel.i]) {
      const f = d.floors[this.sel.i];
      form = h._formSlot("ed-floor", [
        { name: "name", label: t.name, selector: { text: {} } },
        { name: "building", label: t.edBuildingName, helper: t.edBuildingHelp, selector: { text: {} } },
        { type: "grid", name: "", schema: [h._num("elevation", t.edElevation, "m"), h._num("height", t.edHeight, "m", { min: 0.5 })] },
        { name: "ha_floor", label: t.edHaFloor, selector: { floor: {} } },
      ], { name: f.name, building: f.building, elevation: f.elevation ?? 0, height: f.height ?? 2.5, ha_floor: f.ha_floor ?? null }, (v) => {
        if (!this._edited) this._save();
        this._edited = true;
        this.dirty = true;
        f.name = v.name ?? "";
        f.building = v.building ?? "";
        if (Number.isFinite(v.elevation)) {
          f.elevation = v.elevation;
          h._levelKept = v.elevation;
        }
        if (Number.isFinite(v.height) && v.height >= 0.5) f.height = v.height;
        if (v.ha_floor) f.ha_floor = v.ha_floor;
        else delete f.ha_floor;
        h._drawEditor();
      });
    }
    const del = this.sel?.kind === "floor" && d.floors.length > 1 ? h._btn("ed-delete", t.delete, { kind: "danger" }) : "";
    return h._card(t.edFloors,
      `<div class="muted small">${esc(t.edFloorsHint)}</div>` +
      `<table class="data edfloors"><tr><th>${esc(t.edBuildingName)}</th><th>${esc(t.floor)}</th><th class="n">${esc(t.edElevation)}</th></tr>${rows}</table>` + form,
      `<span>${del}</span><span>${h._btn("ed-add-floor", t.edAddFloor)}${h._btn("ed-add-building", t.edAddBuilding)}</span>`);
  }

  // ---- Actions from the sheet ----

  act(act, key) {
    const h = this.host;
    const t = h._t;
    const d = this.draft;
    switch (act) {
      case "ed-tool":
        this.tool = key;
        this.poly = [];
        if (key !== "select") this.sel = null;
        return true;
      case "ed-undo":
        if (this.undo.length) {
          this.draft = JSON.parse(this.undo.pop());
          this.sel = null;
          this.dirty = true;
        }
        return true;
      case "ed-poly-done":
        this.finishPoly();
        return true;
      case "ed-poly-cancel":
        this.poly = [];
        return true;
      case "ed-floor":
        this.sel = { kind: "floor", i: Number(key) };
        this._edited = false;
        h._levelKept = d.floors[Number(key)]?.elevation ?? 0;
        return true;
      case "ed-add-floor":
      case "ed-add-building":
        this.addFloor(act === "ed-add-building");
        return true;
      case "ed-delete": {
        const sel = this.sel;
        if (!sel) return true;
        if (sel.kind === "floor") {
          const f = d.floors[sel.i];
          if (this._used(f.key)) {
            h._note = { kind: "err", text: t.edFloorUsed };
            return true;
          }
          this._save();
          d.floors.splice(sel.i, 1);
        } else {
          this._save();
          ({ room: d.rooms, opening: d.openings, stairs: d.stairs })[sel.kind].splice(sel.i, 1);
        }
        this.sel = null;
        return true;
      }
      case "ed-cancel":
        if (this.dirty) this.confirmCancel = true;
        else this.stop();
        return true;
      case "ed-cancel-no":
        this.confirmCancel = false;
        return true;
      case "ed-cancel-yes":
        this.stop();
        return true;
      default:
        return false;
    }
  }

  // Keys while drawing: Escape drops the polygon or the selection, Enter closes the polygon
  key(e) {
    if (!this.active) return false;
    if (e.key === "Escape") {
      if (this.poly.length) this.poly = [];
      else this.sel = null;
      return true;
    }
    if (e.key === "Enter" && this.poly.length >= 3) {
      this.finishPoly();
      return true;
    }
    return false;
  }

  // The levels the draft has, for the switch
  levels() {
    return levelsOf(this.plan());
  }
}

export const EDITOR_CSS = `
  .editor .eghost { fill: none; stroke: var(--secondary-text-color); stroke-width: 0.03; stroke-dasharray: 0.1 0.1; opacity: 0.5; pointer-events: none; }
  .editor .ehit { fill: transparent; stroke: none; cursor: pointer; pointer-events: all; }
  .editor .ehit.line { stroke: transparent; stroke-width: 0.35; }
  .editor .esel { fill: color-mix(in srgb, var(--primary-color) 10%, transparent); stroke: var(--primary-color); stroke-width: 0.06; pointer-events: none; }
  .editor .esel.door { stroke-width: 0.14; }
  .editor .ehandle { fill: var(--card-background-color); stroke: var(--primary-color); stroke-width: 0.05; cursor: move; }
  .editor .emid { fill: var(--primary-color); opacity: 0.55; cursor: copy; }
  .editor .epoly { fill: none; stroke: var(--primary-color); stroke-width: 0.05; stroke-dasharray: 0.12 0.08; }
  .editor .ept { fill: var(--primary-color); }
  .editor .ept.first { fill: var(--card-background-color); stroke: var(--primary-color); stroke-width: 0.05; }
  .editor .epreview { fill: color-mix(in srgb, var(--primary-color) 12%, transparent); stroke: var(--primary-color); stroke-width: 0.05; stroke-dasharray: 0.12 0.08; }
  .map.drawing svg:not(.mdi) { cursor: crosshair; touch-action: none; }
  .edtools { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
  table.edfloors tr.edfloor { cursor: pointer; }
  table.edfloors tr.edfloor.shown td { font-weight: var(--ha-font-weight-medium, 500); }
  table.edfloors tr.edfloor.on td { color: var(--primary-color); }
`;
