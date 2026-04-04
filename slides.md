---
marp: true
html: true
---

# Why you should use AnyIO

### ...and why you probably already have it installed

https://graingert.co.uk/why-anyio-already

<!-- right so this is a talk about AnyIO. you probably already have it installed and don't know it. I'm going to try and convince you to actually use it on purpose. -->

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

# Agenda

* misconception: `asyncio` == `async`/`await`
* the problems with `asyncio.create_task` (and the fix: structured concurrency)
* getting a result from a task with `nonlocal`
* "But I want to return without waiting!": application scoped task groups
* the two most important reasons to use AnyIO
  * incrementally adoptable — drop into any asyncio codebase
  * cancellations are level-triggered (not edge-triggered like asyncio)
* `asyncio.shield` vs shielded `CancelScope`s
* some of my favourite AnyIO features
    * memory object streams (`asyncio.Queue` done right)
    * `anyio.Path`
    * pytest plugin built in
    * summary of features
* why you already have AnyIO installed

<!-- here's the plan. first I'll clear up the misconception that asyncio IS async/await, then I'll explain why create_task is broken, cover structured concurrency and the "return without waiting" pattern, then the two main reasons to use AnyIO, cancellation semantics, features I like, and finally reveal that you've already got AnyIO installed. -->

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

# Two most important reasons to use AnyIO
* incrementally adoptable - drop into an existing asyncio codebase, and your code automatically works on Trio too
* cancellations are level-triggered

<!-- two biggest selling points. first: it's additive - you can sprinkle it into an existing asyncio codebase and optionally add Trio support later. second, and this is the one I really care about: cancellations are level-triggered. this is subtle but it prevents real bugs. -->

---

# Level-Triggered Cancellation (AnyIO) ✅

With level cancellation, every `await` inside a cancelled `CancelScope` raises `CancelledError` — cancellation is a **persistent state**, not a one-shot event.

```python
import anyio

async def example():
    with anyio.fail_after(0):
        try:
            await anyio.sleep(1)     # raises CancelledError
        finally:
            await anyio.sleep(1000)  # also raises CancelledError ✅
    # raises TimeoutError as you leave the scope

anyio.run(example)
# Note: not anyio.run(example()) - anyio.run takes a callable, not a coroutine
```

Your timeout of 0 seconds means exactly that: **0 seconds**.

<!-- with level cancellation, once a CancelScope is cancelled, EVERY await inside it raises CancelledError. even in the finally block. the cancellation is a state, not an event. so fail_after(0) means every single await in that scope fails immediately. predictable and safe. note: anyio.run takes a callable, not a coroutine - so no parentheses on example. -->

---

# Edge-Triggered Cancellation (asyncio) ❌

With edge cancellation, `CancelledError` is a **one-shot event** — once consumed, the next `await` succeeds even inside a cancelled scope.

```python
import asyncio

async def example():
    async with asyncio.timeout(0):
        try:
            await asyncio.sleep(1)     # raises CancelledError
        finally:
            await asyncio.sleep(1000)  # waits 1000 seconds 😱
    # raises TimeoutError.... eventually

asyncio.run(example())
# Note: not asyncio.run(example) - asyncio.run takes a coroutine, not a callable
```

Your timeout of 0 seconds becomes a timeout of **1000 seconds**.

<!-- now look at the same thing with asyncio. the first await raises CancelledError as expected. but in the finally block the cancellation has been consumed - it was edge-triggered, a one-shot event. so await asyncio.sleep(1000) actually waits 1000 seconds. your timeout of 0 becomes a timeout of 1000. this is a real class of bug. note: asyncio.run takes a coroutine, not a callable - so it's asyncio.run(example()) with parentheses, the opposite of anyio.run. -->

---
<style scoped>section { padding-top: 20px; }</style>
# Deadlocks in asyncio

```python
import asyncio

async def main():
    never = asyncio.Future()

    async def task_with_finally():
        try:
            print("task_with_finally running")
            await asyncio.sleep(10)
        finally:
            print("task_with_finally in finally")
            print("awaiting never-completing future (WILL HANG)")
            await never
            print("never reached")

    async def crash_soon():
        await asyncio.sleep(1)
        print("crash_soon raising")
        raise RuntimeError("boom")

    async with asyncio.TaskGroup() as tg:
        tg.create_task(task_with_finally())
        tg.create_task(crash_soon())

asyncio.run(main())
```
<!-- edge cancellation doesn't just cause slowdowns - it can deadlock. here's a real example that hangs. -->

---

# asyncio Output *(Python 3.14 — deadlock affects all current versions)*

<!-- walk through it: task_with_finally sleeps, then in its finally block awaits a Future that never completes. crash_soon raises after 1 second. the TaskGroup cancels task_with_finally, but because cancellation is edge-triggered, the finally block's `await never` is NOT cancelled - it just hangs forever. you have to Ctrl+C multiple times to kill it. -->

```sh
$ python demo_asyncio.py
task_with_finally running
crash_soon raising
task_with_finally in finally
awaiting never-completing future (WILL HANG)
```

---

# Output after hitting Ctrl+C a few times

