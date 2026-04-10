---
marp: true
html: true
---

# Happy Eyeballs
### Structured Concurrency vs Callbacks

⚡ Thomas Grainger · graingert

<!-- hi everyone. I'm going to talk about Happy Eyeballs — it's a great case study in how structured concurrency simplifies a genuinely tricky algorithm. I'm going to show you the same algorithm implemented twice: once in Twisted with callbacks, and once in AnyIO with structured concurrency. -->

---

# About Me

<img src="https://avatars.githubusercontent.com/u/413772" alt="graingert" style="display: block; margin: 0 auto;" width="250">

<style scoped>section { font-size: 22px; }</style>

**Networking & async:**
- Core developer of AnyIO, Twisted, and Trio
- CPython triager — asyncio contributor
- uvloop contributor — including Python 3.14 compatibility (AbstractChildWatcher removal)

**Other open source:**
- `PyPy`, `pytest-dev`, `PyCQA`, `Dask` and others

<!-- I'm Thomas Grainger. I'm a core developer of AnyIO, Twisted, and Trio, which puts me in a good position to compare implementations across these libraries. -->

---

# What is Happy Eyeballs? (RFC 6555)

`example.com` resolves to both IPv6 **and** IPv4 — which do you use?

- IPv6 is preferred — but what if the IPv6 path is broken or slow?
- Waiting for a 75-second TCP timeout is not an option

**The solution: race them**

1. Try IPv6 first
2. After **250ms**, try IPv4 in parallel
3. Use whichever connects first — cancel the rest

*Your browser does this. Chrome, Firefox, curl all implement it. So do AnyIO and Twisted.*

<!-- so what is Happy Eyeballs? when you connect to a hostname it can resolve to both IPv6 and IPv4 addresses. IPv6 is preferred, but if the IPv6 path is broken or slow, you don't want to wait for the 75-second TCP timeout. the solution is to race them — start IPv6, wait 250ms, then start IPv4 in parallel, take whichever wins. RFC 6555 was published in 2012. Twisted implemented it in 2013. AnyIO has it built into connect_tcp. the interesting part is HOW they implement it. -->

---

# Twisted (2013): Callbacks

```python
pending: list[Deferred] = []
failures: list[Failure] = []
checkDoneCompleted = False
checkDoneEndpointsLeft = True

@LoopingCall
def iterateEndpoint() -> None:
    endpoint = next(iterEndpoints, None)
    if endpoint is None:
        checkDoneEndpointsLeft = False; checkDone(); return
    eachAttempt = endpoint.connect(protocolFactory)
    pending.append(eachAttempt)
    eachAttempt.addBoth(noLongerPending).addCallback(succeeded).addErrback(failed)

iterateEndpoint.start(self._attemptDelay)  # 300ms — fixed interval
return winner.addBoth(cancelRemainingPending)
```

4 pieces of manual state · 5 nested closures · 1 `LoopingCall`

<!-- Twisted was genuinely ahead of its time implementing this in 2013. but look at the bookkeeping required. four pieces of state: a pending list, a failures list, and two booleans just to track whether you're done. a LoopingCall firing every 300ms. five nested closures. this is the inherent complexity of the callback model — you're manually managing a state machine. -->

---

# AnyIO: Structured Concurrency

```python
async with create_task_group() as tg:
    for _af, addr in target_addrs:
        event = Event()
        tg.start_soon(try_connect, addr, event)
        with move_on_after(happy_eyeballs_delay):
            await event.wait()
```

The task group handles: **cancellation · error propagation · cleanup**

<!-- Five lines. That's the entire concurrency logic. The task group handles cancellation — when one connection succeeds, the task group cancels all the others. Error propagation — if every connection fails, the exceptions are collected and re-raised. And cleanup — tasks can't leak, the with block won't exit until everything is done. All that state you saw in Twisted — the pending list, the failure list, the two booleans — you don't need any of it. The task group is your state machine. -->

---

# A subtlety: adaptive vs fixed delay

**Twisted**: `LoopingCall` fires every 300ms regardless of what the previous attempt did

**AnyIO**: starts the next attempt when the previous one finishes *or* 250ms passes — whichever comes first

```python
async def try_connect(remote_host, event):
    try:
        stream = await connect(...)
        ...
    finally:
        event.set()  # fires immediately on success or failure

# main loop: wait up to 250ms, then move on regardless
with move_on_after(happy_eyeballs_delay):
    await event.wait()
```

Attempt 0 fails in 10ms → attempt 1 starts at 10ms, not 250ms

<!-- This is actually more correct per RFC 8305. Fast failures shouldn't penalise the user with a full delay. The Twisted LoopingCall always waits the full interval. -->

---

# Also: Twisted only reports the last failure

```python
# Twisted
def checkDone() -> None:
    if pending or checkDoneCompleted or checkDoneEndpointsLeft:
        return
    winner.errback(failures.pop())  # ← only the last one
```

```python
# AnyIO
cause = (
    oserrors[0] if len(oserrors) == 1
    else ExceptionGroup("multiple connection attempts failed", oserrors)
)
raise OSError("All connection attempts failed") from cause
```

AnyIO gives you *all* the failures.

<!-- This matters for debugging. If IPv6 and IPv4 both fail for different reasons, Twisted only tells you about the last one. AnyIO wraps them all in an ExceptionGroup. -->

---

# Twisted even warns about circular references

```python
def _canceller(cancelled: Deferred[IProtocol]) -> None:
    # This canceller must remain defined outside of
    # `startConnectionAttempts`, because Deferred should not
    # participate in cycles with their cancellers; that would
    # create a potentially problematic circular reference and
    # possibly gc.garbage.
    ...
```

AnyIO's task group handles cancellation — **no closures, no cycles, no comment needed**.

<!-- The Twisted code itself documents the footgun. Structured concurrency eliminates the whole class of problem. -->

---

# Bonus: CPython asyncio had bugs

asyncio also has Happy Eyeballs (`happy_eyeballs_delay` in `asyncio.open_connection`):

- **Reference cycles** — failed-attempt exceptions were trapped by the implementation, preventing GC (Oct 2024)
- **`staggered_race` task leaks** — tasks weren't cancelled on success, plus a `NameError` when logging unhandled errors

I found and fixed both — merged across Python 3.12, 3.13, and `main`.

AnyIO's structured approach avoids this whole class of bug.

<!-- Finding bugs in the implementation you're replacing is a good way to validate that the replacement is better. Both bugs stem from manual bookkeeping that structured concurrency eliminates. -->

---

<style scoped>section { font-size: 22px; }</style>

# Further Reading

