---
marp: true
html: true
---
# Why you should use AnyIO — Part 1 of 3

### asyncio != async/await and Structured Concurrency

https://graingert.co.uk/why-anyio-already

<!-- Part 1 of 3 -->

---

# About Me

<img src="https://avatars.githubusercontent.com/u/413772" alt="graingert" style="display: block; margin: 0 auto;" width="150">

<style scoped>section { font-size: 22px; }</style>

**Networking & async:**
- Core developer of AnyIO, Twisted, and Trio
- CPython triager — asyncio fixes: `TaskGroup` cancellation + refcycles, `asyncio.Timeout` zero-deadline delivery, `staggered_race` task leaks, happy eyeballs refcycles, `sock_connect` UDP
- Proposed asyncio child watcher deprecation (3.12); contributed to asyncio policy system deprecation (3.14)

**Other open source:**
- Member of `PyPy`, `pytest-dev`, `PyCQA`, `Dask`, `jazzband`, `sqlalchemy-redshift`, `canvg` orgs
- Mars 2020 Helicopter Mission contributor
- 1 CVE security advisory credit

<!-- I'm Thomas Grainger, graingert on GitHub. I'm a core dev on AnyIO, Twisted, and Trio. I've contributed to CPython asyncio itself - the happy eyeballs implementation and various TaskGroup fixes. -->

---

<style scoped>section{font-size:22px; padding-top:10px;}</style>

# Part 1 Contents

* `asyncio` != `async`/`await` — the most important take-away (generators all the way down)
* What is AnyIO? How it dispatches. Callables, not coroutines
* The problems with `asyncio.create_task()` — it's a go statement
  * Problem 1: functions aren't black boxes anymore
  * Problem 2: resource cleanup breaks
  * Problem 3: error handling breaks
  * Root cause: unstructured concurrency + real-world consequences
* The fix: structured concurrency with task groups
* Key Takeaway — `asyncio.TaskGroup` too, but not all the way
* Getting a result from a task with `nonlocal`
* "But I want to return without waiting!" — FastAPI lifespan pattern
* Further Reading
* Why you probably already have AnyIO installed

---

# asyncio != async/await

*This is the most important take-away of this presentation*

