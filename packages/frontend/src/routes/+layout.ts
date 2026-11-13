// When building for Tauri (VITE_TAURI=true), disable SSR globally.
// The web build (default) keeps SSR enabled via adapter-node.
export const ssr = import.meta.env.VITE_TAURI !== 'true';