**These slides:** [graingert.co.uk/why-anyio-already](https://graingert.co.uk/why-anyio-already)

- [anyio.readthedocs.io](https://anyio.readthedocs.io) — AnyIO docs
- [datatracker.ietf.org/doc/html/rfc6555](https://datatracker.ietf.org/doc/html/rfc6555) — Happy Eyeballs
- [datatracker.ietf.org/doc/html/rfc8305](https://datatracker.ietf.org/doc/html/rfc8305) — Happy Eyeballs v2
- [github.com/python/cpython/issues/124858](https://github.com/python/cpython/issues/124858) — asyncio refcycle fix
- [github.com/python/cpython/pull/128475](https://github.com/python/cpython/pull/128475) — staggered_race leak fix
- [graingert.co.uk/glyph-watering-eyeballs](https://graingert.co.uk/glyph-watering-eyeballs) — Glyph's WIP branch

<!-- thanks for listening! links are on screen. -->

---

<style scoped>section { padding: 20px; } pre { font-size: 4px !important; line-height: 1.2 !important; margin: 0 !important; }</style>

# Twisted Happy Eyeballs: The Full Patch (still not merged, 9 years later)

<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:0.3em">
<div>

```diff
diff --git a/src/twisted/internet/_corohost.py b/src/twisted/internet/_corohost.py
new file mode 100644
index 000000000..b680f87c7
--- /dev/null
+++ b/src/twisted/internet/_corohost.py
@@ -0,0 +1,277 @@
+# -*- test-case-name: twisted.internet.test.test_endpoints -*-
+from __future__ import annotations
+
+from dataclasses import dataclass, field
+from enum import Enum, auto
+from typing import (
+    TYPE_CHECKING,
+    AsyncIterable,
+    Callable,
+    Generic,
+    Literal,
+    Tuple,
+    TypeVar,
+    Union,
+)
+
+from zope.interface import implementer
+
+from twisted.internet.address import HostnameAddress, IPv4Address, IPv6Address
+from twisted.internet.defer import CancelledError, Deferred, succeed
+from twisted.internet.error import ConnectingCancelledError, DNSLookupError
+from twisted.internet.interfaces import (
+    IProtocolFactory,
+    IReactorTime,
+    IResolutionReceiver,
+    IStreamClientEndpoint,
+)
+from twisted.internet.task import deferLater
+from twisted.python.failure import Failure
+from ._shutil import Outstanding
+
+if TYPE_CHECKING:
+    from twisted.internet.endpoints import HostnameEndpoint
+
+from twisted.internet.interfaces import (
+    IAddress,
+    IHostResolution,
+    IProtocol as TwistedProtocol,
+)
+
+T = TypeVar("T")
+X = TypeVar("X")
+
+
+class DoneSentinel(Enum):
+    Done = auto()
+
+
+def push2aiter() -> tuple[Callable[[T], None], Callable[[], None], AsyncIterable[T]]:
+    """
+    Create a Deferred coroutine which presents an async iterable, and a
+    callable that will push values into it and a callable that will stop it.
+    """
+    q: list[Deferred[Union[T, Literal[DoneSentinel.Done]]]] = []
+
+    async def aiter() -> AsyncIterable[T]:
+        while True:
+            if not q:
+                assert 0
+                q.append(Deferred())  # type:ignore[unreachable]
+            out = await q.pop(0)
+            if out is DoneSentinel.Done:
+                return
+            # 'is done' is a type guard that mypy can't see
+            yield out
+
+    def push(value: Union[T, DoneSentinel]) -> None:
+        q.append(succeed(value))
+
+    def stop() -> None:
+        push(DoneSentinel.Done)
+
+    return push, stop, aiter()
+
+
+def addr2endpoint(
+    hostnameEndpoint: HostnameEndpoint,
+    address: IAddress,
+) -> Union[IStreamClientEndpoint, None]:
+    """
+    Convert an address into an endpoint
+    """
+    # Circular imports.
+    from twisted.internet.endpoints import TCP4ClientEndpoint, TCP6ClientEndpoint
+
+    reactor = hostnameEndpoint._reactor
+    timeout = hostnameEndpoint._timeout
+    bindAddress = hostnameEndpoint._bindAddress
+
+    if isinstance(address, IPv6Address):
+        return TCP6ClientEndpoint(
+            reactor, address.host, address.port, timeout, bindAddress
+        )
+    if isinstance(address, IPv4Address):
+        return TCP4ClientEndpoint(
+            reactor, address.host, address.port, timeout, bindAddress
+        )
+    return None
+
+
+@dataclass
+class MultiFirer(Generic[T]):
+    deferreds: Outstanding[T] = field(default_factory=Outstanding)
+    activeTimeout: Union[Deferred[None], None] = None
+    waiting: Union[
+        Deferred[Union[tuple[Literal[True], T], tuple[Literal[False], None]]], None
+    ] = None
+    hasResult: bool = False
+    hasFailure: bool = False
+    finalResult: Union[T, None] = None
+    ended: bool = False
+    failures: list[Failure] = field(default_factory=list)
+
+    def add(self, deferred: Deferred[T]) -> None:
+        """
+        Add a Deferred that might be waited upon.
+        """
+        self.deferreds.add(deferred)
+
+        def complete(result: T) -> T:
+            self.hasResult = True
+            self.finalResult = result
+            self._maybeCompleteWaiting(True, self.finalResult)
+            return result
+
+        def failed(failure: Failure) -> None:
+            self.failures.append(failure)
+            self._maybeCompleteWaiting(False, None)
+            return None
+
+        deferred.addCallbacks(complete, failed)
+
+    def wait(
+        self, clock: IReactorTime, seconds: float
+    ) -> Deferred[Union[tuple[Literal[True], T], tuple[Literal[False], None]]]:
+        assert self.waiting is None, "no waiting while waiting"
+
+        def cancel(d: Deferred[tuple[bool, Union[T, None]]]) -> None:
+            self.deferreds.cancel()
+
+        def timedOut(nothing: None) -> None:
+            self._maybeCompleteWaiting(False, None)
+
+        def ignoreCancel(f: Failure) -> None:
+            f.trap(CancelledError)
+
+        self.activeTimeout = deferLater(clock, seconds).addCallbacks(
+            timedOut, ignoreCancel
+        )
+        w = self.waiting = Deferred(cancel)
+        self._maybeFinallyFail()
+        return w
+
+    def end(self) -> Deferred[T]:
+        """
+        No more results will be added.
+        """
+        assert self.waiting is None, "no ending while waiting"
+        self.ended = True
+        self.activeTimeout = Deferred(lambda dself: dself.callback(None))
+
+        def cancel(d: Deferred[Tuple[bool, Union[T, None]]]) -> None:
+            self.deferreds.cancel()
+
+        def definitely(result: Tuple[bool, Union[T, None]]) -> T:
+            yup, actual = result
+            # T might hypothetically include None so we can't assert here
+            return actual  # type: ignore
+
+        w = self.waiting = Deferred(cancel)
+        x = w.addCallback(definitely)
+        self._maybeFinallyFail()
+        return x
+
+    def cancel(self) -> None:
+        self.deferreds.cancel()
+
+    def _maybeFinallyFail(self) -> None:
+        """ """
+        if (
+            self.waiting is not None
+            and self.activeTimeout is not None
+            and self.ended
+            and self.deferreds.empty()
+            and not self.hasResult
+        ):
+            self.activeTimeout.cancel()
+            self.activeTimeout = None
+            it, self.waiting = self.waiting, None
+            e: Union[Failure, Exception]
+            if len(self.failures) == 1:
+                e = self.failures[0]
+            else:
+                e = RuntimeError(f"multiple failures {self.failures}")
+            it.errback(e)
+
+    def _maybeCompleteWaiting(self, actuallyDone: bool, value: Union[T, None]) -> None:
+        self._maybeFinallyFail()
+        if self.waiting is not None and self.activeTimeout is not None:
+            self.activeTimeout.cancel()
+            self.activeTimeout = None
+            it, self.waiting = self.waiting, None
+            assert actuallyDone or value is None
+            result: tuple[Literal[True], T] | tuple[Literal[False], None] = (
+                actuallyDone,
+                value,
+            )  # type:ignore[assignment]
+            it.callback(result)
+
+
+async def _start(
+    endpoint: HostnameEndpoint,
+    pf: IProtocolFactory,
+) -> TwistedProtocol:
+    """
+    resolver coroutine that runs
+    """
+    assert endpoint is not None, "Wtf"
+    p: Callable[[IAddress], None]
+    s: Callable[[], None]
+    ai: AsyncIterable[IAddress]
+
+    p, s, ai = push2aiter()
+
+    @implementer(IResolutionReceiver)
+    class res:
+        def resolutionBegan(self, resolutionInProgress: IHostResolution) -> None:
+            pass
+
+        def addressResolved(self, address: IAddress) -> None:
+            p(address)
+
+        def resolutionComplete(self) -> None:
+            s()
+
+    reactor = endpoint._reactor
+    resolver = endpoint._getNameResolverAndMaybeWarn(reactor)
+    resolver.resolveHostName(res(), endpoint._hostText, portNumber=endpoint._port)
+
+    mf: MultiFirer[TwistedProtocol] = MultiFirer()
+    try:
+        attempts = 0
+        async for addr in ai:
+            ep = addr2endpoint(endpoint, addr)
+            if ep is None:
+                continue
+            attempts += 1
+            mf.add(ep.connect(pf))
+            done, result = await mf.wait(reactor, endpoint._attemptDelay)
+            if done:
+                assert result is not None
+                return result
+        if not attempts:
+            raise DNSLookupError(
+                f"no results for hostname lookup: {endpoint._hostText}"
+            )
+        return await mf.end()
+    finally:
+        ty, v, tb = exc_info()
+        if ty is not GeneratorExit:
+            mf.cancel()
+
+
+from sys import exc_info
+
+
+def start(
+    endpoint: HostnameEndpoint,
+    pf: IProtocolFactory,
+) -> Deferred[TwistedProtocol]:
+    def translateCancel(f: Failure) -> Failure:
+        f.trap(CancelledError, ConnectingCancelledError)
+        raise ConnectingCancelledError(
+            HostnameAddress(endpoint._hostBytes, endpoint._port)
+        )
+
+    return Deferred.fromCoroutine(_start(endpoint, pf)).addErrback(translateCancel)
diff --git a/src/twisted/internet/_shutil.py b/src/twisted/internet/_shutil.py
new file mode 100644
index 000000000..9d73b5385
--- /dev/null
+++ b/src/twisted/internet/_shutil.py
@@ -0,0 +1,75 @@
+from dataclasses import dataclass, field
+from itertools import count
+from typing import (
+    Callable,
+    Dict,
+    FrozenSet,
+    Generic,
+    Iterable,
+    Iterator,
+    Set,
+    Tuple,
+    TypeVar,
+)
+
+from twisted.internet.defer import Deferred
+
+T = TypeVar("T")
+
+
+@dataclass
+class CallWhenAll(Generic[T]):
+    _call: Callable[[], None]
+    _required: FrozenSet[T]
+    _present: Set[T] = field(default_factory=set)
+    _called: bool = False
+
+    def check(self, checks: Iterable[Tuple[bool, T]]) -> None:
+        for shouldAdd, item in sorted(checks, key=lambda x: x[0]):
+            method = self.add if shouldAdd else self.remove
+            method(item)
+
+    def add(self, item: T) -> None:
+        if item in self._present:
+            return
+        self._present.add(item)
+        if self._called:
+            return
+        remaining = self._required - self._present
+        if not remaining:
+            self._called = True
+            self._call()
+
+    def remove(self, item: T) -> None:
+        if item not in self._present:
+            return
+        self._present.remove(item)
+
+
+AttemptId = int
+
+
+@dataclass
+class Outstanding(Generic[T]):
+    _ds: Dict[int, Deferred[T]] = field(default_factory=dict)
+    _id: Iterator[AttemptId] = field(default_factory=count)
+
+    def add(self, d: Deferred[T]) -> Deferred[T]:
+        nextId = next(self._id)
+        self._ds[nextId] = d
+
+        def done(result: T) -> T:
+            if nextId in self._ds:
+                # during cancel() we remove first
+                del self._ds[nextId]
+            return result
+
+        return d.addBoth(done)
+
+    def cancel(self) -> None:
+        while self._ds:
+            k, v = self._ds.popitem()
+            v.cancel()
+
+    def empty(self) -> bool:
+        return len(self._ds) == 0
diff --git a/src/twisted/internet/_statefulhost.py b/src/twisted/internet/_statefulhost.py
new file mode 100644
index 000000000..b76e3a04b
--- /dev/null
+++ b/src/twisted/internet/_statefulhost.py
@@ -0,0 +1,567 @@
+# -*- test-case-name: twisted.internet.test.test_endpoints -*-
+
+from functools import wraps
+
+from zope.interface import implementer
+
+from automat import MethodicalMachine as _automat
+
```

</div>
<div>

```diff
+from twisted.internet.address import HostnameAddress, IPv4Address, IPv6Address
+from twisted.internet.defer import Deferred
+from twisted.internet.error import ConnectingCancelledError, DNSLookupError
+from twisted.internet.interfaces import IResolutionReceiver
+from twisted.python.failure import Failure
+
+
+class _FeedbackInput:
+    """
+    This feature really belongs in automat.
+    """
+
+    def __init__(self, machine):
+        """ """
+        self.machine = machine
+
+    def __call__(self, method):
+        """ """
+        anInput = self.machine.input()(method)
+        return _FeedbackInputOnClass(method, anInput)
+
+
+class _FeedbackInputOnClass:
+
+    """ """
+
+    def __init__(self, function, input):
+        """ """
+        self.function = function
+        self.input = input
+
+    def __get__(self, oself, type=None):
+        """ """
+        theInput = self.input.__get__(oself, type)
+
+        @wraps(self.function)
+        def function(ooself, *a, **kw):
+            wasProcessingFeedback = ooself._isProcessingFeedback
+            ooself._isProcessingFeedback = True
+            try:
+                try:
+                    if not wasProcessingFeedback:
+                        assert getattr(ooself, "_pendingFeedback", None) is None
+                        ooself._pendingFeedback = []
+                    result = theInput(*a, **kw)
+                    if not wasProcessingFeedback:
+                        while ooself._pendingFeedback:
+                            f = ooself._pendingFeedback.pop(0)
+                            f()
+                        assert not ooself._pendingFeedback
+                    return result
+                finally:
+                    if not wasProcessingFeedback:
+                        ooself._isProcessingFeedback = False
+                        # assert not ooself._pendingFeedback, ooself._pendingFeedback
+                        del ooself._pendingFeedback
+            except:
+                import traceback
+
+                traceback.print_exc()
+                raise
+
+        function.input = theInput
+        return function.__get__(oself, type)
+
+
+@implementer(IResolutionReceiver)
+class _HostnameConnectionAttempt:
+    """ """
+
+    machine = _automat()
+
+    def __init__(self, hostnameEndpoint, protocolFactory):
+        """ """
+        self.hostnameEndpoint = hostnameEndpoint
+        self.protocolFactory = protocolFactory
+        self.deferred = Deferred(self.cancel)
+        self.failures = []
+        self._endpointQueue = []
+        self._pendingConnectionAttempts = []
+        self._isProcessingFeedback = False
+
+    def cancel(self, deferred):
+        """ """
+        self.failures.append(
+            ConnectingCancelledError(
+                HostnameAddress(
+                    self.hostnameEndpoint._hostBytes, self.hostnameEndpoint._port
+                )
+            )
+        )
+        self.userCancellation()
+
+    @machine.state(initial=True)
+    def _idle(self):
+        """
+        The idle state.
+        """
+
+    @machine.state()
+    def _awaitingResolution(self):
+        """
+        Name resolution has been initiated but has not yet begun.
+        """
+
+    @machine.state()
+    def _noNamesYet(self):
+        """ """
+
+    @machine.state()
+    def _resolvingNames(self):
+        """
+        Name resolution is in progress.
+        """
+
+    @machine.state()
+    def _resolvingWithPending(self):
+        """
+        Name resolution and an outgoing attempt are both in progress.
+        """
+
+    @machine.state()
+    def _justPending(self):
+        """
+        Name resolution is done, but there are pending connection attempts.
+        """
+
+    @machine.state()
+    def _justQueued(self):
+        """
+        There are no pending connections right now, but there are queued ones.
+        """
+
+    @machine.state()
+    def _resolvingWithPendingAndQueued(self):
+        """
+        This is starting to look like a cartesian product...
+        """
+
+    @machine.state()
+    def _pendingAndQueued(self):
+        """
+        There are pending connection attempts as well as queued connections.
+        """
+
+    @machine.state()
+    def _done(self):
+        """
+        The operation is complete.
+        """
+
+    def feedback(self, thunk):
+        """
+        Outputs which want to produce an input to the same state machine can
+        call this method to provide work to do after the currently queued list
+        of state transitions is complete.
+        """
+        assert self._isProcessingFeedback
+        self._pendingFeedback.append(thunk)
+
+    @_FeedbackInput(machine)
+    def start(self):
+        """ """
+
+    @_FeedbackInput(machine)
+    def resolutionBegan(self, resolutionInProgress):
+        """
+        Hostname resolution began.
+        """
+
+    def addressResolved(self, address):
+        """
+        An address was resolved.
+        """
+        endpoint = self.addr2endpoint(address)
+        if endpoint is not None:
+            self.endpointResolved(endpoint)
+
+    @_FeedbackInput(machine)
+    def endpointResolved(self, endpoint):
+        """
+        An endpoint of a known type was resolved from an address.
+        """
+
+    @_FeedbackInput(machine)
+    def resolutionComplete(self):
+        """
+        Hostname resolution was completed.
+        """
+
+    @_FeedbackInput(machine)
+    def established(self, protocol):
+        """
+        A connection has been established.
+        """
+
+    @_FeedbackInput(machine)
+    def oneAttemptFailed(self, reason):
+        """
+        A connection cannot be established
+        """
+
+    @_FeedbackInput(machine)
+    def endpointQueueEmpty(self):
+        """
+        There are no more endpoints in the outbound queue.
+        """
+
+    @_FeedbackInput(machine)
+    def noPendingConnections(self):
+        """
+        The last pending connection has terminated, in either success or
+        failure.
+        """
+
+    @_FeedbackInput(machine)
+    def userCancellation(self):
+        """
+        A user cancelled the outermost deferred.
+        """
+
+    @_FeedbackInput(machine)
+    def attemptDelayExpired(self):
+        """
+        It's time to unqueue the next connection attempt.
+        """
+
+    @_FeedbackInput(machine)
+    def moreQueuedEndpoints(self):
+        """
+        More endpoints remain in the queue.
+        """
+
+    def addr2endpoint(self, address):
+        """
+        Convert an address into an endpoint
+        """
+        from twisted.internet.endpoints import TCP4ClientEndpoint, TCP6ClientEndpoint
+
+        reactor = self.hostnameEndpoint._reactor
+        timeout = self.hostnameEndpoint._timeout
+        bindAddress = self.hostnameEndpoint._bindAddress
+        if isinstance(address, IPv6Address):
+            return TCP6ClientEndpoint(
+                reactor, address.host, address.port, timeout, bindAddress
+            )
+        if isinstance(address, IPv4Address):
+            return TCP4ClientEndpoint(
+                reactor, address.host, address.port, timeout, bindAddress
+            )
+        return None
+
+    # --- Outputs ---
+
+    @machine.output()
+    def begin(self):
+        """
+        Start doing name resolution.
+        """
+
+        @self.feedback
+        def doResolution():
+            self.resolutionInProgress = (
+                self.hostnameEndpoint._nameResolver.resolveHostName(
+                    self,
+                    self.hostnameEndpoint._hostText,
+                    portNumber=self.hostnameEndpoint._port,
+                )
+            )
+
+        return self.deferred
+
+    @machine.output()
+    def queueOneAttempt(self, endpoint):
+        """
+        Add an endpoint to the list of endpoints that we should still use.
+        """
+        self._endpointQueue.append(endpoint)
+
+    @machine.output()
+    def doOneAttempt(self, endpoint):
+        """
+        Make one outbound connection attempt right now.
+        """
+        self._doOneAttempt()
+
+    @machine.output()
+    def doOneAttempt0(self):
+        """
+        Same.
+        """
+        self._doOneAttempt()
+
+    def _doOneAttempt(self):
+        """ """
+        self.lastAttemptTime = self.hostnameEndpoint._reactor.seconds()
+
+        @self.feedback
+        def oneAttempt():
+            endpoint = self._endpointQueue.pop(0)
+            if not self._endpointQueue:
+                self.endpointQueueEmpty()
+            else:
+                self.moreQueuedEndpoints()
+
+            connected = endpoint.connect(self.protocolFactory)
+            self._pendingConnectionAttempts.append(connected)
+
+            def removePending(result):
+                self._pendingConnectionAttempts.remove(connected)
+                return result
+
+            connected.addBoth(removePending)
+            connected.addCallbacks(self.established, self.failures.append)
+
+            def maybeNoMoreConnections(result):
+                if not self._pendingConnectionAttempts:
+                    self.noPendingConnections()
+
+            connected.addBoth(maybeNoMoreConnections)
+
+    @machine.output()
+    def oneAttemptLater(self, endpoint):
+        """ """
+        self._oneAttemptLater()
+
+    @machine.output()
+    def oneAttemptLater0(self):
+        """ """
+        self._oneAttemptLater()
+
+    nextAttemptCall = None
+
+    def _oneAttemptLater(self):
+        """ """
+        assert self.nextAttemptCall is None
+
+        def noneAndInput():
+            self.nextAttemptCall = None
+            self.attemptDelayExpired()
+
+        self.nextAttemptCall = self.hostnameEndpoint._reactor.callLater(
+            self.hostnameEndpoint._attemptDelay
+            - (self.hostnameEndpoint._reactor.seconds() - self.lastAttemptTime),
+            noneAndInput,
+        )
+
+    @machine.output()
+    def cancelTimer(self, protocol):
+        """ """
+        call = self.nextAttemptCall
+        self.nextAttemptCall = None
+        self.feedback(call.cancel)
+
+    @machine.output()
+    def cancelTimer0(self):
+        """ """
+        call = self.nextAttemptCall
+        self.nextAttemptCall = None
+        self.feedback(call.cancel)
+
+    @machine.output()
+    def cancelResolution1(self, protocol):
+        """ """
+        self.cancelResolution0()
+
+    @machine.output()
+    def cancelResolution0(self):
+        """ """
+        self.resolutionInProgress.cancel()
+
+    @machine.output()
+    def cancelOtherPending1(self, protocol):
+        """ """
+        self.feedback(self.cancelOtherPending)
+
+    @machine.output()
+    def cancelOtherPending0(self):
```

</div>
<div>

```diff
+        """ """
+        self.feedback(self.cancelOtherPending)
+
+    def cancelOtherPending(self):
+        """ """
+        while self._pendingConnectionAttempts:
+            self._pendingConnectionAttempts[0].cancel()
+
+    @machine.output()
+    def complete(self, protocol):
+        """ """
+        self.feedback(lambda: self.deferred.callback(protocol))
+
+    @machine.output()
+    def connectionFailure(self):
+        """ """
+        self.deferred.errback(self.failures.pop())
+
+    @machine.output()
+    def resolutionFailure(self):
+        """
+        Name resolution yielded no results.
+        """
+        self.deferred.errback(
+            Failure(
+                DNSLookupError(
+                    "no results for hostname lookup: {}".format(
+                        self.hostnameEndpoint._hostStr
+                    )
+                )
+            )
+        )
+
+    _idle.upon(
+        start.input,
+        enter=_awaitingResolution,
+        outputs=[begin],
+        collector=lambda gen: next(iter(list(gen))),
+    )
+
+    _awaitingResolution.upon(resolutionBegan.input, enter=_noNamesYet, outputs=[])
+
+    _noNamesYet.upon(
+        endpointResolved.input,
+        enter=_resolvingWithPending,
+        outputs=[queueOneAttempt, doOneAttempt],
+    )
+    _noNamesYet.upon(
+        resolutionComplete.input,
+        enter=_done,
+        outputs=[resolutionFailure],
+    )
+    _noNamesYet.upon(userCancellation.input, enter=_done, outputs=[cancelResolution0])
+
+    _resolvingNames.upon(
+        endpointResolved.input,
+        enter=_resolvingWithPending,
+        outputs=[queueOneAttempt, doOneAttempt],
+    )
+    _resolvingNames.upon(
+        resolutionComplete.input,
+        enter=_done,
+        outputs=[connectionFailure],
+    )
+
+    _resolvingWithPending.upon(
+        noPendingConnections.input,
+        enter=_resolvingNames,
+        outputs=[],
+    )
+    _resolvingWithPending.upon(
+        endpointResolved.input,
+        enter=_resolvingWithPendingAndQueued,
+        outputs=[queueOneAttempt, oneAttemptLater],
+    )
+    _resolvingWithPending.upon(
+        endpointQueueEmpty.input,
+        enter=_resolvingWithPending,
+        outputs=[],
+    )
+
+    _resolvingWithPendingAndQueued.upon(
+        endpointQueueEmpty.input, enter=_resolvingWithPending, outputs=[]
+    )
+    _resolvingWithPendingAndQueued.upon(
+        resolutionComplete.input, enter=_pendingAndQueued, outputs=[]
+    )
+    _resolvingWithPendingAndQueued.upon(
+        noPendingConnections.input, enter=_resolvingWithPendingAndQueued, outputs=[]
+    )
+
+    _pendingAndQueued.upon(
+        moreQueuedEndpoints.input, enter=_pendingAndQueued, outputs=[]
+    )
+    # this one's a bit weird; the queued connection will inevitably _become_ a
+    # pending connection, so _pendingAndQueued is still an appropriate state
+    # despite the lack of anything presently pending
+    _pendingAndQueued.upon(
+        noPendingConnections.input,
+        enter=_justQueued,
+        outputs=[cancelTimer0, doOneAttempt0],
+        collector=list,
+    )
+
+    _justQueued.upon(
+        moreQueuedEndpoints.input,
+        enter=_pendingAndQueued,
+        outputs=[oneAttemptLater0],
+        collector=list,
+    )
+    _justQueued.upon(
+        noPendingConnections.input, enter=_justQueued, outputs=[doOneAttempt0]
+    )
+    _justQueued.upon(endpointQueueEmpty.input, enter=_justPending, outputs=[])
+
+    _resolvingWithPendingAndQueued.upon(
+        endpointResolved.input,
+        enter=_resolvingWithPendingAndQueued,
+        outputs=[queueOneAttempt],
+    )
+    _resolvingWithPendingAndQueued.upon(
+        established.input,
+        enter=_done,
+        outputs=[cancelResolution1, cancelOtherPending1, cancelTimer, complete],
+        collector=list,
+    )
+    _resolvingWithPendingAndQueued.upon(
+        attemptDelayExpired.input, enter=_resolvingWithPending, outputs=[doOneAttempt0]
+    )
+
+    _pendingAndQueued.upon(
+        attemptDelayExpired.input, enter=_pendingAndQueued, outputs=[doOneAttempt0]
+    )
+    _pendingAndQueued.upon(endpointQueueEmpty.input, enter=_justPending, outputs=[])
+    _pendingAndQueued.upon(
+        established.input,
+        enter=_done,
+        outputs=[cancelOtherPending1, cancelTimer, complete],
+        collector=list,
+    )
+
+    _resolvingWithPending.upon(
+        established.input, enter=_done, outputs=[cancelResolution1, complete]
+    )
+    _resolvingWithPending.upon(
+        resolutionComplete.input,
+        enter=_justPending,
+        outputs=[],
+    )
+
+    _justPending.upon(
+        moreQueuedEndpoints.input,
+        enter=_pendingAndQueued,
+        outputs=[
+            oneAttemptLater0,
+        ],
+    )
+    _justPending.upon(
+        endpointQueueEmpty.input,
+        enter=_justPending,
+        outputs=[],
+    )
+    _justPending.upon(
+        noPendingConnections.input,
+        enter=_done,
+        outputs=[connectionFailure],
+        collector=list,
+    )
+    _justPending.upon(
+        userCancellation.input,
+        enter=_done,
+        outputs=[cancelOtherPending0, connectionFailure],
+    )
+    _justPending.upon(
+        established.input,
+        enter=_done,
+        outputs=[cancelOtherPending1, complete],
+        collector=list,
+    )
+
+    _done.upon(noPendingConnections.input, enter=_done, outputs=[], collector=list)
diff --git a/src/twisted/internet/_statefulhost2.py b/src/twisted/internet/_statefulhost2.py
new file mode 100644
index 000000000..61c80b905
--- /dev/null
+++ b/src/twisted/internet/_statefulhost2.py
@@ -0,0 +1,222 @@
+from dataclasses import dataclass, field
+from typing import TYPE_CHECKING, List, Protocol, TypeVar
+
+from zope.interface import implementer
+
+from automat import TypeMachineBuilder
+
+from twisted.internet.address import IPv4Address, IPv6Address
+from twisted.internet.defer import Deferred as D
+from twisted.internet.error import DNSLookupError
+from twisted.internet.interfaces import (
+    IAddress,
+    IDelayedCall,
+    IHostResolution,
+    IProtocol,
+    IProtocolFactory,
+    IResolutionReceiver,
+    IStreamClientEndpoint,
+)
+from twisted.internet.protocol import Protocol as TwistedProtocol
+from twisted.python.failure import Failure
+
+if TYPE_CHECKING:
+    from twisted.internet.endpoints import HostnameEndpoint
+
+T = TypeVar("T")
+
+
+@implementer(IResolutionReceiver)
+class CxnTry(Protocol):
+    # IResolutionReceiver
+    def resolutionBegan(self, resolutionInProgress: IHostResolution) -> None:
+        ...
+
+    def addressResolved(self, address: IAddress) -> None:
+        ...
+
+    def resolutionComplete(self) -> None:
+        ...
+
+    # Internal Methods
+    def start(self) -> D[IProtocol]:
+        ...
+
+    def established(self, protocol: TwistedProtocol) -> None:
+        ...
+
+    def noPendingConnections(self) -> None:
+        ...
+
+    def userCancellation(self, deferred: D[IProtocol]) -> None:
+        ...
+
+    def attemptDelayExpired(self) -> None:
+        ...
+
+
+def addr2endpoint(
+    hostnameEndpoint: HostnameEndpoint, address: IAddress
+) -> IStreamClientEndpoint:
+    # Circular imports.
+    from twisted.internet.endpoints import TCP4ClientEndpoint, TCP6ClientEndpoint
+
+    _endpoints = {IPv6Address: TCP6ClientEndpoint, IPv4Address: TCP4ClientEndpoint}
+    assert isinstance(address, (IPv4Address, IPv6Address))
+    return _endpoints[type(address)](
+        hostnameEndpoint._reactor,
+        address.host,
+        address.port,
+        hostnameEndpoint._timeout,
+        hostnameEndpoint._bindAddress,
+    )
+
+
+@dataclass
+class AttemptState:
+    deferred: D[IProtocol]
+    endpoint: HostnameEndpoint
+    protocolFactory: IProtocolFactory
+    lastAttemptTime: float = 0.0
+    pendingCxnTrys: List[D[IProtocol]] = field(default_factory=list)
+    failures: list[Failure] = field(default_factory=list)
+    nextAttemptCall: IDelayedCall | None = None
+    resolutionInProgress: IHostResolution | None = None
+
+    def oneAttemptLater(self, machine: CxnTry) -> None:
+        def noneAndInput() -> None:
+            self.nextAttemptCall = None
+            machine.attemptDelayExpired()
+
+        assert self.nextAttemptCall is None
+        self.nextAttemptCall = self.endpoint._reactor.callLater(
+            self.endpoint._attemptDelay
+            - (self.endpoint._reactor.seconds() - self.lastAttemptTime),
+            noneAndInput,
+        )
+
+    def queueOneAttempt(self, attempt: CxnTry, address: IAddress) -> None:
+        def removePending(result: T) -> T:
+            self.pendingCxnTrys.remove(connected)
+            return result
+
+        def maybeNoMoreConnections(result: object) -> None:
+            if not self.pendingCxnTrys:
+                attempt.noPendingConnections()
+
+        self.lastAttemptTime = self.endpoint._reactor.seconds()
+        endpoint = addr2endpoint(self.endpoint, address)
+        connected = endpoint.connect(self.protocolFactory)
+        self.pendingCxnTrys.append(connected)
+        connected.addBoth(removePending)
+        connected.addCallbacks(attempt.established, self.failures.append)
+        connected.addBoth(maybeNoMoreConnections)
+
+
+def rememberRes(
+    attempt: CxnTry, core: AttemptState, resolutionInProgress: IHostResolution
+) -> IHostResolution:
+    return resolutionInProgress
+
+
+def addressResolved(attempt: CxnTry, core: AttemptState, address: IAddress) -> None:
+    core.queueOneAttempt(attempt, address)
+
+
+# states
+build = TypeMachineBuilder(CxnTry, AttemptState)
+idle = build.state("idle")
+"initial idle state"
+awaitingResolution = build.state("awaitingResolution")
+"resolveHostName has been called, but no names have yet been resolved"
+noNamesYet = build.state("noNamesYet", rememberRes)
+"resolutionBegan called on the resolution receiver, but no names yet"
+resolvingWithPending = build.state("resolvingWithPending")
+"at least one address has been resolved, and there are pending .connect() calls"
+resolvingNames = build.state("resolvingNames")
+"at least one address has been resolved, and there are no pending .connect() calls"
+justPending = build.state("justPending")
+"There are no queued connections right now, but there are pending ones."
+justQueued = build.state("justQueued")
+"There are no pending connections right now, but there are queued ones."
+resolvingWithPendingAndQueued = build.state("resolvingWithPendingAndQueued")
+pendingAndQueued = build.state("pendingAndQueued")
+done = build.state("done")
+
+awaitingResolution.upon(CxnTry.resolutionBegan).to(noNamesYet).returns(None)
+resolvingNames.upon(CxnTry.resolutionComplete).to(done).returns(None)
+resolvingNames.upon(CxnTry.addressResolved).to(resolvingNames)(addressResolved)
+resolvingWithPending.upon(CxnTry.noPendingConnections).to(resolvingNames).returns(None)
+justPending.upon(CxnTry.noPendingConnections).to(done).returns(None)
+# FIXME
+#     outputs=[connectionFailure],
+justPending.upon(CxnTry.userCancellation).to(done).returns(None)
+# FIXME
+# outputs=[cancelOtherPending0, connectionFailure],
+justPending.upon(CxnTry.established).to(done)
+# FIXME
+#     outputs=[cancelOtherPending1, complete],
+justQueued.upon(CxnTry.moreQueuedEndpoints).to(
+    pendingAndQueued,
+    # FIXME
+    # outputs=[oneAttemptLater0],
+)
+justQueued.upon(CxnTry.noPendingConnections).to(justQueued)
+# FIXME
+# outputs=[doOneAttempt0]
+justQueued.upon(CxnTry.endpointQueueEmpty).to(justPending).returns(None)
+resolvingWithPendingAndQueued.upon(CxnTry.endpointQueueEmpty).to(
+    resolvingWithPending
+).returns(None)
+resolvingWithPendingAndQueued.upon(CxnTry.resolutionComplete).to(
+    pendingAndQueued
+).returns(None)
+resolvingWithPendingAndQueued.upon(CxnTry.noPendingConnections).to(
+    resolvingWithPendingAndQueued
+).returns(None)
+pendingAndQueued.upon(CxnTry.moreQueuedEndpoints).to(pendingAndQueued).returns(None)
+# this one's a bit weird; the queued connection will inevitably _become_ a
+# pending connection, so pendingAndQueued is still an appropriate state despite
+# the lack of anything presently pending
+pendingAndQueued.upon(CxnTry.noPendingConnections).to(justQueued)
+# FIXME
+# outputs=[cancelTimer0, doOneAttempt0],
+done.upon(CxnTry.noPendingConnections).to(done).returns(None)
+noNamesYet.upon(CxnTry.addressResolved).to(resolvingWithPending)(
+    lambda attempt, core, resolution, address: addressResolved(attempt, core, address)
+)
+resolvingWithPending.upon(CxnTry.addressResolved).to(resolvingWithPendingAndQueued)(
+    addressResolved
+)
+
```

</div>
<div>

```diff
+
+@idle.upon(CxnTry.start).to(awaitingResolution)
+def doStart(attempt: CxnTry, core: AttemptState) -> D[IProtocol]:
+    core.endpoint._getNameResolverAndMaybeWarn(core.endpoint._reactor).resolveHostName(
+        attempt,
+        core.endpoint._hostText,
+        portNumber=core.endpoint._port,
+    )
+    core.deferred = D(attempt.userCancellation)
+    return core.deferred
+
+
+@noNamesYet.upon(CxnTry.resolutionComplete).to(done)
+def completed(attempt: CxnTry, core: AttemptState, res: IHostResolution) -> None:
+    e = DNSLookupError(f"no results for hostname lookup: {core.endpoint._hostText}")
+    core.deferred.errback(e)
+
+
+@noNamesYet.upon(CxnTry.userCancellation).to(done)
+def cancel(
+    attempt: CxnTry, core: AttemptState, res: IHostResolution, deferred: D[IProtocol]
+) -> None:
+    res.cancel()
+
+
+CxnTryImpl = build.build()
+
+
+def start(endpoint: HostnameEndpoint, pf: IProtocolFactory) -> D[IProtocol]:
+    state = AttemptState(D(), endpoint, pf)
+    return CxnTryImpl(state).start()
diff --git a/src/twisted/internet/_statefulhost3.py b/src/twisted/internet/_statefulhost3.py
new file mode 100644
index 000000000..07c3a75d1
--- /dev/null
+++ b/src/twisted/internet/_statefulhost3.py
@@ -0,0 +1,252 @@
+# -*- test-case-name: twisted.internet.test.test_endpoints -*-
+from __future__ import annotations
+
+from dataclasses import dataclass, field
+from enum import Enum, auto
+from typing import TYPE_CHECKING, Callable, TypeVar
+
+from zope.interface import implementer
+
+from twisted.internet.address import HostnameAddress, IPv4Address, IPv6Address
+from twisted.internet.defer import Deferred
+from twisted.internet.error import ConnectingCancelledError, DNSLookupError
+from twisted.internet.interfaces import (
+    IAddress,
+    IDelayedCall,
+    IHostResolution,
+    IProtocol,
+    IProtocolFactory,
+    IReactorTime,
+    IResolutionReceiver,
+    IStreamClientEndpoint,
+)
+from twisted.internet.protocol import Protocol as TwistedProtocol
+from twisted.python.failure import Failure
+from ._shutil import CallWhenAll, Outstanding
+
+if TYPE_CHECKING:
+    from twisted.internet.endpoints import HostnameEndpoint
+
+
+T = TypeVar("T")
+
+
+class ConnectionFailedParts(Enum):
+    ResolutionCompleted = auto()
+    NoResolvedNamesToAttempt = auto()
+    AllConnectionsFailed = auto()
+    NotCancelled = auto()
+    NotEstablished = auto()
+
+
+@implementer(IResolutionReceiver)
+@dataclass
+class Resolution:
+    allCall: CallWhenAll[ConnectionFailedParts]
+    enq: Callable[[IAddress], None]
+    inProgress: IHostResolution | None = None
+
+    def resolutionBegan(self, resolutionInProgress: IHostResolution) -> None:
+        """
+        Name resolution has started.
+        """
+        self.inProgress = resolutionInProgress
+
+    def addressResolved(self, address: IAddress) -> None:
+        """
+        An address was resolved.
+        """
+        self.enq(address)
+
+    def resolutionComplete(self) -> None:
+        """
+        Name resolution is complete, no further names will be resolved.
+        """
+        self.inProgress = None
+        self.allCall.add(ConnectionFailedParts.ResolutionCompleted)
+
+    def cancel(self) -> None:
+        if self.inProgress is not None:
+            self.inProgress.cancel()
+
+
+def addr2endpoint(
+    hostnameEndpoint: HostnameEndpoint,
+    address: IAddress,
+) -> IStreamClientEndpoint | None:
+    """
+    Convert an address into an endpoint
+    """
+    # Circular imports.
+    from twisted.internet.endpoints import TCP4ClientEndpoint, TCP6ClientEndpoint
+
+    reactor = hostnameEndpoint._reactor
+    timeout = hostnameEndpoint._timeout
+    bindAddress = hostnameEndpoint._bindAddress
+
+    if isinstance(address, IPv6Address):
+        return TCP6ClientEndpoint(
+            reactor, address.host, address.port, timeout, bindAddress
+        )
+    if isinstance(address, IPv4Address):
+        return TCP4ClientEndpoint(
+            reactor, address.host, address.port, timeout, bindAddress
+        )
+    return None
+
+
+@dataclass
+class Attempts:
+    """
+    Object managing outgoing connection attempts.
+    """
+
+    protocolFactory: IProtocolFactory
+    failer: CallWhenAll[ConnectionFailedParts]
+    clock: IReactorTime
+    attemptDelay: float
+    established: Callable[[TwistedProtocol], None]
+    lastAttemptTime: float | None = None
+    delayedCall: IDelayedCall | None = None
+    attemptsInProgress: Outstanding[IProtocol] = field(default_factory=Outstanding)
+    endpointQueue: list[IStreamClientEndpoint] = field(default_factory=list)
+    failures: list[Failure] = field(default_factory=list)
+
+    def invariants(self) -> None:
+        C = ConnectionFailedParts
+        self.failer.check(
+            [
+                (self.attemptsInProgress.empty(), C.AllConnectionsFailed),
+                (not self.endpointQueue, C.NoResolvedNamesToAttempt),
+            ]
+        )
+
+    def cancel(self) -> None:
+        self.endpointQueue[:] = []
+        self.invariants()
+        self.attemptsInProgress.cancel()
+        if self.delayedCall is not None:
+            self.delayedCall.cancel()
+
+    def attempt(self, endpoint: IStreamClientEndpoint) -> None:
+        self.endpointQueue.append(endpoint)
+        self.invariants()
+        self.scheduleQueueDrain()
+
+    def scheduleQueueDrain(self) -> None:
+        if self.delayedCall is not None:
+            # There is already a queue drain in progress; it'll keep going, so
+            # never mind.
+            return
+
+        def drainQueue() -> None:
+            self.delayedCall = None
+            self.lastAttemptTime = self.clock.seconds()
+            endpoint = self.endpointQueue.pop(0)
+            if self.endpointQueue:
+                self.scheduleQueueDrain()
+
+            def maybeNoMoreConnections(result: T) -> T:
+                self.invariants()
+                if self.attemptsInProgress.empty() and self.endpointQueue:
+                    if self.delayedCall is not None:
+                        self.delayedCall.cancel()
+                    drainQueue()
+                return result
+
+            a = self.attemptsInProgress.add(endpoint.connect(self.protocolFactory))
+            self.invariants()
+            a.addCallbacks(self.established, self.failures.append)
+            a.addBoth(maybeNoMoreConnections)
+
+        lastAttemptTime = self.lastAttemptTime
+        now = self.clock.seconds()
+        desiredDelay = (
+            -1
+            if lastAttemptTime is None
+            else self.attemptDelay - (now - lastAttemptTime)
+        )
+        if desiredDelay <= 0:
+            assert self.delayedCall is None
+            drainQueue()
+        else:
+            assert self.delayedCall is None
+            self.delayedCall = self.clock.callLater(
+                desiredDelay,
+                drainQueue,
+            )
+
+
+def start(
+    hostnameEndpoint: HostnameEndpoint,
+    protocolFactory: IProtocolFactory,
+) -> Deferred[TwistedProtocol]:
+    """
+    do it
+    """
+    d: Deferred[TwistedProtocol]
+    resolution: Resolution
+
+    def determineFailure() -> Failure | Exception:
+        if attempts.failures:
+            return attempts.failures[0]
+        else:
+            return DNSLookupError(
+                f"no results for hostname lookup: {hostnameEndpoint._hostText}"
+            )
+
+    failer: CallWhenAll[ConnectionFailedParts] = CallWhenAll(
+        lambda: d.errback(determineFailure()),
+        frozenset(ConnectionFailedParts),
+    )
+
+    def cleanup() -> None:
+        resolution.cancel()
+        attempts.cancel()
+
+    def cancel(d2: Deferred[TwistedProtocol]) -> None:
+        failer.remove(ConnectionFailedParts.NotCancelled)
+        cleanup()
+        d.errback(
+            ConnectingCancelledError(
+                HostnameAddress(hostnameEndpoint._hostBytes, hostnameEndpoint._port)
+            )
+        )
+
+    def established(result: TwistedProtocol) -> None:
+        failer.remove(ConnectionFailedParts.NotCancelled)
+        cleanup()
+        d.callback(result)
+
+    d = Deferred(cancel)
+
+    failer.add(ConnectionFailedParts.NotCancelled)
+    failer.add(ConnectionFailedParts.NotEstablished)
+    # there are no un-failed connections, so at this point all connections have
+    # failed, we'll clean it up
+    failer.add(ConnectionFailedParts.AllConnectionsFailed)
+    failer.add(ConnectionFailedParts.NoResolvedNamesToAttempt)
+
+    attempts = Attempts(
+        protocolFactory,
+        failer,
+        hostnameEndpoint._reactor,
+        hostnameEndpoint._attemptDelay,
+        established,
+    )
+
+    def enq(address: IAddress) -> None:
+        newEndpoint = addr2endpoint(hostnameEndpoint, address)
+        if newEndpoint is None:
+            return
+        attempts.attempt(newEndpoint)
+
+    resolution = Resolution(failer, enq)
+
+    hostnameEndpoint._getNameResolverAndMaybeWarn(attempts.clock).resolveHostName(
+        resolution,
+        hostnameEndpoint._hostText,
+        portNumber=hostnameEndpoint._port,
+    )
+
+    return d
diff --git a/src/twisted/internet/_statefulhost4.py b/src/twisted/internet/_statefulhost4.py
new file mode 100644
index 000000000..0f002e860
--- /dev/null
+++ b/src/twisted/internet/_statefulhost4.py
@@ -0,0 +1,81 @@
+"""
+as each address is resolved:
+
+(convert it to an endpoint) if we are beneath the concurrent connection
+threshold: connect to it on connection: abort any other outgoing connections
+complete the deferred.  on error: remember the failure for later if resolution
+has completed and all outgoing connections are done: complete the deferred with
+a MultiFailure of remembered failures else: enqueue it
+
+name resolution states:
+
+    - not resolving yet
+
+    - receiving names
+
+    - done resolving
+
+        - when resolutionComplete triggers receivingNames->doneResolving - we
+          need to check whether the outgoing connection state is idle and fail
+          the deferred if so
+
+outgoing connection states:
+
+    - idle
+
+        - when connectionFailed input triggers someOutgoingConnections->idle -
+          we need to check whether the name resolver is done resolving and fail
+          the deferred if so
+
+    - some outgoing connections
+
+    - parallel limit reached
+
+combined state machine?
+
+- not resolving
+- resolving <-> resolving + connecting
+- failed <- connecting -> succeeded
+
+"""
+
+from dataclasses import dataclass
+from typing import Protocol
+
+from zope.interface import implementer
+
+from automat import TypeMachineBuilder
+
+from twisted.internet.interfaces import IAddress, IHostResolution, IResolutionReceiver
+
+
+@implementer(IResolutionReceiver)
+class RRProto(Protocol):
+    def resolutionBegan(self, resolutionInProgress: IHostResolution) -> None:
+        ...
+
+    def addressResolved(self, address: IAddress) -> None:
+        ...
+
+    def resolutionComplete(self) -> None:
+        ...
+
+
+@dataclass
+class ResoState:
+    ...
+
+
+resolutionBuilder = TypeMachineBuilder(RRProto, ResoState)
+
+
+class CxnEvents(Protocol):
+    ...
+
+
+@dataclass
+class CxnState:
+    ...
+
+
+cxnBuilder = TypeMachineBuilder(CxnEvents, CxnState)
```

</div>
</div>

<!-- The Glyph branch has been in progress since 2017. Multiple implementation attempts — _statefulhost.py, then _statefulhost2, 3, 4, then a coroutine-based _corohost.py. The last commit message was "my eyes are starting to water looking at this". This is 1,542 lines of additions across 6 new files. Compare that to AnyIO's 5 lines. -->