```sh
task_with_finally running
crash_soon raising
task_with_finally in finally
awaiting never-completing future (WILL HANG)
^C^Cunhandled exception during asyncio.run() shutdown
task: <Task finished name='Task-1' coro=<main() done, defined at /home/graingert/projects/anyio_why_already_slides/demo_asyncio.py:3> exception=ExceptionGroup('unhandled errors in a TaskGroup', [RuntimeError('boom')])>
  + Exception Group Traceback (most recent call last):
  |   File "/home/graingert/projects/anyio_why_already_slides/demo_asyncio.py", line 21, in main
  |     async with asyncio.TaskGroup() as tg:
  |                ~~~~~~~~~~~~~~~~~^^
  |   File "/usr/lib/python3.14/asyncio/taskgroups.py", line 72, in __aexit__
  |     return await self._aexit(et, exc)
  |            ^^^^^^^^^^^^^^^^^^^^^^^^^^
  |   File "/usr/lib/python3.14/asyncio/taskgroups.py", line 174, in _aexit
  |     raise BaseExceptionGroup(
  |     ...<2 lines>...
  |     ) from None
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Traceback (most recent call last):
    |   File "/home/graingert/projects/anyio_why_already_slides/demo_asyncio.py", line 19, in crash_soon
    |     raise RuntimeError("boom")
    | RuntimeError: boom
    +------------------------------------
Traceback (most recent call last):
  File "/home/graingert/projects/anyio_why_already_slides/demo_asyncio.py", line 25, in <module>
    asyncio.run(main())
    ~~~~~~~~~~~^^^^^^^^
  File "/usr/lib/python3.14/asyncio/runners.py", line 204, in run
    return runner.run(main)
           ~~~~~~~~~~^^^^^^
  File "/usr/lib/python3.14/asyncio/runners.py", line 127, in run
    return self._loop.run_until_complete(task)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/usr/lib/python3.14/asyncio/base_events.py", line 706, in run_until_complete
    self.run_forever()
    ~~~~~~~~~~~~~~~~^^
  File "/usr/lib/python3.14/asyncio/base_events.py", line 677, in run_forever
    self._run_once()
    ~~~~~~~~~~~~~~^^
  File "/usr/lib/python3.14/asyncio/base_events.py", line 2008, in _run_once
    event_list = self._selector.select(timeout)
  File "/usr/lib/python3.14/selectors.py", line 452, in select
    fd_event_list = self._selector.poll(timeout, max_ev)
  File "/usr/lib/python3.14/asyncio/runners.py", line 166, in _on_sigint
    raise KeyboardInterrupt()
KeyboardInterrupt
```

<!-- that's a lot of traceback just to say "your program hung and you had to kill it". the program didn't exit cleanly - we had to interrupt it multiple times. the actual error from crash_soon only surfaces after we force-kill the process. -->

---

<style scoped>section { padding-top: 20px; }</style>

# The Same Example with AnyIO

```python
import asyncio
import anyio

async def main():
    never = asyncio.Future()

    async def task_with_finally():
        try:
            print("task_with_finally running")
            await asyncio.sleep(10)
        finally:
            print("task_with_finally in finally")
            print("awaiting never-completing future (WILL NOT HANG)")
            await never
            print("never reached")

    async def crash_soon():
        await asyncio.sleep(1)
        print("crash_soon raising")
        raise RuntimeError("boom")

    async with anyio.create_task_group() as tg:
        tg.start_soon(task_with_finally)
        tg.start_soon(crash_soon)

asyncio.run(main())
```

---

# AnyIO Output

<!-- same program with anyio.create_task_group. only change is using anyio.create_task_group instead of asyncio.TaskGroup. because AnyIO uses level-triggered cancellation, when crash_soon raises, the cancellation of task_with_finally persists into its finally block. the `await never` is immediately cancelled too. no hang. -->
```sh
$ python demo_anyio.py
task_with_finally running
crash_soon raising
task_with_finally in finally
awaiting never-completing future (WILL NOT HANG)
  + Exception Group Traceback (most recent call last):
  |   File "/home/graingert/projects/anyio_why_already_slides/demo_anyio.py", line 26, in <module>
  |     asyncio.run(main())
  |     ~~~~~~~~~~~^^^^^^^^
  |   File "/usr/lib/python3.14/asyncio/runners.py", line 204, in run
  |     return runner.run(main)
  |            ~~~~~~~~~~^^^^^^
  |   File "/usr/lib/python3.14/asyncio/runners.py", line 127, in run
  |     return self._loop.run_until_complete(task)
  |            ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  |   File "/usr/lib/python3.14/asyncio/base_events.py", line 719, in run_until_complete
  |     return future.result()
  |            ~~~~~~~~~~~~~^^
  |   File "/home/graingert/projects/anyio_why_already_slides/demo_anyio.py", line 22, in main
  |     async with anyio.create_task_group() as tg:
  |                ~~~~~~~~~~~~~~~~~~~~~~~^^
  |   File "/home/graingert/projects/anyio_why_already_slides/.venv/lib/python3.14/site-packages/anyio/_backends/_asyncio.py", line 783, in __aexit__
  |     raise BaseExceptionGroup(
  |         "unhandled errors in a TaskGroup", self._exceptions
  |     ) from None
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Traceback (most recent call last):
    |   File "/home/graingert/projects/anyio_why_already_slides/demo_anyio.py", line 20, in crash_soon
    |     raise RuntimeError("boom")
    | RuntimeError: boom
    +------------------------------------
```

<!-- clean exit, clear traceback, no hanging, no Ctrl+C. the program terminates immediately with the actual error. notice "WILL NOT HANG" - the await never was properly cancelled by level-triggered cancellation. -->

---

# Edge Cancellation with WebSockets over TLS

<style scoped>section { padding-top: 20px; }</style>

- Cancellation fires inside `process()` - but the `async with` still runs `__aexit__`
- WebSocket `__aexit__` does a TLS shutdown, which **awaits I/O**
- With edge cancellation, that await **succeeds** even in a cancelled state
- So the timeout is bypassed - your 10-second limit can hang forever

```python
async def consume_ws():
    async with await connect_ws("wss://example.com/news") as ws:
        async for message in ws:
            await process(message)  # cancellation happens here
    # cancellation doesn't happen as we `__aexit__()` the context manager

async def example():
    async with asyncio.timeout(10):
        await consume_ws()  # could hang forever
```

