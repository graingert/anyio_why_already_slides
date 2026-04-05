---
marp: true
html: true
---

# Why you should use AnyIO

### ...and why you probably already have it installed

⚡ Lightning Talk · https://graingert.co.uk/why-anyio-already

<!-- hi everyone, I'm going to give you the speedrun on AnyIO. Why you should use it — and why you probably already have it installed. -->

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

# `asyncio` != `async`/`await`

*Most important take-away of this presentation*

- **Three separate things:** async I/O (concept) · `asyncio` (stdlib module) · `async`/`await` (syntax)
- Twisted, Trio, and Curio all use `async`/`await` with their own event loops
- AnyIO works on both asyncio and Trio — like `six` for async frameworks

<!-- async/await is just generators. it's not asyncio. AnyIO works on both asyncio and Trio automatically. -->

---

# It's Generators All the Way Down

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

```python
coro = async_range()
list(coro.__await__())  # [1, 2, 3] — no asyncio, no event loop
```

`async`/`await` is just the generator protocol. Any framework can drive it.

<!-- grab the __await__ iterator, drain it into a list. no event loop, no scheduler, just generators. this is why multiple async frameworks can use the same async/await syntax. -->

---

# `asyncio.create_task()` is the `goto` of Concurrency

```python
asyncio.create_task(myfunc())  # fire and forget — no guaranteed reunion point
```

- ❌ Functions aren't black boxes — background tasks survive returns
- ❌ Resource cleanup breaks — `async with` can't track orphaned tasks
- ❌ Errors silently drop — no stack to propagate up

```python
# The fix: structured concurrency
async with anyio.create_task_group() as tg:
    tg.start_soon(myfunc)
    tg.start_soon(other)
# blocked until ALL tasks finish — errors propagate, cleanup runs
```

<!-- create_task is a go statement. task groups fix it: you can't leave until all children complete. errors propagate, cleanup happens. -->

---

# Level Cancellation vs Edge Cancellation

<style scoped>
table { display: table !important; width: 100% !important; table-layout: fixed !important; }
</style>

<table>
<tr>
<th>AnyIO — level-triggered ✅</th>
<th>asyncio — edge-triggered ❌</th>
</tr>
<tr>
<td>

```python
with anyio.fail_after(0):
    try:
        await anyio.sleep(1)
    finally:
        await anyio.sleep(1000)
        # ALSO raises CancelledError
```

</td>
<td>

```python
async with asyncio.timeout(0):
    try:
        await asyncio.sleep(1)
    finally:
        await asyncio.sleep(1000)
        # waits 1000 seconds! 😱
```

</td>
</tr>
</table>

Edge cancellation = **your 0s timeout becomes a 1000s timeout**. Level cancellation persists — every `await` in a cancelled scope raises. `CancelScope(shield=True)` defers it cleanly for cleanup.

<!-- asyncio edge-triggered cancel is consumed after one catch. AnyIO level-triggered cancel persists. your timeouts actually mean something. -->

---

# Batteries Included

- 🔀 **Memory object streams** — `asyncio.Queue` with backpressure, `clone()`, structured shutdown
- 📖 **`BufferedByteReceiveStream`** — `receive_until(b"\n")`, `receive_exactly(n)` — Trio doesn't have this
- 📁 **`anyio.Path`** — async drop-in for `pathlib`, runs in a thread pool
- 🧪 **Built-in pytest plugin** — `@pytest.mark.anyio`, no `pytest-asyncio` needed
- 🌐 **Networking** — TCP/UDP/TLS/subprocesses, Happy Eyeballs built in
- 📦 **PyPI-shipped bugfixes** — don't wait for a Python release to fix `TaskGroup`

<!-- memory streams, buffered reads, async pathlib, pytest plugin, full networking, PyPI bugfixes. -->

---

# ~~`pip install anyio`~~

You probably already have it.

```
anyio==4.13.0
├── starlette → fastapi, mcp
├── httpx → mcp, jupyterlab
├── jupyter_server → notebook, jupyterlab
└── mcp
```

Installed `httpx`, `fastapi`, `jupyter`, or `mcp`? **AnyIO is already in your virtualenv.** Might as well use it on purpose.

<!-- that's the punchline - if you've installed any modern Python web or data science package, you already have AnyIO. might as well use it intentionally. -->

---

<style scoped>section { font-size: 22px; }</style>

# Any questions?

**These slides:** [graingert.co.uk/why-anyio-already](https://graingert.co.uk/why-anyio-already)

**Further reading:**
- [anyio.readthedocs.io](https://anyio.readthedocs.io) — AnyIO documentation
- [graingert.co.uk/trio-sc](https://graingert.co.uk/trio-sc) — Go statement considered harmful (njs)
- [graingert.co.uk/dijkstra68](https://graingert.co.uk/dijkstra68) — Go To Statement Considered Harmful (1968)
- [graingert.co.uk/dabeaz-gen](https://graingert.co.uk/dabeaz-gen) — Generator Tricks for Systems Programmers
- [graingert.co.uk/dabeaz-coro](https://graingert.co.uk/dabeaz-coro) — A Curious Course on Coroutines and Concurrency
- [graingert.co.uk/dabeaz-final](https://graingert.co.uk/dabeaz-final) — Generators: The Final Frontier

<!-- thanks! happy to take questions. I'm graingert on GitHub. -->
