# IPC Visual Simulator

An interactive Python/Tkinter application that visually simulates four core Inter-Process Communication (IPC) mechanisms used in operating systems.

## IPC Mechanisms Covered

| Tab | Mechanism | System Calls |
|-----|-----------|--------------|
| 🔵 Pipe | Unidirectional kernel buffer | `read()`, `write()` |
| 🟣 Shared Memory | Direct mapped memory region | `mmap()`, `shmget()` |
| 🟠 Semaphore | Counting semaphore (value=3) | `wait()`, `signal()` |
| 🟢 Message Queue | FIFO typed message queue | `msgsnd()`, `msgrcv()` |

## Features
- Live animation of data movement between processes
- Colour-coded process states (writing, reading, blocked)
- Real-time log output with step-by-step details
- Start / Stop / Reset controls per mechanism
- Threading simulation (no actual OS processes — educational visual)

## Requirements
```
Python 3.8+
tkinter (included in standard library)
```

## Run
```bash
python main.py
```