<!-- this isn't contrived. if you're using WebSockets over TLS, the TLS shutdown in __aexit__ involves awaiting I/O. with edge cancellation that await succeeds even though you're in a cancelled state, so your timeout becomes meaningless. your 10-second timeout could hang forever. -->

---

# Shielding from Cancellation

## When you *can't* just walk away - even after cancelling

Sometimes you can cancel the work, but you **must wait for it to finish dying**:

- Subprocesses (`anyio.to_process.run_sync`): you can `terminate()` the process, but you must still `wait()` to join it - otherwise you get zombie processes
- Waiting for a thread to finish (`loop.run_in_executor`, `anyio.to_thread.run_sync`) - threads can't be interrupted at all
- On Windows IOCP (Proactor): cancelled operations complete with `ERROR_OPERATION_ABORTED`, and you must wait for the completion packet before freeing memory

<!-- sometimes you can cancel the work but you can't just walk away. subprocesses are the perfect example: you can terminate the process, but you MUST still join it afterwards. if you don't wait, you get zombie processes. threads are worse - you can't even cancel them. and on Windows IOCP the OS must acknowledge the cancel before you can free memory. this is where shielding comes in. -->

---

# Cancellation Abandons the Work, Not the Task

The async framework can raise `CancelledError` in your coroutine, but:
- the **underlying thread keeps running**
- a **terminated subprocess still needs to be joined**
- **something still needs to wait to be able to clear memory**

You're not cancelling the work - you're just *abandoning* the future that was watching it. 👻

<!-- key insight: when you cancel an executor task in asyncio, the thread keeps running. when you cancel a subprocess wrapper, the process might still be alive or needs joining. you've just abandoned the Future. the work is still happening, you just stopped paying attention to it. like hanging up the phone on someone mid-sentence. -->

---

# Example: Windows IOCP Buffer Safety

```python
# IOCP
buffer = allocate_buffer(1024)
try:
    await write_buffer_to_socket(buffer, socket)
finally:
    # if write_buffer_to_socket is cancelled and we don't wait for the cancel
    # signal the OS could still be using the buffer and we send undefined
    # bytes to the socket.
    clear(buffer)
```

<!-- concrete Windows example. if you cancel during write_buffer_to_socket and immediately clear the buffer, the OS might still be DMA-ing from that buffer. you'd send undefined bytes over the network. you MUST wait for cancellation to complete before freeing resources. -->

---

# `asyncio.shield` - The Duct-Tape Approach

```python
async def run_in_process(fn, *args):
    process = await asyncio.create_subprocess_exec(...)
    try:
        await asyncio.shield(process.wait())
        # ⚠️ If cancelled, shield absorbs the cancel...
        # ... but process.wait() keeps running as a detached task
    except asyncio.CancelledError:
        process.terminate()
        # ⚠️ Edge cancellation: nested asyncio.timeout blocks or
        # multiple task.cancel() calls can cancel this await again
        # before the process exits - leaving it un-joined
        await process.wait()  # might be cancelled before process exits!
        raise
```

<!-- asyncio.shield is the standard answer to "how do I protect work from cancellation". but it's duct tape. it wraps a single await, creates a detached task. and because of edge cancellation - from nested asyncio.timeout blocks or multiple task.cancel() calls - the process.wait() in the except block can be cancelled again before the process exits, leaving it un-joined. -->

---

# Problems

❌ **Edge-triggered**: a `CancelledError` sneaks through on the *next* checkpoint after the shield exits  
❌ **Orphaned inner task**: the shielded `process.wait()` keeps running with no owner  
❌ **No scope**: shield applies to one `await`, not a logical block (terminate + join)  
❌ **Can't compose terminate + join**: need to shield the wait, then join, then re-raise - but edge cancellation makes the join unreliable

<!-- four problems. shield only wraps one await. the inner task is orphaned. and the critical issue for subprocesses: you need to terminate AND join as a single logical unit, but shield can't express that. edge cancellation - from nested asyncio.timeout blocks or multiple task.cancel() calls - means the join in the except block can be cancelled again before the process exits, leaving it un-joined. -->

---

# AnyIO Shielded Cancel Scopes - The Structured Approach

```python
# Simplified implementation of anyio.to_process.run_sync
async def to_process_run_sync(fn, *args):
    process = await anyio.open_process(...)
    try:
        await process.wait()
        return process.returncode
    except anyio.get_cancelled_exc_class():
        process.terminate()
        # Shield the join: we MUST wait for the process to exit
        # even though we've been cancelled
        with anyio.CancelScope(shield=True):
            await process.wait()  # no zombie processes
        raise
    # Pending cancellation is re-raised after the shielded join
```

<!-- AnyIO's approach is fundamentally different. when cancellation hits, we terminate the process, then shield the join. CancelScope with shield=True protects the wait - the process is properly reaped even under cancellation. pending cancellation is deferred and reliably re-raised after we exit the shield. no zombies, no orphans. -->

---

# Why It Works

✅ **Level-triggered**: cancellation is *deferred*, not lost — re-fires on the next `await` after the shield exits  
✅ **Process-aware**: `terminate()` + shielded `wait()` — kill it, then reap it  
✅ **Scoped**: protect the whole terminate-and-join block, not just one `await`  
✅ **No zombies**: structured concurrency means every process is joined

The key insight: sometimes cleanup requires I/O. `asyncio.shield` can only protect a single expression. `CancelScope(shield=True)` protects an entire logical block — terminate *and* join — which is exactly what subprocess cleanup needs.

---

<style scoped>section { padding-top: 10px; }</style>

