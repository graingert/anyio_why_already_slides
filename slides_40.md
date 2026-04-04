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
- AnyIO works on both asyncio and Trio - like `six` for async frameworks

<!-- async/await is NOT asyncio. it's just syntax built on top of the generator protocol. any framework can drive coroutines - Twisted, Trio, Curio all do it with completely different event loops. AnyIO works on both asyncio and Trio, doing the right thing automatically. -->

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

coro = async_range()
gen = coro.__await__()
list(gen)  # [1, 2, 3]  - no asyncio, no event loop
```

<!-- @types.coroutine: marks a generator function as a coroutine function. When the function is called, the resulting generator iterator is also considered a coroutine object and is awaitable. Bridges yield-from generators with async/await. _async_yield is a raw coroutine that just yields a value. async_range is a normal async function built on top - no asyncio anywhere. grab the __await__ iterator, drain it into a list. no event loop, no scheduler, just generators. this is how multiple async frameworks can coexist. -->

---

# The Problems with `asyncio.create_task()`

## It's a "go statement" - and go statements break everything

```python
asyncio.create_task(myfunc())  # Fire and forget!
# Control returns immediately, myfunc() runs in background
# No guaranteed reunion point
```

**Key problem:** Control flow splits with **one-way jump**

- ❌ Functions aren't black boxes - hidden background tasks survive returns
- ❌ Resource cleanup breaks - `async with` can't track orphaned tasks
- ❌ Errors silently drop - no stack to propagate up

<!-- asyncio.create_task is what njs calls a "go statement". it's a one-way jump that splits control flow. parent spawns a child and immediately moves on. child runs off unsupervised. no guaranteed reunion point. functions stop being black boxes, resource cleanup breaks, and errors get silently dropped. -->

---

# Problem: Resource Cleanup Breaks

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

<!-- concrete example. you open a file in an async with block, pass the handle to process_file, block exits, file closes. but if process_file secretly spawned a background task still reading from that handle - boom, error on a closed file. context managers are broken. -->

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

# Two most important reasons to use AnyIO
* incrementally adoptable - drop into an existing asyncio codebase, and your code automatically works on Trio too
* cancellations are level-triggered

<!-- two biggest selling points. first: it's additive - you can sprinkle it into an existing asyncio codebase and optionally add Trio support later. second, and this is the one I really care about: cancellations are level-triggered. this is subtle but it prevents real bugs. -->

---

# Level-Triggered Cancellation

With level cancellation every async operation in a cancelled CancelScope (a scoped
region of code that can be cancelled or given a deadline) will fail with a `CancelledError`

```python
import anyio

async def example():
    with anyio.fail_after(0):
        try:
            await anyio.sleep(1)  # raises CancelledError
        finally:
            await anyio.sleep(1000)  # also raises CancelledError
    # raises TimeoutError as you leave the scope

anyio.run(example)
# Note: not anyio.run(example()) - anyio.run takes a callable, not a coroutine
```

<!-- with level cancellation, once a CancelScope is cancelled, EVERY await inside it raises CancelledError. even in the finally block. the cancellation is a state, not an event. so fail_after(0) means every single await in that scope fails immediately. predictable and safe. note: anyio.run takes a callable, not a coroutine - so no parentheses on example. -->

---

# Edge-Triggered Cancellation (asyncio)

With edge cancellation, `CancelledError` is a one-shot event - once consumed, the next await succeeds even inside a cancelled scope.

```python
import asyncio

async def example():
    async with asyncio.timeout(0):
        try:
            await asyncio.sleep(1)   # raises CancelledError
        finally:
            await asyncio.sleep(1000)  # waits 1000 seconds
    # raises TimeoutError.... eventually

