"""
ipc_main.py
───────────
IPC Visual Simulator — Main Application
Run: python ipc_main.py

Tabs:
  1. Pipe Simulator          — Writer → Pipe buffer → Reader
  2. Race Condition          — Unsync vs Sync shared memory counter
  3. Producer–Consumer       — Bounded buffer with semaphores

Each tab has:
  • Animated canvas showing data flow
  • Step-by-step event log with color coding
  • Play / Step / Reset controls
  • Speed slider
"""

import tkinter as tk
from tkinter import ttk, font
import math

from ipc_engine import (
    PipeSimulation,
    RaceSimulation,
    ProducerConsumerSimulation,
    Event,
)

# ── THEME ─────────────────────────────────────────────────────────────────────
BG       = "#0d0d1a"
PANEL    = "#111122"
TOOLBAR  = "#0a0a18"
FG       = "#e0e0f0"
ACCENT   = "#4fc3f7"
GREEN    = "#2ecc71"
RED      = "#e74c3c"
ORANGE   = "#e67e22"
PURPLE   = "#9b59b6"
BLUE     = "#3498db"
TEAL     = "#1abc9c"
YELLOW   = "#f1c40f"

FONT_TITLE = ("Courier New", 13, "bold")
FONT_BOLD  = ("Courier New", 10, "bold")
FONT_MONO  = ("Courier New", 10)
FONT_SMALL = ("Courier New", 9)

KIND_COLORS = {
    "write"       : BLUE,
    "read"        : GREEN,
    "block"       : ORANGE,
    "pipe_full"   : ORANGE,
    "pipe_empty"  : ORANGE,
    "acquire"     : PURPLE,
    "release"     : TEAL,
    "race_corrupt": RED,
    "shm_write"   : BLUE,
    "shm_read"    : GREEN,
    "signal"      : TEAL,
    "done"        : PURPLE,
}


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def make_label(parent, text, **kw):
    defaults = dict(bg=PANEL, fg=FG, font=FONT_MONO)
    defaults.update(kw)
    return tk.Label(parent, text=text, **defaults)


def make_btn(parent, text, cmd, color=ACCENT, **kw):
    return tk.Button(
        parent, text=text, command=cmd,
        bg=color, fg="#000000" if color in (YELLOW, GREEN, ACCENT) else FG,
        font=FONT_BOLD, relief=tk.FLAT, padx=10, pady=4,
        activebackground=color, cursor="hand2", **kw
    )


# ─────────────────────────────────────────────
#  BASE TAB
# ─────────────────────────────────────────────