# Shielding in Detail: asyncio.shield
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 660 310" font-family="'JetBrains Mono','Fira Code','Cascadia Code',ui-monospace,monospace" width="650" style="display: block; margin: 0 auto;">
  <defs>
    <marker id="asyncio-shield-arr-red" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3z" fill="#d20f39"/></marker>
    <marker id="asyncio-shield-arr-blue" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3z" fill="#1e66f5"/></marker>
    <marker id="asyncio-shield-arr-muted" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3z" fill="#9ca0b0"/></marker>
  </defs>
  <!-- background -->
  <rect width="660" height="310" fill="#eff1f5" rx="12"/>
  <!-- title -->
  <text x="330" y="26" text-anchor="middle" font-size="13" font-weight="bold" fill="#d20f39">asyncio.shield — what happens under cancellation</text>
  <line x1="16" y1="34" x2="644" y2="34" stroke="#d20f39" stroke-width="1" opacity="0.35"/>
  <!-- column headers -->
  <text x="160" y="54" text-anchor="middle" font-size="11" fill="#6c6f85">what your code sees</text>
  <text x="490" y="54" text-anchor="middle" font-size="11" fill="#6c6f85">what happens inside shield()</text>
  <!-- divider -->
  <line x1="330" y1="44" x2="330" y2="290" stroke="#8c8fa1" stroke-width="1" stroke-dasharray="4,3"/>
  <text x="330" y="174" text-anchor="middle" font-size="18" fill="#8c8fa1" transform="rotate(-90,330,174)">one-way barrier</text>
  <!-- === LEFT SIDE === -->
  <!-- your code box -->
  <rect x="30" y="66" width="140" height="44" rx="5" fill="#dce0e8" stroke="#1e66f5" stroke-width="1.5"/>
  <text x="100" y="84" text-anchor="middle" font-size="11" fill="#6c6f85">your code</text>
  <text x="100" y="101" text-anchor="middle" font-size="12" font-weight="bold" fill="#1e66f5">await shield(f)</text>
  <!-- down arrow -->
  <line x1="100" y1="110" x2="100" y2="138" stroke="#d20f39" stroke-width="1.5" marker-end="url(#asyncio-shield-arr-red)"/>
  <text x="112" y="130" font-size="10" fill="#d20f39">cancel</text>
  <!-- CancelledError box -->
  <rect x="20" y="140" width="220" height="44" rx="5" fill="#ffd7cf" stroke="#d20f39" stroke-width="2"/>
  <text x="130" y="158" text-anchor="middle" font-size="11" fill="#6c6f85">outer Future cancelled</text>
  <text x="130" y="176" text-anchor="middle" font-size="13" font-weight="bold" fill="#d20f39">⚡ CancelledError</text>
  <!-- edge note -->
  <text x="130" y="208" text-anchor="middle" font-size="10" fill="#6c6f85">edge-triggered: cancel "used up" here</text>
  <text x="130" y="222" text-anchor="middle" font-size="10" fill="#6c6f85">next await may succeed ⚠</text>
  <!-- === RIGHT SIDE === -->
  <!-- inner Task box -->
  <rect x="350" y="66" width="270" height="44" rx="5" fill="#fff0d4" stroke="#fe640b" stroke-width="1.5" stroke-dasharray="6,3"/>
  <text x="485" y="84" text-anchor="middle" font-size="11" fill="#6c6f85">inner Task  👻</text>
  <text x="485" y="101" text-anchor="middle" font-size="12" fill="#fe640b">cancel NOT forwarded</text>
  <!-- down arrow -->
  <line x1="485" y1="110" x2="485" y2="138" stroke="#9ca0b0" stroke-width="1.5" marker-end="url(#asyncio-shield-arr-muted)"/>
  <text x="497" y="130" font-size="10" fill="#6c6f85">runs on...</text>
  <!-- result lost box -->
  <rect x="360" y="140" width="250" height="44" rx="5" fill="#eff1f5" stroke="#d20f39" stroke-width="1.5"/>
  <text x="485" y="158" text-anchor="middle" font-size="11" fill="#6c6f85">completes eventually</text>
  <text x="485" y="176" text-anchor="middle" font-size="13" font-weight="bold" fill="#d20f39">result → void ❌</text>
  <!-- orphan note -->
  <text x="485" y="208" text-anchor="middle" font-size="10" fill="#6c6f85">no owner, no supervision</text>
  <text x="485" y="222" text-anchor="middle" font-size="10" fill="#6c6f85">resource cleanup may never run</text>
  <!-- bottom summary -->
  <rect x="16" y="248" width="628" height="48" rx="6" fill="#e6e9ef" stroke="#8c8fa1" stroke-width="1"/>
  <text x="330" y="266" text-anchor="middle" font-size="11" fill="#d20f39" font-weight="bold">cancel flows in (to outer Future) but not through (to inner Task)</text>
  <text x="330" y="285" text-anchor="middle" font-size="10" fill="#6c6f85">Use CancelScope(shield=True) instead — it defers cancellation and keeps the task owned</text>
</svg>

**What's happening:** `shield()` wraps the outer Future around an inner Task. When the outer cancel arrives, the outer Future is cancelled immediately (edge-triggered ⚡). The inner Task is orphaned — it keeps running with no owner. The result is silently discarded.

<!-- in this diagram you can see the orphaned inner task running off on its own - same problem as create_task. shield wraps a single point, and after it exits you're back to unstructured territory. -->

---

<style scoped>section { padding-top: 15px; }</style>

# Comparison

| | `asyncio.shield` | `anyio.CancelScope(shield=True)` |
|---|---|---|
| Cancellation model | Edge (one-shot) | Level (persistent, deferred) |
| Scope | Single `await` | Entire `with` block |
| Process cleanup | ❌ Can't reliably terminate + join | ✅ Terminate then shielded join |
| Cancellation after exit | ⚠️ Maybe (edge, unreliable) | ✅ Always re-raised |
| Orphaned tasks | ❌ Yes | ✅ Never |
| Composable | ❌ Not really | ✅ Nests with task groups |