asyncio.run(example())
# Note: not asyncio.run(example) - asyncio.run takes a coroutine, not a callable
```

<!-- now look at the same thing with asyncio. the first await raises CancelledError as expected. but in the finally block the cancellation has been consumed - it was edge-triggered, a one-shot event. so await asyncio.sleep(1000) actually waits 1000 seconds. your timeout of 0 becomes a timeout of 1000. this is a real class of bug. -->

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
<!-- edge cancellation doesn't just cause slowdowns - it can deadlock. here's a real example that hangs forever. crash_soon raises, the TaskGroup cancels task_with_finally, but because cancellation is edge-triggered the finally block's `await never` is NOT cancelled - it just hangs. you have to Ctrl+C multiple times to kill it. with AnyIO's level-triggered cancellation the `await never` is immediately cancelled too. no hang. -->

---

# Shielding from Cancellation

Sometimes you can cancel the work, but you **must wait for it to finish dying**:

- Subprocesses: you can `terminate()` but must still `wait()` to join - otherwise zombie processes
- Threads: can't be interrupted at all - must wait for completion
- Windows IOCP: must wait for cancellation acknowledgement before freeing memory

<!-- sometimes you can cancel the work but you can't just walk away. subprocesses: terminate then join. threads: can't cancel at all. this is where shielding comes in. -->

---

# `asyncio.shield` - The Duct-Tape Approach

```python
try:
    await asyncio.shield(process.wait())
    # ⚠️ If cancelled, shield absorbs the cancel...
    # ... but process.wait() keeps running as a detached task
except asyncio.CancelledError:
    process.terminate()
    # ⚠️ Edge cancellation: this await might be cancelled again
    # before the process exits - leaving it un-joined
    await process.wait()
    raise
```

- ❌ Wraps ONE `await`, orphans the inner task
- ❌ Edge-triggered: cleanup can be interrupted again
- ❌ Can't compose terminate + join as a single logical unit

<!-- asyncio.shield wraps one await and creates an orphaned task. edge cancellation means the process.wait() in the except block can be cancelled again before the process exits, leaving it un-joined. -->

---

# AnyIO Shielded Cancel Scopes

```python
try:
    await process.wait()
    return process.returncode
except anyio.get_cancelled_exc_class():
    process.terminate()
    # Shield the join: we MUST wait for the process to exit
    with anyio.CancelScope(shield=True):
        await process.wait()  # shielded - always completes
    raise
# Pending cancellation reliably re-raised after the shielded scope
```

- ✅ Level-triggered: cancellation is deferred, not lost
- ✅ Scoped: protect the whole terminate-and-join block
- ✅ No zombies: every process is joined

<!-- AnyIO's CancelScope(shield=True) protects a whole block. level-triggered cancellation is deferred and reliably re-raised after. no zombies, no orphans. -->

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

<!-- full comparison side by side. every row is a win for AnyIO. key insight: shielding should be a scope, not a wrapper around a single expression. -->

---

# More AnyIO Features: Memory Object Streams

<!-- ok we've covered the big conceptual stuff - structured concurrency and level-triggered cancellation. now let me show you some practical features. -->

* AnyIO provides `MemoryObjectSendStream` and `MemoryObjectReceiveStream`
* like `asyncio.Queue` but with backpressure, `clone()`, structured shutdown, and `async for`
  * you just make a clone for each producer/consumer
  * use a `with` or `async with` to close the clones
  * Once all the clones of one end are closed, iterating the other end will raise StopAsyncIteration

<!-- memory object streams are like asyncio.Queue but designed right. the killer feature is clone() - each producer/consumer gets their own clone, and when all clones of one end are closed the other end gets a clean StopAsyncIteration. no sentinel values, no manual counting. -->

---

# Memory Object Streams: Full Example

```python
async def consume_ws(url, stream):
    with stream:              # sync - runs before first await
        async with await connect_ws(url) as ws:
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