class BaseTab(tk.Frame):
    def __init__(self, parent, title):
        super().__init__(parent, bg=BG)
        self._events   = []
        self._idx      = 0
        self._playing  = False
        self._after_id = None
        self._speed_ms = 400
        self._build_layout(title)

    def _build_layout(self, title):
        # Title bar
        title_bar = tk.Frame(self, bg=TOOLBAR, pady=8)
        title_bar.pack(fill=tk.X)
        tk.Label(title_bar, text=title, bg=TOOLBAR, fg=ACCENT,
                 font=FONT_TITLE).pack(side=tk.LEFT, padx=16)

        # Main split
        main = tk.Frame(self, bg=BG)
        main.pack(fill=tk.BOTH, expand=True)

        # Left — canvas
        left = tk.Frame(main, bg=BG)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(left, bg=BG, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Right — log + controls
        right = tk.Frame(main, bg=PANEL, width=320)
        right.pack(side=tk.RIGHT, fill=tk.Y)
        right.pack_propagate(False)

        self._build_controls(right)
        self._build_log(right)

        # bind resize
        self.canvas.bind("<Configure>", lambda e: self._draw_static())

    def _build_controls(self, parent):
        ctrl = tk.Frame(parent, bg=PANEL, pady=8)
        ctrl.pack(fill=tk.X, padx=8)

        make_label(parent, "Controls", font=FONT_BOLD, bg=TOOLBAR,
                   pady=4).pack(fill=tk.X)

        row1 = tk.Frame(ctrl, bg=PANEL)
        row1.pack(fill=tk.X, pady=4)
        self.play_btn = make_btn(row1, "▶ Play",  self._play,  GREEN)
        self.play_btn.pack(side=tk.LEFT, padx=2)
        make_btn(row1, "⏸ Pause", self._pause, ORANGE).pack(side=tk.LEFT, padx=2)
        make_btn(row1, "⏭ Step",  self._step,  BLUE  ).pack(side=tk.LEFT, padx=2)

        row2 = tk.Frame(ctrl, bg=PANEL)
        row2.pack(fill=tk.X, pady=4)
        make_btn(row2, "⟳ Reset",  self._reset,  RED   ).pack(side=tk.LEFT, padx=2)
        make_btn(row2, "⚡ Re-run", self._rerun,  PURPLE).pack(side=tk.LEFT, padx=2)

        # Speed
        spd_frame = tk.Frame(ctrl, bg=PANEL)
        spd_frame.pack(fill=tk.X, pady=(8, 0))
        make_label(spd_frame, "Speed:", bg=PANEL).pack(side=tk.LEFT)
        self.speed_var = tk.IntVar(value=400)
        tk.Scale(spd_frame, from_=50, to=1000, orient=tk.HORIZONTAL,
                 variable=self.speed_var, bg=PANEL, fg=FG, troughcolor=TOOLBAR,
                 highlightthickness=0, length=140,
                 command=lambda v: setattr(self, '_speed_ms', int(v))
                 ).pack(side=tk.LEFT, padx=4)

        # Tick counter
        self.tick_lbl = make_label(ctrl, "Tick: 0 / 0", bg=PANEL, fg=ACCENT)
        self.tick_lbl.pack(pady=4)

        # Status
        self.status_lbl = make_label(ctrl, "Press Play to start",
                                      bg=PANEL, fg=YELLOW, wraplength=280,
                                      justify=tk.LEFT)
        self.status_lbl.pack(fill=tk.X, pady=4)

    def _build_log(self, parent):
        make_label(parent, "Event Log", font=FONT_BOLD, bg=TOOLBAR,
                   pady=4).pack(fill=tk.X)
        log_frame = tk.Frame(parent, bg=PANEL)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.log = tk.Text(log_frame, bg="#08080f", fg=FG, font=FONT_SMALL,
                           state=tk.DISABLED, relief=tk.FLAT, wrap=tk.WORD,
                           insertbackground=FG)
        vsb = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=vsb.set)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # colour tags
        for kind, col in KIND_COLORS.items():
            self.log.tag_configure(kind, foreground=col)
        self.log.tag_configure("tick", foreground="#555577")
        self.log.tag_configure("note", foreground="#888899")

    # ── playback ──────────────────────────────

    def _play(self):
        if self._playing:
            return
        if not self._events:
            self._rerun()
        self._playing = True
        self._schedule()

    def _pause(self):
        self._playing = False
        if self._after_id:
            self.after_cancel(self._after_id)

    def _step(self):
        self._pause()
        self._advance()

    def _reset(self):
        self._pause()
        self._idx = 0
        self.log.config(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.config(state=tk.DISABLED)
        self.tick_lbl.config(text="Tick: 0 / 0")
        self.status_lbl.config(text="Reset. Press Play.")
        self._draw_static()

    def _rerun(self):
        self._reset()
        self._generate_events()
        self.tick_lbl.config(text=f"Tick: 0 / {len(self._events)}")

    def _schedule(self):
        if self._playing and self._idx < len(self._events):
            self._advance()
            self._after_id = self.after(self._speed_ms, self._schedule)
        else:
            self._playing = False

    def _advance(self):
        if self._idx >= len(self._events):
            return
        ev = self._events[self._idx]
        self._idx += 1
        self.tick_lbl.config(text=f"Tick: {self._idx} / {len(self._events)}")
        self._log_event(ev)
        self._animate_event(ev)
        self.status_lbl.config(text=ev.note or ev.kind, fg=ev.color)

    def _log_event(self, ev: Event):
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, f"[{ev.tick:03d}] ", "tick")
        label = f"{ev.actor}→{ev.target} "
        self.log.insert(tk.END, label, ev.kind)
        self.log.insert(tk.END, f"{ev.value}\n", ev.kind)
        if ev.note:
            self.log.insert(tk.END, f"      {ev.note}\n", "note")
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)

    # ── override in subclass ──────────────────
    def _generate_events(self): pass
    def _draw_static(self):     pass
    def _animate_event(self, ev: Event): pass