<!-- full comparison side by side. every row is a win for AnyIO. key insight: shielding should be a scope, not a wrapper around a single expression. the process case makes this crystal clear - you need to shield a multi-step cleanup sequence. -->


---

<style scoped>section { font-size: 22px; padding-top: 20px; }</style>

# Mixing Native asyncio Cancellation

❌ `task.cancel()` injects `CancelledError` directly, bypassing AnyIO's cancel scope stack — the shield cannot defer it:

```python
async def ham():
    with anyio.CancelScope(shield=True):
        await spam()  # shield does NOT protect against task.cancel()

async def bad():
    task = asyncio.create_task(ham())
    task.cancel()   # bypasses AnyIO's cancel scope machinery entirely
    await task      # CancelledError — task never started
```

✅ `tg.cancel_scope.cancel()` goes through AnyIO's machinery — the shield defers it correctly:

```python
async def main():
    async with anyio.create_task_group() as tg:
        tg.cancel_scope.cancel()
        tg.start_soon(ham)  # spam() runs to completion ✅
```

AnyIO guarantees every `start_soon`'d task runs to its first `await` before cancellation is delivered — so `with anyio.CancelScope(shield=True):` (synchronous) is always entered first.

<!-- task.cancel() is a raw asyncio operation that bypasses AnyIO's cancel scope stack entirely. CancelScope(shield=True) only defers cancellations delivered through AnyIO's own machinery. tg.cancel_scope.cancel() goes through that machinery, so the shield works. AnyIO's start_soon guarantee means the synchronous with block is always entered before cancellation fires, so the shield is always in place. -->

---

# More AnyIO Features: Backpressure by Default. Structured. Composable.

<!-- ok we've covered the big conceptual stuff - structured concurrency and level-triggered cancellation. now let me show you some practical features I like. -->

* AnyIO provides `MemoryObjectSendStream` and `MemoryObjectReceiveStream`
* like `asyncio.Queue` but you don't need to keep a count of how many producer/consumers you have
  * you just make a clone for each producer/consumer
  * use a `with` or `async with` to close the clones.
  * Once all the clones of one end of the memory object stream are closed
  iterating the other end will raise StopAsyncIteration.

<!-- memory object streams are like asyncio.Queue but designed right. the killer feature is clone() - each producer/consumer gets their own clone, and when all clones of one end are closed the other end gets a clean StopAsyncIteration. no sentinel values, no manual counting, no shutdown coordination. -->

---

# Memory Object Streams: Full Example

```python
import anyio

async def consume_ws(url, stream):
    with stream:              # sync - runs before first await
        async with await connect_ws(url) as ws:
            async for msg in ws:
                await stream.send(msg)

async def news_and_weather():
    tx, rx = anyio.create_memory_object_stream[bytes]()  # default buffer size = 0
    with tx, rx:
        async with anyio.create_task_group() as tg:
            tg.start_soon(consume_ws, "ws://example.com/news", tx.clone())
            tg.start_soon(consume_ws, "ws://example.com/weather", tx.clone())
            tx.close()
            async for item in rx:
                print(item)

anyio.run(news_and_weather)
```

<!-- look how clean this is. two WebSocket consumers, each with a clone of the send stream, feeding a single receive stream. when both producers finish their clones close, original tx is already closed, so the async for on rx terminates naturally. fully structured shutdown with zero boilerplate. default buffer size is 0 so you get backpressure for free.

note the synchronous `with stream:` - AnyIO guarantees every start_soon'd task runs to its first await point before cancellation is delivered. the sync with runs before any await, so __exit__ always fires and the clone is always closed. no leaked clones, no phantom senders keeping rx open forever.

the [bytes] on create_memory_object_stream is for static type checking - create_memory_object_stream is a generic tuple subclass, so [bytes] specialises the type. no runtime effect, but your type checker and IDE will know the stream carries bytes. -->

---

<style scoped>section { padding-top: 10px; padding-bottom: 40px; }</style>

# Key Properties

-   ✅ **Buffer size defaults to 0** → automatic backpressure

-   ✅ `async for` works naturally

-   ✅ `aclose()` or `close()` signals end-of-stream

-   ✅ `clone()` enables multiple consumers safely - use `async with` or sync `with` to gain ownership and automatically close:

    ```python
    async def consume_ws(url, stream):
        with stream:          # sync - runs before first await
            async with await connect_ws(url) as ws:
                ...

    tg.start_soon(consume_ws, url, tx.clone())
    ```

-   ✅ Structured shutdown - unlike asyncio, AnyIO tasks always run to their first `await` before cancellation, so `with stream:` always closes the clone

<!-- five properties you want from inter-task communication. you get them all for free just by using memory object streams instead of asyncio.Queue. the clone pattern is safe because AnyIO guarantees start_soon'd tasks reach their first checkpoint before cancellation - and the synchronous with stream runs before any await, so the clone is always closed. -->

---

# `async with` shortcut

- `async with` = `with` for streams - automatic cleanup
- Combine streams, task groups, etc. in one `async with`:

```python
async def consume_ws(url, stream):
    async with stream, await connect_ws(url) as ws:
        async for msg in ws:
            await stream.send(msg)

async def news_and_weather():
    tx, rx = anyio.create_memory_object_stream[bytes]()
    async with tx, rx, anyio.create_task_group() as tg:
        tg.start_soon(consume_ws, "ws://example.com/news", tx.clone())
        tg.start_soon(consume_ws, "ws://example.com/weather", tx.clone())
        tx.close()
        async for item in rx:
            print(item)
```

<!-- async with gives you automatic cleanup of streams just like files. stacking tx, rx, and the task group into a single async with means you get structured ownership. -->

---

# `async with` shortcut — why it's safe

Three resources enter one `async with`: the send stream, receive stream, and task group. They're all closed/joined together on exit — **in the right order, even under exceptions or cancellation**.