anyio.run(news_and_weather)
```

<!-- two WebSocket consumers, each with a clone of the send stream, feeding a single receive stream. when both producers finish their clones close, original tx is already closed, so the async for on rx terminates naturally. fully structured shutdown with zero boilerplate. -->

---

# Key Properties

- ✅ Buffer size defaults to 0 → automatic backpressure
- ✅ `clone()` + structured shutdown - unlike asyncio, AnyIO tasks always run to their first `await` before cancellation, so `with stream:` always closes the clone
- ✅ `async for` works naturally, `close()` signals end-of-stream

<!-- default buffer size is 0 so you get backpressure for free. the synchronous `with stream:` runs before any await, so __exit__ always fires and the clone is always closed. -->

---

<style scoped>section { font-size: 20px; padding-top: 10px; }</style>

# Batteries Included

| Category | Feature | Benefit |
|---|---|---|
| **Streams** | `BufferedByteReceiveStream` | `receive_until(delimiter)`, `receive_exactly(n)` - even Trio doesn't have this |
| | `TextReceiveStream` | Incremental UTF-8 decoding over any byte stream |
| | `StapledStream` | Combine separate send/receive into one bidirectional stream |
| **File I/O** | `anyio.Path` | Async drop-in for `pathlib` (no more blocking the event loop) |
| **Testing** | Built-in pytest plugin | `@pytest.mark.anyio` - no need for `pytest-asyncio` |
| **Networking** | TCP/UDP/TLS/subprocesses | Happy Eyeballs built in; async stream I/O |
| **Concurrency** | `tg.start()` | Blocks until the task signals it's ready |
| | Synchronization primitives | `Lock`, `Event`, `Semaphore`, `CapacityLimiter` - portable |
| **Threads** | `to_thread` / `from_thread` | Bidirectional sync↔async bridging with structured cancellation |
| | Subinterpreters | `anyio.to_interpreter.run_sync` for true parallelism (3.13+) |
| **Types** | Fully typed | Great IDE autocompletion and type checker support |

<!-- AnyIO is batteries included. buffered byte reads Trio doesn't have, async pathlib, built-in pytest plugin, full networking stack, bidirectional thread bridging, subinterpreters, and the whole API is fully typed. -->

---
<style scoped>section { font-size: 26px; }</style>

# The Advantage of Being on PyPI

* Python 3.13 fixed TaskGroup deadlocks — but those fixes weren't backported to 3.11/3.12

from the [Python 3.13 changelog](https://docs.python.org/3/whatsnew/3.13.html#asyncio) - `docs.python.org/3/whatsnew/3.13.html#asyncio`:

> Improve the behavior of TaskGroup when an external cancellation collides
> with an internal cancellation. For example, when two task groups are
> nested and both experience an exception in a child task simultaneously,
> it was possible that the outer task group would hang, because its
> internal cancellation was swallowed by the inner task group.

* With asyncio, you need to upgrade your **entire Python version** for bugfixes
* Because AnyIO is on PyPI, you get bugfixes on **all supported Python versions**
* AnyIO currently still supports the EOL Python 3.9 (as of v4.12.1)

<!-- practical advantage of being pip-installable. with asyncio you need to upgrade your entire Python for bugfixes. with AnyIO you just pip install the latest and get fixes everywhere. -->

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

# Wrap Up

* remember: `asyncio` != `async`/`await` - other async frameworks exist (Twisted, Trio, Curio) and AnyIO works across asyncio and Trio
* I've given you a whistle-stop tour of some of my favourite features, there's loads more
   * and more being added all the time
* I hope I've persuaded you to give AnyIO a try
* you might as well give it a go if you already have it installed

<!-- to wrap up: asyncio is not the only async framework - async/await is decoupled from any event loop and other frameworks like Twisted, Trio, and Curio all use the same syntax. AnyIO works across asyncio and Trio. structured concurrency, level-triggered cancellation, great batteries. you've probably already got it installed. give it a go. -->
---

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

<!-- thanks! happy to take questions. I'm graingert on GitHub. -->
