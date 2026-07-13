import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";

// Code-split each route. A visitor landing on "/" should not have to download
// the WebGL bundle (ogl, used only on /upload) or the markdown renderer
// (react-markdown, used only on /chat) — lazy() puts each page in its own chunk
// that loads on demand. The body's dark background shows during the brief load,
// so the null fallback never causes a white flash.
const Index = lazy(() => import("./pages/Index"));
const Upload = lazy(() => import("./pages/Upload"));
const Chat = lazy(() => import("./pages/Chat"));

/**
 * App — top-level router.
 *
 *   /         the dark "Turing Tree" hero landing page
 *   /upload   the security-focused drag-a-folder ingestion screen
 *   /chat     the neutral-corporate AI chat screen
 */
export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={null}>
        <Routes>
          <Route path="/" element={<Index />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/chat" element={<Chat />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
