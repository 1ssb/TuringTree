/// <reference types="vite/client" />

// Augment Vite's env typing with our custom variables (see frontend/.env.example).
interface ImportMetaEnv {
  /**
   * Optional backend base URL, e.g. "https://api.example.com". Empty (default)
   * uses same-origin "/api/..." paths (proxied to FastAPI on :8000 in dev).
   */
  readonly VITE_API_BASE_URL?: string;
}
