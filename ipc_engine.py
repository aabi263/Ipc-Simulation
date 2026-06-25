"""
ipc_engine.py
─────────────
Core simulation engine for the IPC Visual Simulator.

Simulates:
  1. PIPE       — unidirectional byte stream between writer/reader processes
  2. SHARED MEM — multiple processes read/write a shared integer counter
  3. RACE       — unsynchronized shared memory (shows corruption)
  4. SEMAPHORE  — synchronized shared memory using a counting semaphore

All simulation is event-driven: each 'tick' produces a list of events
that the GUI can animate. No real OS calls — pure Python simulation.
"""

import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional


# ─────────────────────────────────────────────
#  EVENT  (one animatable action)
# ─────────────────────────────────────────────

@dataclass
class Event:
    tick      : int
    kind      : str          # "write" | "read" | "block" | "signal" | "acquire" |
                             # "release" | "race_corrupt" | "race_ok" | "shm_write" |
                             # "shm_read" | "pipe_full" | "pipe_empty" | "done"
    actor     : str          # process name e.g. "Writer" / "P0"
    target    : str          # destination e.g. "Pipe" / "SHM"
    value     : str          # data being sent/received
    color     : str = "#ffffff"
    note      : str = ""     # extra annotation


# ─────────────────────────────────────────────
#  PIPE SIMULATION
# ─────────────────────────────────────────────

class PipeSimulation:
    """
    Simulates a pipe between one Writer and one Reader.
    Writer produces tokens; pipe has finite buffer; reader consumes.
    Shows blocking when pipe is full or empty.
    """

    BUFFER_CAP = 6

    def __init__(self, n_messages=12):
        self.n_messages = n_messages
        self.reset()

    def reset(self):
        self.pipe_buffer : deque = deque()
        self.events      : List[Event] = []
        self.tick        = 0
        self.written     = 0
        self.read        = 0

    def run(self):
        self.reset()
        writer_done = False
        reader_done = False

        while not (writer_done and reader_done):
            self.tick += 1

            # Writer turn
            if not writer_done:
                if len(self.pipe_buffer) < self.BUFFER_CAP:
                    msg = f"MSG{self.written}"
                    self.pipe_buffer.append(msg)
                    self.written += 1
                    self.events.append(Event(
                        tick=self.tick, kind="write",
                        actor="Writer", target="Pipe",
                        value=msg, color="#3498db",
                        note=f"buffer={len(self.pipe_buffer)}/{self.BUFFER_CAP}"
                    ))
                    if self.written >= self.n_messages:
                        writer_done = True
                else:
                    self.events.append(Event(
                        tick=self.tick, kind="pipe_full",
                        actor="Writer", target="Pipe",
                        value="[BLOCKED]", color="#e67e22",
                        note="Pipe full — Writer blocks"
                    ))

            # Reader turn
            if not reader_done:
                if self.pipe_buffer:
                    msg = self.pipe_buffer.popleft()
                    self.read += 1
                    self.events.append(Event(
                        tick=self.tick, kind="read",
                        actor="Reader", target="Pipe",
                        value=msg, color="#2ecc71",
                        note=f"buffer={len(self.pipe_buffer)}/{self.BUFFER_CAP}"
                    ))
                    if self.read >= self.n_messages:
                        reader_done = True
                else:
                    self.events.append(Event(
                        tick=self.tick, kind="pipe_empty",
                        actor="Reader", target="Pipe",
                        value="[BLOCKED]", color="#e67e22",
                        note="Pipe empty — Reader blocks"
                    ))

            if self.tick > 200:   # safety
                break

        self.events.append(Event(
            tick=self.tick + 1, kind="done",
            actor="System", target="Pipe",
            value="EOF", color="#9b59b6",
            note="All messages transferred"
        ))
        return self.events


# ─────────────────────────────────────────────
#  SHARED MEMORY — RACE CONDITION SIMULATION
# ─────────────────────────────────────────────

