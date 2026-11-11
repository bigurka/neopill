// Robust custom element registration for scripts loaded via add_extra_js_url.
//
// Home Assistant's index page imports these extra modules *before* its own frontend
// bundle runs, and that bundle can then replace window.customElements with a
// scoped-registry implementation. An element defined a moment earlier on the old
// registry becomes invisible to the dashboard, which then fails with "Timeout
// waiting for strategy element ... to be registered" - intermittently, depending on
// which script finishes loading first. So: define now, and for the first seconds of
// the page keep checking the *current* registry, defining the element again there
// (as a fresh subclass, since a constructor can't be registered twice) if it's
// missing.
const WATCH_MS = 20000;
const POLL_MS = 50;

export function defineElement(tag, cls) {
  const ensure = (ctor) => {
    if (window.customElements.get(tag)) return;
    try {
      window.customElements.define(tag, ctor);
    } catch (err) {
      // Defined in the meantime by another copy of this script: nothing to do.
      if (!window.customElements.get(tag)) throw err;
    }
  };
  ensure(cls);
  const started = Date.now();
  const timer = setInterval(() => {
    if (!window.customElements.get(tag)) ensure(class extends cls {});
    if (Date.now() - started > WATCH_MS) clearInterval(timer);
  }, POLL_MS);
}