- `tx.close()` is called explicitly in the body — this is what signals end-of-stream to tasks
- `async with tx, rx` exits in *reverse* entry order: `tg.__aexit__` first (joins tasks), then `rx`, then `tx` — the explicit close is what actually stops new work before the tasks finish
- `MemoryObjectStream.__aenter__` returns `self` without yielding — not a real checkpoint — so the structured shutdown guarantee still holds

<!-- the key insight: async with on a MemoryObjectStream doesn't yield to the event loop, so it's safe to use inside a task group even with cancellation. everything closes in structured order. -->

---

# asyncio.Queue Comparison

```python
import asyncio

async def main():
    q = asyncio.Queue()  # unbounded by default (!)

    async def producer():
        for i in range(3):
            print("put", i)
            await q.put(i)
        # How do we signal completion?

    async def consumer():
        while True:
            item = await q.get()
            print("got", item)
```

<!-- here's the equivalent with asyncio.Queue. notice the problems immediately: unbounded by default, no async iteration, and - how do you signal completion? there's no mechanism. you end up with sentinel values or manual counters. -->

---

# Problems with `asyncio.Queue`

-   ❌ Unbounded by default (no backpressure)

-   ❌ No async iteration

-   ❌ No built-in structured close (historically)

-   ❌ No clone() so requires sentinel values or custom shutdown logic

<!-- every one of these is a footgun. unbounded means memory grows without limit. no async iteration means you write while True loops. no structured close means you invent your own shutdown protocol. -->

---

# asyncio.Queue.shutdown() (3.13+)

Python 3.13 added:

```python
q.shutdown()
```

But:

-   Only on Python 3.13+

-   Still no cloning

-   Still no structured fan-out

<!-- Python 3.13 added Queue.shutdown() which is progress, but it's only on the latest Python, doesn't have cloning, doesn't compose with structured concurrency. AnyIO gives you all of this on Python 3.9+. -->

---
# Conceptual Comparison

| Feature | AnyIO Stream | asyncio.Queue |
|---------|--------------|---------------|
| Default backpressure | ✅ (buffer=0) | ❌ (unbounded) |
| Async iteration | ✅ | ❌ |
| Structured close | ✅ | ⚠️ (3.13+) |
| Clone receivers | ✅ | ❌ |
| Trio-compatible | ✅ | ❌ |

AnyIO streams compose with structured concurrency. `asyncio.Queue`
predates it.

<!-- the table tells the story. AnyIO streams were designed with structured concurrency in mind. asyncio.Queue predates it and it shows. -->

---
# "If I'm already using Trio, I don't need AnyIO."

Trio is a minimal framework — only what's mandatory for a network framework. AnyIO is a portability + abstraction layer with batteries included.

What AnyIO adds on top of Trio:

-   ✅ Backend portability (asyncio and Trio) — a stable public API for libraries
-   ✅ High-level stream utilities: `BufferedByteReceiveStream`, `StapledStream`, `anyio.Path`
-   ✅ Thread/subprocess/subinterpreter helpers

<!-- common pushback: "I already use Trio, why do I need AnyIO?" Trio is deliberately minimal - it only gives you what a network framework must provide. AnyIO is batteries-included on top of that. -->

---

# Writing Libraries: Target AnyIO, Not Trio

If you write a library **directly against Trio**:

- ❌ You lock out asyncio users entirely.

If you write a library **against AnyIO**:

- ✅ Trio users still get full Trio semantics.
- ✅ asyncio users can incrementally adopt structured concurrency.
- ✅ You get a bunch of cool extra tools.

**AnyIO is the right target for any library that wants to support both backends.**

---

# Buffered Byte Streams (AnyIO Feature Trio Lacks)

Trio provides `SendStream` / `ReceiveStream`.

But it does **not** provide:

-   Buffered reads

-   `receive_exactly(n)`

-   `receive_until(delimiter)`

-   Automatic read buffering

AnyIO does.

<!-- one of my favourite examples. Trio gives you raw byte streams but if you need line-by-line reading or fixed-size reads you're on your own. AnyIO's BufferedByteReceiveStream handles all the annoying buffering for you. -->

---

<style scoped>section { padding-top: 20px; }</style>

# Demo --- AnyIO Buffered Byte Streams

```python
import anyio.streams.buffered

async def main():

    async def producer(stream):
        with stream:
            await stream.send(b"hello\nworld\n")

    async def consumer(stream):
        with stream:
            buffered = anyio.streams.buffered.BufferedByteReceiveStream(stream)
            line1 = await buffered.receive_until(b"\n", 4096)
            print("line1:", line1)
            line2 = await buffered.receive_until(b"\n", 4096)
            print("line2:", line2)

    tx, rx = anyio.create_memory_object_stream[bytes]()
    async with tx, rx, anyio.create_task_group() as tg:
        tg.start_soon(producer, tx.clone())
        tx.close()
        tg.start_soon(consumer, rx.clone())
        rx.close()

anyio.run(main)
```

---

# Output + What Just Happened

<!-- producer sends both lines in one chunk. consumer uses receive_until to split by newline. no manual buffer management, no partial read handling. it just works. -->

```sh
$ python demo_buffered_bytes.py
line1: b'hello'
line2: b'world'
```

-   The producer sent both lines in one chunk.
-   The consumer parsed them cleanly by delimiter.
-   No manual buffering. No partial read bookkeeping.

<!-- clean output. the buffered stream handled all the complexity of parsing delimited data from arbitrary chunk boundaries. saves you from writing buggy buffer management code. -->

---

# How You'd Do This in Trio

Trio gives you raw receive:

```python
data = await stream.receive_some(1024)
```

But you must manually:

-   Accumulate into a buffer

-   Search for delimiters

-   Slice the buffer

-   Handle partial frames

-   Handle EOF correctly