# ─────────────────────────────────────────────
#  TAB 1: PIPE SIMULATOR
# ─────────────────────────────────────────────

class PipeTab(BaseTab):
    def __init__(self, parent):
        self.sim = PipeSimulation(n_messages=14)
        super().__init__(parent, "① PIPE SIMULATOR — Writer → Buffer → Reader")
        self._generate_events()

    def _generate_events(self):
        self._events = self.sim.run()

    def _draw_static(self):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width() or 700
        h = c.winfo_height() or 400

        # Background grid
        _draw_grid(c, w, h)

        # Writer box
        self._wr_x, self._wr_y = 80, h // 2
        _draw_process_box(c, self._wr_x, self._wr_y, "Writer\n[P0]", BLUE)

        # Reader box
        self._rd_x, self._rd_y = w - 80, h // 2
        _draw_process_box(c, self._rd_x, self._rd_y, "Reader\n[P1]", GREEN)

        # Pipe buffer slots
        self._slot_xs = []
        cap = PipeSimulation.BUFFER_CAP
        pipe_w = (w - 320) * 0.55
        start_x = w // 2 - pipe_w // 2
        slot_w  = pipe_w / cap
        slot_h  = 44
        py      = h // 2

        for i in range(cap):
            sx = start_x + i * slot_w + slot_w / 2
            self._slot_xs.append(sx)
            c.create_rectangle(sx - slot_w/2 + 3, py - slot_h//2,
                                sx + slot_w/2 - 3, py + slot_h//2,
                                outline=ACCENT, fill="#0a0a20", width=1,
                                tags=f"slot_{i}")
            c.create_text(sx, py + slot_h//2 + 12, text=str(i),
                          fill="#333355", font=FONT_SMALL)

        # Arrow Writer→Pipe
        c.create_line(self._wr_x + 48, self._wr_y,
                      start_x, py,
                      fill=BLUE, width=2, arrow=tk.LAST, dash=(6, 3))
        # Arrow Pipe→Reader
        c.create_line(start_x + pipe_w, py,
                      self._rd_x - 48, self._rd_y,
                      fill=GREEN, width=2, arrow=tk.LAST, dash=(6, 3))

        # Labels
        c.create_text(w // 2, py - 60, text="PIPE  BUFFER",
                      fill=ACCENT, font=FONT_BOLD)
        c.create_text(w // 2, py + 60,
                      text=f"Capacity: {cap} slots",
                      fill="#555577", font=FONT_SMALL)

        self._pipe_center_x = w // 2
        self._pipe_y        = py
        self._pipe_start_x  = start_x
        self._pipe_end_x    = start_x + pipe_w
        self._slot_w        = slot_w
        self._slot_h        = slot_h

        # Stats area
        self._stats_y = py + 90
        self._stats_x = w // 2

    def _animate_event(self, ev: Event):
        c = self.canvas
        c.delete("packet")
        c.delete("highlight_slot")
        c.delete("stats")

        # Rebuild slot display from events up to current idx
        buf = []
        for e in self._events[:self._idx]:
            if e.kind == "write":
                buf.append(e.value)
            elif e.kind == "read" and buf:
                buf.pop(0)

        # Draw buffer contents
        cap = PipeSimulation.BUFFER_CAP
        for i in range(cap):
            sx = self._slot_xs[i]
            py = self._pipe_y
            sh = self._slot_h
            sw = self._slot_w
            fill = "#0a0a20"
            txt  = ""
            col  = "#333355"
            if i < len(buf):
                fill = "#0a2040"
                txt  = buf[i]
                col  = ACCENT
            c.create_rectangle(sx - sw/2 + 3, py - sh//2,
                                sx + sw/2 - 3, py + sh//2,
                                outline=ACCENT, fill=fill, width=1,
                                tags="highlight_slot")
            if txt:
                c.create_text(sx, py, text=txt, fill=col,
                              font=FONT_SMALL, tags="highlight_slot")

        # Animate packet movement
        if ev.kind == "write":
            # packet flying from writer into pipe
            tx = self._slot_xs[min(len(buf)-1, cap-1)] if buf else self._pipe_start_x
            _fly_packet(c, self._wr_x + 48, self._wr_y, tx, self._pipe_y,
                        ev.value, BLUE)
        elif ev.kind == "read":
            _fly_packet(c, self._pipe_start_x, self._pipe_y,
                        self._rd_x - 48, self._rd_y, ev.value, GREEN)
        elif ev.kind in ("pipe_full", "pipe_empty"):
            # flash warning on pipe
            c.create_rectangle(
                self._pipe_start_x, self._pipe_y - self._slot_h,
                self._pipe_end_x,   self._pipe_y + self._slot_h,
                outline=ORANGE, fill="", width=3, tags="packet"
            )

        # Stats
        c.create_text(self._stats_x, self._stats_y,
                      text=f"Sent: {sum(1 for e in self._events[:self._idx] if e.kind=='write')}  "
                           f"Received: {sum(1 for e in self._events[:self._idx] if e.kind=='read')}  "
                           f"Buffered: {len(buf)}",
                      fill=FG, font=FONT_SMALL, tags="stats")


