import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { initialize, setHostedContext } from "./api";
import "./styles.css";
import "./refinement.css";
const root = createRoot(document.getElementById("root")!);
root.render(
  <div className="startup" role="status">
    Connecting to Harbor Review…
  </div>,
);
async function connect() {
  if (location.pathname === "/connect") {
    const token = location.hash.slice(1);
    history.replaceState(null, "", "/connect");
    const response = await fetch("/api/session/exchange", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) });
    if (!response.ok) throw new Error("Dashboard link expired or already used. Request a new link in Telegram.");
    const { path } = await response.json();
    history.replaceState(null, "", path);
  }
  const config = await initialize();
  setHostedContext(!!config?.hosted, !!config?.sample);
  return config;
}
connect()
  .then((config) =>
    root.render(
      <React.StrictMode>
        <App
          initialFault={config?.fault ?? "none"}
          initialDecisionFault={config?.decision_fault ?? "none"}
          sharedTelegramDemo={config?.milestone === "F2"}
          hosted={config?.hosted}
          telegramUrl={config?.telegram_url}
          sample={config?.sample}
          datasetSize={config?.dataset_size}
        />
      </React.StrictMode>,
    ),
  )
  .catch((error: Error) =>
    root.render(
      <main className="startup">
        <h1>Unable to connect</h1>
        <p>
          {error.message || "The API could not initialize. Please try again."}
        </p>
        <button onClick={() => location.reload()}>Retry connection</button>
      </main>,
    ),
  );
