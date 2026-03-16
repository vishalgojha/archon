(function () {
  const React = window.React;
  const ReactDOM = window.ReactDOM;
  if (!React || !ReactDOM) {
    console.error("ARCHON pack requires React + ReactDOM.");
    return;
  }

  const { createElement: h, useMemo } = React;

  function DrawerCard({ drawer }) {
    const items = Array.isArray(drawer.items) ? drawer.items : [];
    const hasItems = items.length > 0;
    return h(
      "div",
      { className: "archon-pack-card" },
      h("h3", null, drawer.title || "Drawer"),
      drawer.description ? h("p", null, drawer.description) : null,
      h(
        "div",
        { className: "archon-pack-pill" },
        String(drawer.type || "list").toUpperCase()
      ),
      h(
        "div",
        { className: "archon-pack-items" },
        hasItems
          ? items.map((item, idx) =>
              h(
                "div",
                { className: "archon-pack-item", key: idx },
                typeof item === "string" ? item : JSON.stringify(item)
              )
            )
          : h(
              "div",
              { className: "archon-pack-item" },
              "Awaiting live data from your tools."
            )
      )
    );
  }

  function PackApp({ pack }) {
    const manifest = pack && pack.manifest ? pack.manifest : {};
    const drawers = Array.isArray(manifest.drawers) ? manifest.drawers : [];
    const title = manifest.title || "Custom Workspace";
    const summary = manifest.summary || "Self-evolving operator console.";

    const gridStyle = useMemo(
      () => ({
        gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
      }),
      []
    );

    return h(
      "div",
      { className: "archon-pack-root" },
      h("h2", null, title),
      h("p", null, summary),
      h(
        "div",
        { className: "archon-pack-grid", style: gridStyle },
        drawers.map((drawer) =>
          h(DrawerCard, { key: drawer.id || drawer.title, drawer })
        )
      )
    );
  }

  function mount({ root, bridge, pack }) {
    if (!root) {
      throw new Error("Pack mount requires a root element.");
    }
    const cssId = "archon-pack-style";
    if (!document.getElementById(cssId)) {
      const link = document.createElement("link");
      link.id = cssId;
      link.rel = "stylesheet";
      link.href = bridge.assetUrl("styles.css");
      document.head.appendChild(link);
    }

    const container = document.createElement("div");
    root.innerHTML = "";
    root.appendChild(container);
    const reactRoot = ReactDOM.createRoot(container);
    reactRoot.render(h(PackApp, { pack, bridge }));
    return () => reactRoot.unmount();
  }

  window.ARCHON_PACK = { mount };
})();