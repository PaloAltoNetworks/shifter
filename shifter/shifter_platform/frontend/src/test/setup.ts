import "@testing-library/jest-dom/vitest";

// jsdom does not implement ResizeObserver, which the terminal panes use to
// refit xterm when their container changes size (#1661) and which
// react-resizable-panels reads off the document's default view. Register a
// minimal observable stub so component tests can drive container-resize
// behavior deterministically instead of silently skipping it.
type ResizeObserverCallback = (entries: unknown[], observer: ResizeObserverStub) => void;

class ResizeObserverStub {
  // Mutable contents, immutable binding: tests clear it in place
  // (`instances.length = 0`) rather than reassigning the array.
  static readonly instances: ResizeObserverStub[] = [];

  readonly callback: ResizeObserverCallback;
  readonly observed = new Set<Element>();

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
    ResizeObserverStub.instances.push(this);
  }

  observe(target: Element): void {
    this.observed.add(target);
  }

  unobserve(target: Element): void {
    this.observed.delete(target);
  }

  disconnect(): void {
    this.observed.clear();
  }

  /** Test seam: fire the callback as though the observed element resized. */
  trigger(): void {
    this.callback([], this);
  }
}

Object.defineProperty(globalThis, "ResizeObserver", {
  writable: true,
  configurable: true,
  value: ResizeObserverStub,
});

// jsdom does not implement the Pointer Capture API or scrollIntoView, which
// Radix UI primitives (Select, Dialog, etc.) call from their pointer handlers.
// Register no-op stubs so component tests can drive those primitives instead of
// crashing with "hasPointerCapture is not a function" (#1938).
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = () => {};
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = () => {};
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

export { ResizeObserverStub };