<!-- with raw Trio you have to do all this yourself. accumulate into a buffer, scan for delimiters, slice, handle partial frames, handle EOF. it's not rocket science but it's tedious and easy to get wrong. speaking of getting it wrong... -->

---
# Can You Spot the Performance Footgun?

I asked ChatGPT for an example - can you spot the problem?

```python
buffer = bytearray()
while True:
    chunk = await stream.receive_some(1024)
    if not chunk:
        break
    buffer.extend(chunk)
    while b"\n" in buffer:
        line, _, rest = buffer.partition(b"\n")
        print(line + b"\n")
        buffer = bytearray(rest)  # copies remaining bytes every iteration
```

<!-- I asked ChatGPT to write this and it has a bug. can anyone spot it? -->

---

# Quadratic Performance in the Inner Loop

Every iteration of `while b"\n" in buffer` does `buffer = bytearray(rest)`,
copying the remaining data each time. If you receive a chunk with many
newlines, this is O(n²) in the number of bytes.

<!-- it's quadratic! every iteration copies the remaining buffer into a new bytearray. if you get a large chunk with many newlines you're doing O(n²) work. BufferedByteReceiveStream handles this correctly with efficient internal buffering. -->

---

# What AnyIO Adds Here

`BufferedByteReceiveStream` gives you:

-   `receive_exactly(n)`

-   `receive_until(delimiter)`

-   Proper EOF semantics

-   Efficient internal buffering

-   Works on both Trio and asyncio backends

This is a real ergonomic upgrade.

<!-- receive_exactly, receive_until, proper EOF, efficient buffering, works on both backends. real ergonomic upgrade. -->

---

# Further Reading

