import '@testing-library/jest-dom/vitest';

// jsdom exposes scrollTo but reports every call as an unimplemented browser API.
Object.defineProperty(window, 'scrollTo', {
  configurable: true,
  value: () => {},
  writable: true,
});

// jsdom does not implement matchMedia; ThemeProvider relies on it.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}
