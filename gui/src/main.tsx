import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { initLogger, logger } from "./lib/logger";
// Geist Mono — bundled locally so the offline desktop app honors the font
// lock without a network fetch. 400 (body) + 500/600 (emphasis) weights.
import "@fontsource/geist-mono/400.css";
import "@fontsource/geist-mono/500.css";
import "@fontsource/geist-mono/600.css";
import "./index.css";

initLogger();
logger.info("app", "Mounting React root");

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