- `async`/`await` is syntactic sugar over generators - completely decoupled from any event loop
- `async`/`await` also doesn't require async I/O — it's just a way to write coroutines
- **Three separate things:** async I/O (the concept) · `asyncio` (Python's stdlib module) · `async`/`await` (the syntax)
- Twisted, Trio, and Curio all use `async`/`await` with their own event loops
- You can even use `async`/`await` with no event loop at all

<!-- async/await is NOT asyncio. it's just syntax built on top of the generator protocol. any framework can drive coroutines - Twisted, Trio, Curio all do it with completely different event loops. and as I'll show you, you don't even need an event loop. -->

---

# No event loop required

```python
import types

@types.coroutine
def _async_yield(v):
    return (yield v)

async def async_range():
    await _async_yield(1)
    await _async_yield(2)
    await _async_yield(3)
```

<!-- @types.coroutine: marks a generator function as a coroutine function. When the function is called, the resulting generator iterator is also considered a coroutine object and is awaitable. Bridges yield-from generators with async/await. _async_yield is a raw coroutine that just yields a value. async_range is a normal async function built on top - no asyncio anywhere. -->

---

# It's generators all the way down

```python
coro = async_range()
gen = coro.__await__()
list(gen)  # [1, 2, 3]  - no asyncio, no event loop
```

<!-- grab the __await__ iterator, drain it into a list. that's it. no event loop, no scheduler, just generators. this is how multiple async frameworks can coexist - they're all just driving the same generator protocol underneath. -->

---

# Further Reading: Generator Tricks

- [Generator Tricks for Systems Programmers](https://graingert.co.uk/dabeaz-gen) - `graingert.co.uk/dabeaz-gen`
- [A Curious Course on Coroutines and Concurrency](https://graingert.co.uk/dabeaz-coro) - `graingert.co.uk/dabeaz-coro`
- [Generators: The Final Frontier](https://graingert.co.uk/dabeaz-final) - `graingert.co.uk/dabeaz-final`

<!-- if you want to go deeper on generators, David Beazley's talks are brilliant. these three progressively build from basic generators to full coroutine-based concurrency. -->

---

# What is AnyIO?

**AnyIO is a structured concurrency and I/O library** that works on top of asyncio and Trio.

- **Structured concurrency** — task groups that guarantee tasks can't outlive their scope
- **Level-triggered cancellation** — timeouts that actually work
- **Batteries included** — streams, paths, subprocesses, pytest plugin
- **Incrementally adoptable** — drop it into an existing asyncio codebase; your code automatically works on Trio too

Think of it as: the async standard library that Python should have shipped.

---

# How AnyIO Dispatches to the Right Backend

- Uses `sniffio` to detect which async framework is currently running
- Dispatches to the right backend API - asyncio or Trio
- Similar in approach to `six` (the Python 2/3 compatibility library): write once, run on both

<!-- so how does AnyIO work? it uses sniffio to detect which async framework is running, then dispatches to the right API. similar to how the old `six` library worked for Python 2/3 compat - write once, run on both asyncio and Trio. -->

---

# Callables, Not Coroutines

Trio and AnyIO never require you to create a coroutine — you pass async functions, the framework calls them:

```python
# AnyIO / Trio - pass the function itself ✅
tg.start_soon(myfunc)
anyio.run(main)   # OR trio.run(main) - pick one based on your backend
```

```python
# asyncio - pass a coroutine object ❌
asyncio.create_task(myfunc())
asyncio.run(main())           # note: coroutine, not the function
```

No bare coroutine objects → no `RuntimeWarning: coroutine '...' was never awaited`

<!-- start_soon takes myfunc, not myfunc(). the Trio tutorial deliberately never mentions "coroutine" - you don't need to understand coroutine objects to use structured concurrency. bonus: since you never create coroutine objects yourself, you can't forget to await them. -->

---

# The Problems with `asyncio.create_task()`

## It's a "go statement" - and go statements break everything

<!-- ok this is the core of the talk. asyncio.create_task is what njs calls a "go statement". it's a one-way jump that splits control flow and it's fundamentally broken for the same reasons goto was broken. -->

---

# What's a "go statement"?

```python
# asyncio
asyncio.create_task(myfunc())  # Fire and forget!
# Control returns immediately, myfunc() runs in background
# Golang
go myfunc()  // Same thing
# Python threads  
threading.Thread(target=myfunc).start()  # Also same
```

**Key problem:** Control flow splits with **one-way jump**

-   Parent returns immediately
-   Child jumps to myfunc and runs unsupervised
-   No guaranteed reunion point

<!-- it's the same pattern everywhere - asyncio.create_task, Go's `go` keyword, threading.Thread.start. parent spawns a child and immediately moves on. child runs off unsupervised. no guaranteed reunion point. this one-way jump is the root of all the problems. -->

---

# Problem 1: Functions Aren't Black Boxes Anymore

```python
async def process_data(data):
    # Does this function spawn background tasks?
    # Are they still running after it returns?
    # You have NO IDEA without reading all the source code!
    await some_library_function(data)
    # Function returned... but is it done? 🤷
```

**You can't reason locally about control flow**

Every function call might secretly spawn tasks that outlive the function

<!-- this is devastating for maintainability. when you call a function you have no idea whether it spawned background tasks still running after it returns. you'd have to read every line of source, transitively, to know. completely breaks functions as black boxes. -->

---

# Problem 2: Resource Cleanup Breaks

```python
# This LOOKS safe... (pseudocode)
async with aopen("data.csv") as f:
    await process_file(f)

# File closed here... right?
# But what if process_file did this:
async def process_file(f):
    asyncio.create_task(read_data(f))  # Background task!
    return  # Function returns immediately
# Now: file is CLOSED while background task still uses it
# 💥 Error! (if you're lucky)
```

**The language can't help you with automatic cleanup**

<!-- concrete example. you open a file in an async with block, pass the handle to process_file, block exits, file closes. but if process_file secretly spawned a background task still reading from that handle - boom, error on a closed file. async with can't protect you because it doesn't know about the orphaned task. context managers are broken. -->

---

# Problem 3: Error Handling Breaks

```python
async def background_task():
    raise ValueError("Something went wrong!")

# Start background task
task = asyncio.create_task(background_task())
# Error happens... but where does it go?
# Answer: NOWHERE! It's silently dropped!
# (Maybe printed to console if you're lucky)
```

<!-- errors in background tasks have nowhere to go. in sync Python, exceptions propagate up the call stack automatically. but a fire-and-forget task is an orphan - the error gets silently dropped. maybe asyncio prints a warning to the console if you're lucky, but your program keeps running in a broken state. -->

---

# Why Errors Can't Propagate

**Exceptions can't propagate because there's no stack to unwind**

Compare to regular Python:

```python
def my_function():
    raise ValueError("Something went wrong!")

my_function()  # Exception propagates to caller automatically
```

<!-- compare: in sync Python when a function raises, the exception propagates to the caller. that's just how the call stack works. create_task breaks this. -->

---

# The Root Cause: Unstructured Concurrency

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 290" font-family="'Courier New', monospace" width="700" style="display: block; margin: 0 auto;">
  <defs>
    <style>
      @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&amp;display=swap');
    </style>
    <!-- Light background -->
    <linearGradient id="asyncio-create-task-bgGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#f6f8fa"/>
      <stop offset="100%" stop-color="#ffffff"/>
    </linearGradient>
    <!-- Parent task box gradient -->
    <linearGradient id="asyncio-create-task-parentGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#60a5fa"/>
      <stop offset="100%" stop-color="#3b82f6"/>
    </linearGradient>
    <!-- Child task box gradient -->
    <linearGradient id="asyncio-create-task-childGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#fca5a5"/>
      <stop offset="100%" stop-color="#f87171"/>
    </linearGradient>
    <!-- Glow filter for parent (no-op on light bg) -->
    <filter id="asyncio-create-task-blueGlow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="2" result="blur"/>
      <feComposite in="SourceGraphic" in2="blur" operator="over"/>
    </filter>
    <!-- Glow filter for child (no-op on light bg) -->
    <filter id="asyncio-create-task-redGlow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="2" result="blur"/>
      <feComposite in="SourceGraphic" in2="blur" operator="over"/>
    </filter>
    <!-- Arrow markers -->
    <marker id="asyncio-create-task-arrowBlue" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#3b82f6"/>
    </marker>
    <marker id="asyncio-create-task-arrowRed" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#ef4444"/>
    </marker>
    <marker id="asyncio-create-task-arrowGreen" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#16a34a"/>
    </marker>
    <marker id="asyncio-create-task-arrowDashed" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#9ca3af"/>
    </marker>
  </defs>
  <!-- Background -->
  <rect width="520" height="290" fill="url(#asyncio-create-task-bgGrad)" rx="12"/>
  <!-- Subtle grid lines -->
  <g opacity="0.04" stroke="#3b82f6" stroke-width="1">
    <line x1="0" y1="40" x2="520" y2="40"/>
    <line x1="0" y1="80" x2="520" y2="80"/>
    <line x1="0" y1="120" x2="520" y2="120"/>
    <line x1="0" y1="160" x2="520" y2="160"/>
    <line x1="0" y1="200" x2="520" y2="200"/>
    <line x1="0" y1="240" x2="520" y2="240"/>
    <line x1="0" y1="280" x2="520" y2="280"/>
  </g>
  <!-- Title -->
  <text x="260" y="34" text-anchor="middle" fill="#1f2328" font-size="13" font-weight="700" font-family="'Courier New', monospace" letter-spacing="0.5">asyncio.create_task() control flow</text>
  <line x1="20" y1="44" x2="500" y2="44" stroke="#d0d7de" stroke-width="1"/>
  <!-- ── Parent task box ── -->
  <rect x="175" y="60" width="170" height="58" rx="6" fill="#dbeafe" filter="url(#asyncio-create-task-blueGlow)" opacity="0.95"/>
  <rect x="175" y="60" width="170" height="58" rx="6" fill="none" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="260" y="85" text-anchor="middle" fill="#1f2328" font-size="13" font-weight="700" font-family="'Courier New', monospace">Parent</text>
  <text x="260" y="104" text-anchor="middle" fill="#1e40af" font-size="12" font-family="'Courier New', monospace">task</text>
  <!-- Arrow down from parent to fork -->
  <line x1="260" y1="118" x2="260" y2="155" stroke="#3b82f6" stroke-width="2" marker-end="url(#asyncio-create-task-arrowBlue)"/>
  <!-- create_task() label -->
  <rect x="188" y="127" width="145" height="22" rx="4" fill="#f8fafc" opacity="0.7"/>
  <text x="260" y="142" text-anchor="middle" fill="#ea580c" font-size="12" font-family="'Courier New', monospace" font-weight="600">create_task()</text>
  <!-- Fork horizontal line -->
  <line x1="155" y1="168" x2="365" y2="168" stroke="#3b82f6" stroke-width="2"/>
  <!-- Left branch down (parent) -->
  <line x1="185" y1="168" x2="185" y2="205" stroke="#3b82f6" stroke-width="2" marker-end="url(#asyncio-create-task-arrowBlue)"/>
  <!-- Right branch down (child) -->
  <line x1="335" y1="168" x2="335" y2="205" stroke="#ef4444" stroke-width="2" marker-end="url(#asyncio-create-task-arrowRed)"/>
  <!-- ── Parent returns box ── -->
  <rect x="105" y="210" width="160" height="52" rx="6" fill="#f8fafc" stroke="#d1d5db" stroke-width="1.5"/>
  <text x="185" y="233" text-anchor="middle" fill="#57606a" font-size="12" font-family="'Courier New', monospace">Parent</text>
  <text x="185" y="252" text-anchor="middle" fill="#16a34a" font-size="12" font-family="'Courier New', monospace" font-weight="600">returns ✓</text>
  <!-- ── Child task box ── -->
  <rect x="255" y="205" width="160" height="58" rx="6" fill="#fecdd3" filter="url(#asyncio-create-task-redGlow)" opacity="0.95"/>
  <rect x="255" y="205" width="160" height="58" rx="6" fill="none" stroke="#ef4444" stroke-width="1.5"/>
  <text x="335" y="230" text-anchor="middle" fill="#991b1b" font-size="13" font-weight="700" font-family="'Courier New', monospace">Child</text>
  <text x="335" y="250" text-anchor="middle" fill="#991b1b" font-size="10" font-family="'Courier New', monospace">(orphaned, unsupervised)</text>
  <!-- Arrow right from child to myfunc() -->
  <line x1="415" y1="234" x2="460" y2="234" stroke="#ef4444" stroke-width="2" marker-end="url(#asyncio-create-task-arrowRed)"/>
  <!-- myfunc() pill -->
  <rect x="460" y="220" width="44" height="28" rx="14" fill="#f8fafc" stroke="#ef4444" stroke-width="1.5"/>
  <text x="482" y="238" text-anchor="middle" fill="#ef4444" font-size="9" font-family="'Courier New', monospace" font-weight="600">myfunc</text>
  <!-- Corner decoration -->
  <text x="14" y="284" fill="#9ca3af" font-size="10" font-family="'Courier New', monospace">asyncio</text>
  <text x="448" y="284" fill="#9ca3af" font-size="10" font-family="'Courier New', monospace">CPython</text>
</svg>

⚠ no await, no supervision, no cancellation - exceptions silently swallowed

consider: `anyio.create_task_group()` for structured concurrency

<!-- this diagram shows it. create_task launches a task that runs off on its own with no structural connection back to the parent. no guaranteed reunion point. unstructured concurrency - the concurrent equivalent of goto spaghetti. -->

---

# Real-World Consequences

### In asyncio programs:

❌ **Resource leaks** - Files/sockets stay open because cleanup is manual\
❌ **Silent failures** - Errors in background tasks get dropped\
❌ **Shutdown hangs** - Can't wait for "done" because tasks are invisible\
❌ **Operations on closed files** - Tasks outlive the data they operate on

### In data pipelines specifically:

❌ **Timeouts don't work** - Can't cancel tasks you've lost track of\
❌ **Can't reason about code** - Every function is a potential landmine

<!-- these aren't theoretical. people hit these in production every day. resource leaks, silent failures, shutdown hangs, operations on closed files. and for data pipelines: timeouts are meaningless because you can't cancel tasks you've lost track of. -->

---

# Structured Concurrency with Task Groups

*"structured" = tasks have a guaranteed reunion point with their parent*

```python
# asyncio - UNSTRUCTURED (bad)
async def unstructured():
    asyncio.create_task(myfunc())  # Fire and forget
    asyncio.create_task(other())   # Where do errors go?
    return  # Are we done? Who knows!

# AnyIO - STRUCTURED (good)
async def structured():
    async with anyio.create_task_group() as tg:
        tg.start_soon(myfunc)
        tg.start_soon(other)
    # BLOCKED HERE until all tasks finish
    # All errors propagated automatically
    # All cleanup happens automatically
    return  # NOW we're actually done
```

<!-- here's the fix: task groups. you can't exit the async with block until ALL child tasks have finished. errors propagate automatically. cleanup happens automatically. when the function returns, it's actually done. this is structured concurrency - same revolution that if/while/for brought to control flow. -->

---

<style scoped>section { padding-top: 40px; }</style>

# The Fix: Structured Concurrency

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 750 445" font-family="'Courier New', monospace" width="700" style="display: block; margin: 0 auto;">
  <defs>
    <linearGradient id="anyio-create-task-group-bgGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#f6f8fa"/>
      <stop offset="100%" stop-color="#ffffff"/>
    </linearGradient>
    <linearGradient id="anyio-create-task-group-parentGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#60a5fa"/>
      <stop offset="100%" stop-color="#3b82f6"/>
    </linearGradient>
    <linearGradient id="anyio-create-task-group-childGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#86efac"/>
      <stop offset="100%" stop-color="#4ade80"/>
    </linearGradient>
    <linearGradient id="anyio-create-task-group-tgGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#a78bfa"/>
      <stop offset="100%" stop-color="#8b5cf6"/>
    </linearGradient>
    <linearGradient id="anyio-create-task-group-exitGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#fbbf24"/>
      <stop offset="100%" stop-color="#f59e0b"/>
    </linearGradient>
    <filter id="anyio-create-task-group-blueGlow">
      <feGaussianBlur stdDeviation="2" result="blur"/>
      <feComposite in="SourceGraphic" in2="blur" operator="over"/>
    </filter>
    <filter id="anyio-create-task-group-greenGlow">
      <feGaussianBlur stdDeviation="2" result="blur"/>
      <feComposite in="SourceGraphic" in2="blur" operator="over"/>
    </filter>
    <filter id="anyio-create-task-group-purpleGlow">
      <feGaussianBlur stdDeviation="2" result="blur"/>
      <feComposite in="SourceGraphic" in2="blur" operator="over"/>
    </filter>
    <marker id="anyio-create-task-group-arrowBlue" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#3b82f6"/>
    </marker>
    <marker id="anyio-create-task-group-arrowGreen" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#16a34a"/>
    </marker>
    <marker id="anyio-create-task-group-arrowPurple" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#7c3aed"/>
    </marker>
    <marker id="anyio-create-task-group-arrowGold" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#d97706"/>
    </marker>
  </defs>
  <!-- Background -->
  <rect width="750" height="445" fill="url(#anyio-create-task-group-bgGrad)" rx="12"/>
  <!-- Subtle grid -->
  <g opacity="0.035" stroke="#16a34a" stroke-width="1">
    <line x1="0" y1="40"  x2="750" y2="40"/>
    <line x1="0" y1="80"  x2="750" y2="80"/>
    <line x1="0" y1="120" x2="750" y2="120"/>
    <line x1="0" y1="160" x2="750" y2="160"/>
    <line x1="0" y1="200" x2="750" y2="200"/>
    <line x1="0" y1="240" x2="750" y2="240"/>
    <line x1="0" y1="280" x2="750" y2="280"/>
    <line x1="0" y1="320" x2="750" y2="320"/>
    <line x1="0" y1="360" x2="750" y2="360"/>
    <line x1="0" y1="400" x2="750" y2="400"/>
    <line x1="0" y1="440" x2="750" y2="440"/>
  </g>
  <!-- Title -->
  <text x="375" y="32" text-anchor="middle" fill="#1f2328" font-size="13" font-weight="700" font-family="'Courier New', monospace" letter-spacing="0.5">anyio.create_task_group() control flow</text>
  <line x1="20" y1="52" x2="730" y2="52" stroke="#d0d7de" stroke-width="1"/>
  <!-- ── Parent task box ── center=375 -->
  <rect x="290" y="66" width="170" height="54" rx="6" fill="#dbeafe" filter="url(#anyio-create-task-group-blueGlow)" opacity="0.95"/>
  <rect x="290" y="66" width="170" height="54" rx="6" fill="none" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="375" y="89" text-anchor="middle" fill="#1f2328" font-size="13" font-weight="700" font-family="'Courier New', monospace">Parent task</text>
  <text x="375" y="108" text-anchor="middle" fill="#1e40af" font-size="10" font-family="'Courier New', monospace">async def main():</text>
  <!-- Arrow down: parent → async with -->
  <line x1="375" y1="120" x2="375" y2="148" stroke="#3b82f6" stroke-width="2" marker-end="url(#anyio-create-task-group-arrowBlue)"/>
  <!-- ── async with create_task_group() ── center=375 -->
  <rect x="210" y="152" width="330" height="42" rx="6" fill="#ede9fe" filter="url(#anyio-create-task-group-purpleGlow)" opacity="0.95"/>
  <rect x="210" y="152" width="330" height="42" rx="6" fill="none" stroke="#7c3aed" stroke-width="1.5"/>
  <text x="375" y="170" text-anchor="middle" fill="#4c1d95" font-size="11" font-weight="700" font-family="'Courier New', monospace">async with</text>
  <text x="375" y="186" text-anchor="middle" fill="#4c1d95" font-size="11" font-family="'Courier New', monospace">create_task_group() as tg</text>
  <!-- Arrow down from TaskGroup to fork (through start_soon labels) -->
  <line x1="375" y1="194" x2="375" y2="248" stroke="#7c3aed" stroke-width="2"/>
  <!-- tg.start_soon labels on the arrow -->
  <rect x="249" y="200" width="252" height="40" rx="4" fill="#f8fafc" opacity="0.82"/>
  <text x="375" y="216" text-anchor="middle" fill="#ea580c" font-size="11" font-family="'Courier New', monospace" font-weight="600">tg.start_soon(task1)</text>
  <text x="375" y="233" text-anchor="middle" fill="#ea580c" font-size="11" font-family="'Courier New', monospace" font-weight="600">tg.start_soon(task2)</text>
  <!-- Fork horizontal line: y=248, x=70 to x=680 -->
  <line x1="70" y1="248" x2="680" y2="248" stroke="#7c3aed" stroke-width="2"/>
  <!-- Left branch: parent continues at x=145 -->
  <line x1="145" y1="248" x2="145" y2="280" stroke="#3b82f6" stroke-width="2" marker-end="url(#anyio-create-task-group-arrowBlue)"/>
  <!-- Center branch: child 1 at x=375 -->
  <line x1="375" y1="248" x2="375" y2="280" stroke="#16a34a" stroke-width="2" marker-end="url(#anyio-create-task-group-arrowGreen)"/>
  <!-- Right branch: child 2 at x=610 -->
  <line x1="610" y1="248" x2="610" y2="280" stroke="#16a34a" stroke-width="2" marker-end="url(#anyio-create-task-group-arrowGreen)"/>
  <!-- ── Parent body continues ── center=145 -->
  <rect x="56" y="283" width="178" height="52" rx="6" fill="#f8fafc" stroke="#3b82f6" stroke-width="1.5" stroke-dasharray="6,3"/>
  <text x="145" y="304" text-anchor="middle" fill="#57606a" font-size="11" font-family="'Courier New', monospace">Parent body continues</text>
  <text x="145" y="323" text-anchor="middle" fill="#3b82f6" font-size="10" font-family="'Courier New', monospace">(runs concurrently)</text>
  <!-- ── Child task 1 ── center=375 -->
  <rect x="285" y="283" width="180" height="55" rx="6" fill="#dcfce7" filter="url(#anyio-create-task-group-greenGlow)" opacity="0.95"/>
  <rect x="285" y="283" width="180" height="55" rx="6" fill="none" stroke="#16a34a" stroke-width="1.5"/>
  <text x="375" y="307" text-anchor="middle" fill="#14532d" font-size="13" font-weight="700" font-family="'Courier New', monospace">Child task 1</text>
  <text x="375" y="325" text-anchor="middle" fill="#14532d" font-size="11" font-family="'Courier New', monospace">→ task1()</text>
  <!-- ── Child task 2 ── center=610 -->
  <rect x="520" y="283" width="180" height="55" rx="6" fill="#dcfce7" filter="url(#anyio-create-task-group-greenGlow)" opacity="0.95"/>
  <rect x="520" y="283" width="180" height="55" rx="6" fill="none" stroke="#16a34a" stroke-width="1.5"/>
  <text x="610" y="307" text-anchor="middle" fill="#14532d" font-size="13" font-weight="700" font-family="'Courier New', monospace">Child task 2</text>
  <text x="610" y="325" text-anchor="middle" fill="#14532d" font-size="11" font-family="'Courier New', monospace">→ task2()</text>
  <!-- Convergence lines -->
  <line x1="145" y1="335" x2="145" y2="363" stroke="#3b82f6" stroke-width="2"/>
  <line x1="375" y1="338" x2="375" y2="363" stroke="#16a34a" stroke-width="2"/>
  <line x1="610" y1="338" x2="610" y2="363" stroke="#16a34a" stroke-width="2"/>
  <line x1="145" y1="363" x2="610" y2="363" stroke="#d97706" stroke-width="2"/>
  <line x1="375" y1="363" x2="375" y2="380" stroke="#d97706" stroke-width="2" marker-end="url(#anyio-create-task-group-arrowGold)"/>
  <!-- Barrier wait label -->
  <rect x="262" y="344" width="226" height="19" rx="4" fill="#f8fafc" opacity="0.85"/>
  <text x="375" y="357" text-anchor="middle" fill="#d97706" font-size="10" font-family="'Courier New', monospace" font-weight="600">__aexit__ waits for all tasks</text>
  <!-- ── TaskGroup exit / reunion ── center=375 -->
  <rect x="210" y="383" width="330" height="42" rx="6" fill="#fef3c7" opacity="0.95"/>
  <rect x="210" y="383" width="330" height="42" rx="6" fill="none" stroke="#d97706" stroke-width="1.5"/>
  <text x="375" y="401" text-anchor="middle" fill="#78350f" font-size="11" font-weight="700" font-family="'Courier New', monospace">TaskGroup exits cleanly</text>
  <text x="375" y="417" text-anchor="middle" fill="#78350f" font-size="10" font-family="'Courier New', monospace">all tasks joined ✓</text>
  <!-- Corner labels -->
  <text x="14" y="439" fill="#9ca3af" font-size="10" font-family="'Courier New', monospace">anyio</text>
  <text x="683" y="439" fill="#9ca3af" font-size="10" font-family="'Courier New', monospace">trio/asyncio</text>
</svg>

✓ structured concurrency - no orphaned tasks

cancellation · exception propagation · task supervision included

<!-- compare this with the previous diagram. tasks are contained within the task group scope. they fan out, do work, fan back in. structured and predictable. -->

---

# Key Takeaway

**`asyncio.create_task()` is the `goto` of concurrency**

-   It's powerful
-   It seems convenient
-   **It breaks everything**

**AnyIO task groups are the `if/while/for` of concurrency**

-   Tasks can't outlive their scope
-   They preserve abstractions
-   They make the language features work again
-   **They let you reason about your code**

<!-- this is the slide I want you to remember. create_task is goto. task groups are if/while/for. if someone told you to use goto today you'd laugh. start treating create_task the same way. -->

---

# "But asyncio has TaskGroup too!"

Yes! Python 3.11 added `asyncio.TaskGroup`. But:

- Still uses **edge-triggered cancellation** (as we'll see shortly, this causes real bugs)
- Bugfixes are tied to your Python version — not backported (3.13 fixed deadlocks that still exist in 3.11/3.12)
- No `CancelScope(shield=True)` — can't shield cleanup work from cancellation
- No `start()` — can't wait for a task to signal it's ready

`asyncio.TaskGroup` is a step forward. AnyIO takes it the rest of the way.

<!-- you're probably thinking "asyncio has TaskGroup too, why do I need AnyIO?" and yes, Python 3.11 added asyncio.TaskGroup. but it still uses edge-triggered cancellation, which as I'll show you causes real bugs including deadlocks. bugfixes are tied to your Python version. and it's missing CancelScope(shield=True) and start(). asyncio.TaskGroup is progress, but AnyIO finishes the job. -->

---

<style scoped>section { padding-top: 20px; }</style>

# Getting a Result from a Task

```python
async def fetch_both(url1: str, url2: str) -> tuple[str, str]:
    result1: str | None = None
    result2: str | None = None

    async def get1() -> None:
        nonlocal result1
        result1 = await fetch(url1)

    async def get2() -> None:
        nonlocal result2
        result2 = await fetch(url2)

    async with anyio.create_task_group() as tg:
        tg.start_soon(get1)
        tg.start_soon(get2)
    # both tasks are done - results are ready
    assert result1 is not None
    assert result2 is not None
    return result1, result2
```

<!-- tasks can't return values directly, but you can close over a nonlocal variable. each inner function sets its nonlocal when it finishes. after the task group exits, both results are guaranteed to be set - structured concurrency gives you that guarantee for free. -->

---

# "But I want to return without waiting!"

Sometimes you genuinely need to kick off work and respond immediately - e.g. a web endpoint that accepts a job and returns `202 Accepted`.

The answer: a **long-lived task group** scoped to the application lifetime.

---

<style scoped>section { padding-top: 20px; }</style>

# An Example with FastAPI

```python
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import TypedDict
import anyio.abc

class State(TypedDict):
    tg: anyio.abc.TaskGroup

class ProcessResponse(BaseModel):
    status: str

class Done(Exception): pass

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[State]:
    try:
        async with anyio.create_task_group() as tg:
            yield State(tg=tg)
            raise Done
    except* Done:
        pass

app = FastAPI(lifespan=lifespan)

@app.post("/process", status_code=202)
async def process(data: str, request: Request[State]) -> ProcessResponse:
    request.state["tg"].start_soon(background_job, data)
    return ProcessResponse(status="accepted")
```

<!-- the task group lives for the lifetime of the app. individual requests can start_soon without waiting - fire and forget from the endpoint's point of view. but the tasks are still supervised: errors propagate, and on shutdown the lifespan context waits for all tasks to finish before the server exits. -->

---

# Zooming in: the lifespan context

```python
class Done(Exception): pass

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[State]:
    try:
        async with anyio.create_task_group() as tg:
            yield State(tg=tg)
            raise Done
    except* Done:
        pass
```

<!-- `yield` - app is running, tasks can be started. `raise Done` - on shutdown, raises Done inside the task group, which wraps it in an ExceptionGroup. `except* Done` - the except* syntax unpacks the ExceptionGroup and handles Done branches, cleanly absorbing the shutdown signal so it doesn't propagate as an error. -->

---

# Zooming in: the lifespan context (alternative)

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[State]:
    async with anyio.create_task_group() as tg:
        yield State(tg=tg)
        tg.cancel_scope.cancel()
```

<!-- simpler alternative: cancel_scope.cancel() directly cancels the task group's scope on shutdown, so child tasks receive Cancelled and stop immediately. no exception propagates out of the async with block - no except* needed. this is the idiomatic AnyIO way to stop a task group. the Done/except* version is more verbose but demonstrates Python 3.11's ExceptionGroup and except* syntax, which is worth knowing for error handling in concurrent code. both approaches cancel in-flight tasks rather than waiting for them to finish. -->

---

# "But I want to return without waiting!" (continued)

- On Trio: `trio.lowlevel.spawn_system_task()` spawns into a system nursery (Trio's name for a TaskGroup) that lives for the entire `trio.run()`
- AnyIO can't provide a portable `anyio.spawn_system_task()` - asyncio has no equivalent global supervised task group, only the unstructured `asyncio.create_task()`

<!-- trio has spawn_system_task for this pattern natively. anyio can't abstract over it because asyncio has no equivalent - there's no global supervised nursery, only the unstructured create_task. the FastAPI lifespan pattern is the asyncio-compatible solution. -->

---

# Further Reading

**Nathaniel J. Smith (Trio author):**\
["Notes on structured concurrency, or: Go statement considered harmful"](https://graingert.co.uk/trio-sc)\
`graingert.co.uk/trio-sc`

**Original Dijkstra paper:**\
["Go To Statement Considered Harmful" (1968)](https://graingert.co.uk/dijkstra68)\
`graingert.co.uk/dijkstra68`

<!-- njs's blog post is the definitive argument for structured concurrency. and Dijkstra's original paper is a surprisingly easy read - it's only a page long. -->

---

Normally at this stage of my talk I'd ask you to go run

# ~~pip install anyio~~

but if you're in this room you probably already have it in your virtual
environments!

<!-- normally at this point I'd tell you to go pip install AnyIO. but that's the punchline - you probably already have it. if you've installed httpx, FastAPI, Jupyter, MCP, or any number of popular packages, AnyIO is already in your virtualenv. -->

---

# Demo: You Already Have It

```sh
$ pip install httpx fastapi jupyter mcp pipdeptree
$ pipdeptree -p anyio -r  # reverse dependencies (dependants) of anyio
```

Watch the tree unfold: loads of packages you use daily depend on AnyIO

<!-- try this yourself. install a few common packages and run pipdeptree in reverse mode for AnyIO. you'll see a massive dependency tree. -->

---

<style scoped>section { padding-top: 20px; }</style>

# `pipdeptree` Output
```
anyio==4.12.1
├── starlette==0.52.1 [requires: anyio>=3.6.2,<5]
│   ├── fastapi==0.129.0 [requires: starlette>=0.40.0,<1.0.0]
│   ├── mcp==1.26.0 [requires: starlette>=0.27]
│   └── sse-starlette==3.2.0 [requires: starlette>=0.49.1]
│       └── mcp==1.26.0 [requires: sse-starlette>=1.6.1]
├── httpx==0.28.1 [requires: anyio]
│   ├── mcp==1.26.0 [requires: httpx>=0.27.1]
│   └── jupyterlab==4.5.4 [requires: httpx>=0.25.0,<1]
│       ├── notebook==7.5.3 [requires: jupyterlab>=4.5.3,<4.6]
│       │   └── jupyter==1.1.1 [requires: notebook]
│       └── jupyter==1.1.1 [requires: jupyterlab]
├── mcp==1.26.0 [requires: anyio>=4.5]
├── sse-starlette==3.2.0 [requires: anyio>=4.7.0]
│   └── mcp==1.26.0 [requires: sse-starlette>=1.6.1]
└── jupyter_server==2.17.0 [requires: anyio>=3.1.0]
    ├── notebook==7.5.3 [requires: jupyter_server>=2.4.0,<3]
    │   └── jupyter==1.1.1 [requires: notebook]
    ├── jupyter-lsp==2.3.0 [requires: jupyter_server>=1.1.2]
    │   └── jupyterlab==4.5.4 [requires: jupyter-lsp>=2.0.0]
    │       ├── notebook==7.5.3 [requires: jupyterlab>=4.5.3,<4.6]
    │       │   └── jupyter==1.1.1 [requires: notebook]
    │       └── jupyter==1.1.1 [requires: jupyterlab]
    ├── jupyterlab==4.5.4 [requires: jupyter_server>=2.4.0,<3]
    │   ├── notebook==7.5.3 [requires: jupyterlab>=4.5.3,<4.6]
    │   │   └── jupyter==1.1.1 [requires: notebook]
    │   └── jupyter==1.1.1 [requires: jupyterlab]
    ├── jupyterlab_server==2.28.0 [requires: jupyter_server>=1.21,<3]
    │   ├── notebook==7.5.3 [requires: jupyterlab_server>=2.28.0,<3]
    │   │   └── jupyter==1.1.1 [requires: notebook]
    │   └── jupyterlab==4.5.4 [requires: jupyterlab_server>=2.28.0,<3]
    │       ├── notebook==7.5.3 [requires: jupyterlab>=4.5.3,<4.6]
    │       │   └── jupyter==1.1.1 [requires: notebook]
    │       └── jupyter==1.1.1 [requires: jupyterlab]
    └── notebook_shim==0.2.4 [requires: jupyter_server>=1.8,<3]
        ├── notebook==7.5.3 [requires: notebook_shim>=0.2,<0.3]
        │   └── jupyter==1.1.1 [requires: notebook]
        └── jupyterlab==4.5.4 [requires: notebook_shim>=0.2]
            ├── notebook==7.5.3 [requires: jupyterlab>=4.5.3,<4.6]
            │   └── jupyter==1.1.1 [requires: notebook]
            └── jupyter==1.1.1 [requires: jupyterlab]
```

<!-- look at this tree. starlette, FastAPI, MCP, httpx, Jupyter - they all depend on AnyIO. if you're using any modern Python web framework or data science tool you already have it installed. might as well use it. -->

---

# If you've installed any of these...

- `httpx` - the HTTP client
- `fastapi` - async web framework
- `jupyter` - data science notebooks
- `mcp` - Anthropic's Model Context Protocol SDK

...AnyIO was already there.

<!-- the point isn't just that it's popular - it's that you've been benefiting from AnyIO's correctness guarantees without knowing it. might as well start using it intentionally. -->

---

# Wrap Up

* remember: `asyncio` != `async`/`await` - other async frameworks exist (Twisted, Trio, Curio) and AnyIO works across asyncio and Trio
* I've given you a whistle-stop tour of some of my favourite features, there's loads more
   * and more being added all the time
* I hope I've persuaded you to give AnyIO a try
* you might as well give it a go if you already have it installed

<!-- to wrap up: asyncio is not the only async framework - async/await is decoupled from any event loop and other frameworks like Twisted, Trio, and Curio all use the same syntax. AnyIO works across asyncio and Trio. structured concurrency, level-triggered cancellation, great batteries. you've probably already got it installed. give it a go. -->

---

<style scoped>section { font-size: 21px; }</style>

# Any questions?

**These slides:** [graingert.co.uk/why-anyio-already](https://graingert.co.uk/why-anyio-already)

**Further reading:**
- [anyio.readthedocs.io](https://anyio.readthedocs.io) — AnyIO documentation
- [graingert.co.uk/dabeaz-gen](https://graingert.co.uk/dabeaz-gen) — Generator Tricks for Systems Programmers
- [graingert.co.uk/dabeaz-coro](https://graingert.co.uk/dabeaz-coro) — A Curious Course on Coroutines and Concurrency
- [graingert.co.uk/dabeaz-final](https://graingert.co.uk/dabeaz-final) — Generators: The Final Frontier
- [graingert.co.uk/trio-sc](https://graingert.co.uk/trio-sc) — Go statement considered harmful (njs)
- [graingert.co.uk/dijkstra68](https://graingert.co.uk/dijkstra68) — Go To Statement Considered Harmful (1968)