# ─────────────────────────────────────────────
#  TAB 2: RACE CONDITION
# ─────────────────────────────────────────────

class RaceTab(BaseTab):
    def __init__(self, parent):
        self.sim = RaceSimulation(n_processes=3, increments_each=5)
        self._mode = "unsync"   # or "sync"
        super().__init__(parent, "② RACE CONDITION — Shared Memory Corruption vs Semaphore Fix")
        self._build_mode_buttons()
        self._generate_events()

    def _build_mode_buttons(self):
        # insert mode buttons at top of right panel
        pass

    def _build_controls(self, parent):
        # Mode toggle
        mode_frame = tk.Frame(parent, bg=TOOLBAR, pady=6)
        mode_frame.pack(fill=tk.X)
        make_label(mode_frame, "Mode:", bg=TOOLBAR, fg=ACCENT,
                   font=FONT_BOLD).pack(side=tk.LEFT, padx=8)
        self.mode_var = tk.StringVar(value="unsync")
        for txt, val, col in [("⚠ Unsynchronized", "unsync", RED),
                               ("✔ Semaphore Fix",  "sync",   GREEN)]:
            tk.Radiobutton(
                mode_frame, text=txt, variable=self.mode_var, value=val,
                bg=TOOLBAR, fg=col, selectcolor=BG, font=FONT_SMALL,
                activebackground=TOOLBAR,
                command=self._mode_changed
            ).pack(side=tk.LEFT, padx=4)

        super()._build_controls(parent)

    def _mode_changed(self):
        self._mode = self.mode_var.get()
        self._reset()
        self._generate_events()

    def _generate_events(self):
        self._mode = self.mode_var.get() if hasattr(self, 'mode_var') else "unsync"
        if self._mode == "unsync":
            self._events, self._final, self._expected = \
                self.sim.run_unsynchronized()
        else:
            self._events, self._final, self._expected = \
                self.sim.run_synchronized()
        self.tick_lbl.config(text=f"Tick: 0 / {len(self._events)}")

    def _draw_static(self):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width() or 700
        h = c.winfo_height() or 400
        _draw_grid(c, w, h)

        n = self.sim.n_processes
        self._proc_positions = []
        for i in range(n):
            angle = math.pi * (i / (n - 1) if n > 1 else 0.5) + math.pi / 6
            px = int(w * 0.18 + 40 * math.cos(angle * 2))
            py = int(h * 0.2 + (h * 0.6 / (n - 1)) * i if n > 1 else h // 2)
            self._proc_positions.append((px, py))
            _draw_process_box(c, px, py, f"P{i}", BLUE)

        # Shared memory box
        self._shm_x = int(w * 0.55)
        self._shm_y = h // 2
        c.create_rectangle(self._shm_x - 60, self._shm_y - 40,
                           self._shm_x + 60, self._shm_y + 40,
                           fill="#1a0a0a", outline=RED, width=2)
        c.create_text(self._shm_x, self._shm_y - 55,
                      text="SHARED MEMORY", fill=RED, font=FONT_BOLD)
        self._shm_val_tag = "shm_val"

        # Semaphore box (only shown in sync mode)
        self._sem_x = int(w * 0.55)
        self._sem_y = h // 4
        if self._mode == "sync":
            c.create_rectangle(self._sem_x - 50, self._sem_y - 28,
                               self._sem_x + 50, self._sem_y + 28,
                               fill="#0a001a", outline=PURPLE, width=2)
            c.create_text(self._sem_x, self._sem_y - 42,
                          text="SEMAPHORE S", fill=PURPLE, font=FONT_BOLD)

        # Counter bar background
        bar_x = int(w * 0.75)
        self._bar_x    = bar_x
        self._bar_top  = h * 0.1
        self._bar_bot  = h * 0.9
        self._bar_w    = 36
        c.create_rectangle(bar_x - self._bar_w//2, self._bar_top,
                           bar_x + self._bar_w//2, self._bar_bot,
                           fill="#0a0a0a", outline="#333355", width=1)
        c.create_text(bar_x, self._bar_bot + 16,
                      text="Counter", fill=FG, font=FONT_SMALL)
        c.create_text(bar_x, self._bar_top - 16,
                      text=f"Max: {self.sim.n_processes * self.sim.increments_each}",
                      fill=FG, font=FONT_SMALL)

    def _animate_event(self, ev: Event):
        c = self.canvas
        c.delete("dynamic")

        # Current counter value
        cur_counter = 0
        for e in self._events[:self._idx]:
            if e.kind in ("shm_write", "race_corrupt"):
                try:
                    cur_counter = int(e.value.split("→")[1])
                except:
                    pass

        expected = self.sim.n_processes * self.sim.increments_each

        # SHM value display
        col = RED if ev.kind == "race_corrupt" else GREEN
        c.create_rectangle(self._shm_x - 60, self._shm_y - 40,
                           self._shm_x + 60, self._shm_y + 40,
                           fill="#1a0a0a" if ev.kind == "race_corrupt" else "#0a1a0a",
                           outline=col, width=3, tags="dynamic")
        c.create_text(self._shm_x, self._shm_y,
                      text=str(cur_counter),
                      fill=col, font=("Courier New", 22, "bold"),
                      tags="dynamic")

        # Semaphore state
        if self._mode == "sync":
            sem_col = TEAL if ev.kind == "release" else PURPLE
            sem_txt = "S=1 (free)" if ev.kind == "release" else "S=0 (locked)"
            c.create_rectangle(self._sem_x - 50, self._sem_y - 28,
                               self._sem_x + 50, self._sem_y + 28,
                               fill="#0a001a", outline=sem_col, width=2,
                               tags="dynamic")
            c.create_text(self._sem_x, self._sem_y,
                          text=sem_txt, fill=sem_col, font=FONT_SMALL,
                          tags="dynamic")

        # Arrow from active process
        try:
            pidx = int(ev.actor[1])
            if pidx < len(self._proc_positions):
                px, py = self._proc_positions[pidx]
                col2 = RED if ev.kind == "race_corrupt" else ev.color
                c.create_line(px + 48, py, self._shm_x - 60, self._shm_y,
                              fill=col2, width=2, arrow=tk.LAST,
                              tags="dynamic", dash=(4, 2))
        except:
            pass

        # Counter bar fill
        ratio = min(cur_counter / max(expected, 1), 1.0)
        bar_h = (self._bar_bot - self._bar_top) * ratio
        bar_col = GREEN if cur_counter == expected and self._idx == len(self._events) else \
                  RED   if cur_counter > expected else BLUE
        c.create_rectangle(
            self._bar_x - self._bar_w//2,
            self._bar_bot - bar_h,
            self._bar_x + self._bar_w//2,
            self._bar_bot,
            fill=bar_col, outline="", tags="dynamic"
        )
        c.create_text(self._bar_x, self._bar_bot - bar_h - 12,
                      text=str(cur_counter),
                      fill=bar_col, font=FONT_BOLD, tags="dynamic")

        # Final verdict
        if ev.kind == "done":
            verdict = f"✔ CORRECT ({cur_counter}={expected})" \
                if cur_counter == expected else \
                f"✘ CORRUPTED ({cur_counter}≠{expected})"
            vcol = GREEN if cur_counter == expected else RED
            c.create_text(self._shm_x, self._shm_y + 70,
                          text=verdict, fill=vcol,
                          font=("Courier New", 12, "bold"), tags="dynamic")


# ─────────────────────────────────────────────
#  TAB 3: PRODUCER–CONSUMER
# ─────────────────────────────────────────────

class ProducerConsumerTab(BaseTab):
    def __init__(self, parent):
        self.sim = ProducerConsumerSimulation(buffer_size=5, n_produce=12)
        super().__init__(parent, "③ PRODUCER–CONSUMER — Bounded Buffer + Semaphores")
        self._generate_events()

    def _generate_events(self):
        self._events = self.sim.run()
        self.tick_lbl.config(text=f"Tick: 0 / {len(self._events)}")

    def _draw_static(self):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width() or 700
        h = c.winfo_height() or 400
        _draw_grid(c, w, h)

        # Producer
        self._prod_x, self._prod_y = 75, h // 2
        _draw_process_box(c, self._prod_x, self._prod_y, "Producer\n[P0]", BLUE)

        # Consumer
        self._cons_x, self._cons_y = w - 75, h // 2
        _draw_process_box(c, self._cons_x, self._cons_y, "Consumer\n[P1]", GREEN)

        # Buffer slots
        cap    = self.sim.buffer_size
        buf_w  = (w - 320) * 0.5
        slot_w = buf_w / cap
        slot_h = 52
        bx     = w // 2 - buf_w // 2
        by     = h // 2

        self._buf_slots = []
        for i in range(cap):
            sx = bx + i * slot_w + slot_w / 2
            self._buf_slots.append(sx)
            c.create_rectangle(sx - slot_w/2 + 3, by - slot_h//2,
                                sx + slot_w/2 - 3, by + slot_h//2,
                                outline=ACCENT, fill="#0a0a20", width=1,
                                tags=f"bslot_{i}")

        self._bx      = bx
        self._bx_end  = bx + buf_w
        self._by      = by
        self._slot_w  = slot_w
        self._slot_h  = slot_h

        # Semaphore labels
        c.create_text(w//2, by - 80, text="BOUNDED BUFFER", fill=ACCENT, font=FONT_BOLD)
        self._sem_y   = by + 80
        self._sem_x   = w // 2

        # Arrows
        c.create_line(self._prod_x + 48, by, bx, by,
                      fill=BLUE, width=2, arrow=tk.LAST, dash=(6,3))
        c.create_line(self._bx_end, by, self._cons_x - 48, by,
                      fill=GREEN, width=2, arrow=tk.LAST, dash=(6,3))

    def _animate_event(self, ev: Event):
        c = self.canvas
        c.delete("dyn")

        # Reconstruct buffer
        buf = []
        prod_count = 0
        cons_count = 0
        for e in self._events[:self._idx]:
            if e.kind == "write" and e.actor == "Producer":
                buf.append(e.value)
                prod_count += 1
            elif e.kind == "read" and e.actor == "Consumer" and buf:
                buf.pop(0)
                cons_count += 1

        # Draw slots
        cap = self.sim.buffer_size
        for i in range(cap):
            sx = self._buf_slots[i]
            by = self._by
            sh = self._slot_h
            sw = self._slot_w
            filled = i < len(buf)
            c.create_rectangle(sx - sw/2+3, by-sh//2, sx+sw/2-3, by+sh//2,
                                fill="#0a2040" if filled else "#0a0a20",
                                outline=ACCENT, width=1, tags="dyn")
            if filled:
                c.create_text(sx, by, text=buf[i],
                              fill=ACCENT, font=FONT_SMALL, tags="dyn")

        # Semaphore display
        empty_s = cap - len(buf)
        full_s  = len(buf)
        c.create_text(self._sem_x, self._sem_y,
                      text=f"Semaphore: empty={empty_s}  full={full_s}",
                      fill=PURPLE, font=FONT_BOLD, tags="dyn")

        # Packet animation
        if ev.kind == "write":
            _fly_packet(c, self._prod_x+48, self._prod_y,
                        self._buf_slots[min(len(buf)-1, cap-1)], self._by,
                        ev.value, BLUE, tag="dyn")
        elif ev.kind == "read":
            _fly_packet(c, self._bx, self._by,
                        self._cons_x-48, self._cons_y,
                        ev.value, GREEN, tag="dyn")
        elif ev.kind == "block":
            actor_x = self._prod_x if ev.actor == "Producer" else self._cons_x
            c.create_text(actor_x, self._prod_y - 60,
                          text="⏸ BLOCKED", fill=ORANGE,
                          font=FONT_BOLD, tags="dyn")

        # Stats
        c.create_text(self._sem_x, self._sem_y + 30,
                      text=f"Produced: {prod_count}   Consumed: {cons_count}",
                      fill=FG, font=FONT_SMALL, tags="dyn")

        if ev.kind == "done":
            c.create_text(self._sem_x, self._sem_y + 60,
                          text="✔ All items transferred correctly!",
                          fill=GREEN, font=FONT_BOLD, tags="dyn")


# ─────────────────────────────────────────────
#  DRAWING HELPERS
# ─────────────────────────────────────────────

def _draw_grid(c, w, h):
    for x in range(0, w, 40):
        c.create_line(x, 0, x, h, fill="#111122", width=1)
    for y in range(0, h, 40):
        c.create_line(0, y, w, y, fill="#111122", width=1)


def _draw_process_box(c, x, y, label, color):
    r = 44
    c.create_oval(x-r, y-r, x+r, y+r, fill="#0a0a20", outline=color, width=2)
    c.create_text(x, y, text=label, fill=color, font=FONT_SMALL,
                  justify=tk.CENTER)


def _fly_packet(c, x1, y1, x2, y2, label, color, tag="packet"):
    mx = (x1 + x2) / 2
    my = (y1 + y2) / 2 - 20
    # draw a bezier-like arc using a line
    c.create_line(x1, y1, mx, my, x2, y2,
                  fill=color, width=2, smooth=True,
                  arrow=tk.LAST, tags=tag)
    c.create_oval(mx-14, my-14, mx+14, my+14,
                  fill="#0a0a20", outline=color, width=2, tags=tag)
    c.create_text(mx, my, text=label, fill=color, font=FONT_SMALL, tags=tag)


# ─────────────────────────────────────────────
#  MAIN APP
# ─────────────────────────────────────────────

class IPCApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("IPC Visual Simulator — Pipes · Shared Memory · Semaphores")
        self.geometry("1180x700")
        self.configure(bg=BG)
        self.minsize(900, 580)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook",       background=TOOLBAR, borderwidth=0)
        style.configure("TNotebook.Tab",   background=PANEL, foreground=FG,
                        font=FONT_BOLD, padding=(14, 6))
        style.map("TNotebook.Tab",
                  background=[("selected", BG)],
                  foreground=[("selected", ACCENT)])
        style.configure("TScrollbar", background=PANEL, troughcolor=BG,
                        borderwidth=0, arrowcolor=ACCENT)

        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True)

        nb.add(PipeTab(nb),             text="  ① PIPE  ")
        nb.add(RaceTab(nb),             text="  ② RACE  ")
        nb.add(ProducerConsumerTab(nb), text="  ③ PROD-CONS  ")


if __name__ == "__main__":
    app = IPCApp()
    app.mainloop()