class RaceSimulation:
    """
    Simulates the classic race condition:
    N processes each increment a shared counter M times.
    Without sync: read-modify-write is not atomic → corruption.
    With semaphore: all increments are serialized → correct result.
    """

    def __init__(self, n_processes=3, increments_each=5):
        self.n_processes    = n_processes
        self.increments_each = increments_each

    def run_unsynchronized(self):
        """Returns events showing corrupted counter."""
        events = []
        counter = 0
        expected = self.n_processes * self.increments_each
        tick = 0

        # Simulate interleaved non-atomic read-modify-write
        ops = []
        for p in range(self.n_processes):
            for _ in range(self.increments_each):
                ops.append(f"P{p}")
        random.shuffle(ops)

        for op in ops:
            tick += 1
            old_val = counter
            # Simulate preemption: occasionally another process reads same old value
            if random.random() < 0.35 and tick > 1:
                # race: read stale value
                stale = max(0, counter - random.randint(1, 2))
                new_val = stale + 1
                counter = new_val
                events.append(Event(
                    tick=tick, kind="race_corrupt",
                    actor=op, target="SHM",
                    value=f"{old_val}→{new_val}",
                    color="#e74c3c",
                    note=f"⚠ RACE! Read stale={stale}, wrote {new_val} (expected {old_val+1})"
                ))
            else:
                counter += 1
                events.append(Event(
                    tick=tick, kind="shm_write",
                    actor=op, target="SHM",
                    value=f"{old_val}→{counter}",
                    color="#3498db",
                    note=f"Read {old_val}, wrote {counter}"
                ))

        events.append(Event(
            tick=tick+1, kind="done",
            actor="System", target="SHM",
            value=str(counter),
            color="#e74c3c" if counter != expected else "#2ecc71",
            note=f"Final={counter}, Expected={expected} {'✘ CORRUPTED' if counter!=expected else '✔ OK'}"
        ))
        return events, counter, expected

    def run_synchronized(self):
        """Returns events showing correct counter with semaphore."""
        events = []
        counter = 0
        semaphore = 1   # binary semaphore (mutex)
        expected = self.n_processes * self.increments_each
        tick = 0

        ops = []
        for p in range(self.n_processes):
            for _ in range(self.increments_each):
                ops.append(f"P{p}")
        random.shuffle(ops)

        for op in ops:
            tick += 1
            # Acquire semaphore
            events.append(Event(
                tick=tick, kind="acquire",
                actor=op, target="SEM",
                value="wait(S)",
                color="#9b59b6",
                note=f"{op} acquires semaphore → S=0"
            ))
            tick += 1
            old_val = counter
            counter += 1
            events.append(Event(
                tick=tick, kind="shm_write",
                actor=op, target="SHM",
                value=f"{old_val}→{counter}",
                color="#2ecc71",
                note=f"Critical section: {old_val}+1={counter}"
            ))
            tick += 1
            events.append(Event(
                tick=tick, kind="release",
                actor=op, target="SEM",
                value="signal(S)",
                color="#1abc9c",
                note=f"{op} releases semaphore → S=1"
            ))

        events.append(Event(
            tick=tick+1, kind="done",
            actor="System", target="SHM",
            value=str(counter),
            color="#2ecc71",
            note=f"Final={counter}, Expected={expected} ✔ CORRECT"
        ))
        return events, counter, expected


# ─────────────────────────────────────────────
#  PRODUCER–CONSUMER (Pipe + Semaphore)
# ─────────────────────────────────────────────

class ProducerConsumerSimulation:
    """
    Classic producer-consumer with bounded buffer.
    Uses two semaphores: empty (slots available) and full (items available).
    Shows blocking producers and consumers.
    """

    def __init__(self, buffer_size=4, n_produce=10):
        self.buffer_size = buffer_size
        self.n_produce   = n_produce

    def run(self):
        events = []
        buffer = deque()
        empty  = self.buffer_size   # semaphore: empty slots
        full   = 0                  # semaphore: filled slots
        tick   = 0
        produced = 0
        consumed = 0

        while consumed < self.n_produce:
            tick += 1

            # Producer
            if produced < self.n_produce:
                if empty > 0:
                    empty -= 1
                    item = f"I{produced}"
                    buffer.append(item)
                    full += 1
                    produced += 1
                    events.append(Event(
                        tick=tick, kind="write",
                        actor="Producer", target="Buffer",
                        value=item, color="#3498db",
                        note=f"empty={empty} full={full} buf={list(buffer)}"
                    ))
                else:
                    events.append(Event(
                        tick=tick, kind="block",
                        actor="Producer", target="Buffer",
                        value="[WAIT]", color="#e67e22",
                        note="Buffer full — Producer blocks on empty semaphore"
                    ))

            # Consumer
            if full > 0:
                full -= 1
                item = buffer.popleft()
                empty += 1
                consumed += 1
                events.append(Event(
                    tick=tick, kind="read",
                    actor="Consumer", target="Buffer",
                    value=item, color="#2ecc71",
                    note=f"empty={empty} full={full} buf={list(buffer)}"
                ))
            else:
                if produced >= self.n_produce:
                    break
                events.append(Event(
                    tick=tick, kind="block",
                    actor="Consumer", target="Buffer",
                    value="[WAIT]", color="#e67e22",
                    note="Buffer empty — Consumer blocks on full semaphore"
                ))

            if tick > 300:
                break

        events.append(Event(
            tick=tick+1, kind="done",
            actor="System", target="Buffer",
            value=f"{consumed} items",
            color="#9b59b6",
            note=f"All {consumed} items produced & consumed correctly"
        ))
        return events