-   [github.com/python-trio/trio/issues/796](https://github.com/python-trio/trio/issues/796) - Provide standard mechanism for splitting a stream into lines
-   [github.com/groove-x/trio-util/issues/22](https://github.com/groove-x/trio-util/issues/22) - Add a LineReader?
-   [github.com/python-trio/trio/issues/562](https://github.com/python-trio/trio/issues/562) - Get N items from Channel

<!-- these are the Trio issues where buffered streams were discussed and ultimately not added to Trio itself. AnyIO fills this gap. -->

---

# anyio.Path: Async File Operations

## The Problem with pathlib

```python
from pathlib import Path

async def amain():
    # ⚠️ These all BLOCK the event loop!
    path = Path("data.txt")

    path.write_text("Hello!")      # Blocks
    content = path.read_text()     # Blocks
    exists = path.exists()         # Blocks
```

<!-- pathlib is great but every operation blocks the event loop. in an async application, calling path.read_text() blocks the entire loop while waiting for disk I/O. defeats the whole point of async. -->

---

# The Solution: `anyio.Path`

```python
import anyio

async def amain():
    # ✅ Non-blocking - each runs in a thread pool via anyio.to_thread.run_sync
    path = anyio.Path("data.txt")
    await path.write_text("Hello!")    # Async
    content = await path.read_text()  # Async
    exists = await path.exists()      # Async
```

**Same API as `pathlib`, but async-native.** Each operation offloads to a thread pool, so your event loop stays free while the disk I/O happens.

<!-- anyio.Path is a drop-in async replacement for pathlib.Path. under the hood, each method wraps the blocking call with anyio.to_thread.run_sync. the event loop isn't blocked - other tasks keep running. -->

---

# Real Power: Parallel File Operations

```python
import anyio

async def concurrently_chmod_all_csvs():
    data_dir = anyio.Path("training_data")
    async with anyio.create_task_group() as tg:
        async for path in data_dir.iterdir():
            if await path.is_file() and path.suffix == '.csv':
                tg.start_soon(path.chmod, 0o644)

anyio.run(concurrently_chmod_all_csvs)
# All files processed concurrently!
```

<!-- and because it's async you can combine it with task groups for parallel file I/O. process all CSVs in a directory concurrently, with structured concurrency ensuring everything completes before you continue. -->

---

# Key Features

| Feature | pathlib | anyio.Path |
|---------|---------|------------|
| Async operations | ❌ Blocks | ✅ async with threads |
| Parallel I/O | ❌ Sequential | ✅ Works with task groups |
| Event loop friendly | ❌ Blocks | ✅ Non-blocking |
| API compatibility | ✅ Standard | ✅ Same interface but async |
| Type hints | ✅ Yes | ✅ Yes |

**Key Takeaway:** Drop-in replacement for pathlib that actually respects
async/await

<!-- anyio.Path gives you everything pathlib does but without blocking the event loop. genuine drop-in replacement. -->

---

# pytest Plugin

* AnyIO ships with a pytest plugin that it uses to test itself.
* This means if you already depend on AnyIO you don't need pytest-asyncio as well.

```python
@pytest.mark.anyio
async def test_something():
    assert await something() == "result"
```

<!-- AnyIO ships with its own pytest plugin - the same one it uses to test itself. so if you already depend on AnyIO you don't need pytest-asyncio. just @pytest.mark.anyio and you're done. -->

---
# Limiting the Plugin to asyncio
* By default the plugin runs your tests under both asyncio and Trio
* if you're still gradually migrating to AnyIO and still call asyncio APIs directly
* you can run your tests in asyncio mode only by adding the following to your root `conftest.py`

```python
@pytest.fixture
def anyio_backend():
    return 'asyncio'
```

<!-- by default the plugin runs tests on both asyncio and Trio, which is great for catching backend-specific bugs. if you're still migrating and only need asyncio, add this fixture to your conftest. -->
---

# Networking & I/O

| Feature | Benefit |
|---|---|
| **TCP/UDP/UNIX sockets** | Happy Eyeballs built in (fixed refcycles in CPython's implementation); async/await UDP — no Transports/Protocols |
| **TLS streams** | `TLSStream` wraps any byte stream with TLS, not just sockets |
| **Subprocesses** | `run_process()` / `open_process()` with async stream I/O on stdin/stdout/stderr |
| **Signal handling** | `open_signal_receiver()` - async iterator over OS signals |

<!-- AnyIO has a full networking stack. TCP, UDP, Unix sockets with Happy Eyeballs built in. TLS that wraps any byte stream, not just sockets. subprocesses with async stream I/O. signal handling as an async iterator. -->

---

# Streams & Concurrency

| Feature | Benefit |
|---|---|
| **`TextReceiveStream`** | Incremental UTF-8 decoding over any byte stream |
| **`StapledStream`** | Combine separate send/receive streams into one bidirectional stream |
| **`tg.start()`** | `await tg.start(server_fn)` - blocks until the task calls `task_status.started(value)`, perfect for server startup |
| **Synchronization primitives** | `Lock`, `Condition`, `Event`, `Semaphore`, `CapacityLimiter` - portable across backends |

<!-- more batteries: TextReceiveStream for incremental UTF-8 decoding, StapledStream for combining send/receive, tg.start() which blocks until a task signals it's ready - great for server startup - and all the sync primitives you'd expect, portable across backends. -->

---

# Threads & Beyond

| Feature | Benefit |
|---|---|
| **`to_thread` / `from_thread`** | Bidirectional sync↔async bridging with structured cancellation — run blocking code without blocking the event loop, or call async code from a thread |
| **Subinterpreters** | `anyio.to_interpreter.run_sync` subinterpreter helpers for true parallelism (Python 3.13+) |
| **Async `functools`** | `anyio.functools.lru_cache` for async functions |
| **Fully typed** | Great IDE autocompletion and type checker support |

<!-- and more: bidirectional sync/async bridging with structured cancellation, subinterpreter support for true parallelism on 3.13+, async functools like lru_cache, and the whole API is fully typed for great IDE and type checker support. -->

---

# The Advantage of Being on PyPI

In Python 3.13, a number of bug-fixes were applied to asyncio.TaskGroup
but they were considered breaking changes so were not backported to 3.11
or 3.12:

https://docs.python.org/3/whatsnew/3.13.html#asyncio

<!-- practical advantage of AnyIO being a pip-installable package. in Python 3.13 important TaskGroup bugfixes landed - like fixing deadlocks when nested task groups both have failing children. but these were considered breaking changes and weren't backported to 3.11 or 3.12. -->

> Improve the behavior of
> [TaskGroup](https://docs.python.org/3/library/asyncio-task.html#asyncio.TaskGroup)
> when an external cancellation collides with an internal cancellation.
> For example, when two task groups are nested and both experience an
> exception in a child task simultaneously, it was possible that the
> outer task group would hang, because its internal cancellation was
> swallowed by the inner task group.

---

# The Advantage of Being on PyPI (continued)
* you need to use the latest version of Python for fixed asyncio
* Because AnyIO is hosted on PyPI you get bugfixes on all supported python versions
* AnyIO is currently still supporting the EOL Python 3.9 (as of v4.12.1)

<!-- with asyncio you need to upgrade your entire Python version for bugfixes. with AnyIO you just pip install the latest and get fixes on every supported Python version. AnyIO even still supports Python 3.9 which is past EOL. that's the power of being on PyPI. -->

---

# Asyncio is not bad

* it's better than Twisted (I once spent a week fixing a missing `six` call
  - asyncio is Python 3 only so this class of bug can't exist)
* but try making an LDAP server without Twisted!
* *some* of the mistakes Twisted made were copied into asyncio
* Curio is good! Unfortunately it's archived
* Trio isn't perfect: it's slower than asyncio, especially with uvloop
  * but better abstractions mean you're *more likely* to use async correctly — e.g. `anyio.Path` instead of blocking pathlib — so your real-world throughput may actually be higher
* AnyIO gives you options and batteries to play with

<!-- I want to be fair: asyncio is not bad. it's a huge improvement over Twisted - I once spent a week debugging a missing `six` call, a whole class of bug that can't exist with asyncio. but try making an LDAP server without Twisted! Curio was great but it's archived. Trio is excellent but slower than asyncio. AnyIO gives you options. -->

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

<style scoped>section { font-size: 22px; }</style>

# Any questions?

**These slides:** [graingert.co.uk/why-anyio-already](https://graingert.co.uk/why-anyio-already)

**Further reading:**
- [graingert.co.uk/trio-sc](https://graingert.co.uk/trio-sc) - Go statement considered harmful (njs)
- [graingert.co.uk/dijkstra68](https://graingert.co.uk/dijkstra68) - Go To Statement Considered Harmful (1968)
- [anyio.readthedocs.io](https://anyio.readthedocs.io) — AnyIO documentation
- [graingert.co.uk/dabeaz-gen](https://graingert.co.uk/dabeaz-gen) - Generator Tricks for Systems Programmers
- [graingert.co.uk/dabeaz-coro](https://graingert.co.uk/dabeaz-coro) - A Curious Course on Coroutines and Concurrency
- [graingert.co.uk/dabeaz-final](https://graingert.co.uk/dabeaz-final) - Generators: The Final Frontier
- [docs.python.org/3/whatsnew/3.13.html#asyncio](https://docs.python.org/3/whatsnew/3.13.html#asyncio) - Python 3.13 asyncio changes
- [github.com/python-trio/trio/issues/796](https://github.com/python-trio/trio/issues/796) - Provide standard mechanism for splitting a stream into lines
- [github.com/groove-x/trio-util/issues/22](https://github.com/groove-x/trio-util/issues/22) - Add a LineReader?
- [github.com/python-trio/trio/issues/562](https://github.com/python-trio/trio/issues/562) - Get N items from Channel

<!-- thanks! happy to take questions. I'm graingert on GitHub. -->
