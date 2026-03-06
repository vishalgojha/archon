(() => {
  const { useMemo, useState } = React;

  function buildPreviewHtml(scriptTag) {
    return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      body { margin: 0; font-family: sans-serif; background: #f8fafc; }
      .container { padding: 16px; }
      h4 { margin: 0 0 8px 0; color: #0f172a; }
      p { margin: 0; color: #334155; }
    </style>
  </head>
  <body>
    <div class="container">
      <h4>ARCHON Widget Preview</h4>
      <p>Widget script injected below.</p>
    </div>
    ${scriptTag}
  </body>
</html>`;
  }

  function EmbedGenerator() {
    const [url, setUrl] = useState("");
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState("");
    const [copied, setCopied] = useState(false);

    const previewHtml = useMemo(() => {
      if (!result?.embed?.script_tag) {
        return "";
      }
      return buildPreviewHtml(result.embed.script_tag);
    }, [result]);

    const onGenerate = async () => {
      setLoading(true);
      setError("");
      setCopied(false);
      setResult(null);
      try {
        const response = await window.consoleApiFetch("/console/crawl", {
          method: "POST",
          body: JSON.stringify({ url }),
        });
        const payload = await response.json();
        setResult(payload);
      } catch (crawlError) {
        setError(String(crawlError.message || crawlError));
      } finally {
        setLoading(false);
      }
    };

    const onCopy = async () => {
      if (!result?.embed?.script_tag) {
        return;
      }
      try {
        await navigator.clipboard.writeText(result.embed.script_tag);
        setCopied(true);
      } catch (_error) {
        setCopied(false);
      }
    };

    return (
      <div className="console-pane embed-pane">
        <h2>Embed Generator</h2>
        <div className="provider-row">
          <input
            placeholder="https://example.com"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
          />
          <button type="button" onClick={onGenerate} disabled={loading || !url.trim()}>
            {loading ? "Crawling..." : "Generate"}
          </button>
        </div>

        {result ? (
          <div className="embed-result">
            <div className="embed-intent">
              <strong>Detected intent:</strong> {result.site_intent?.primary || "unknown"}
              <span className="muted"> confidence {Math.round((result.site_intent?.confidence || 0) * 100)}%</span>
            </div>

            <label>
              Script tag
              <textarea value={result.embed?.script_tag || ""} readOnly rows={4} />
            </label>
            <button type="button" onClick={onCopy}>
              {copied ? "Copied" : "Copy to clipboard"}
            </button>

            <div className="iframe-preview">
              <iframe
                title="ARCHON widget preview"
                sandbox="allow-scripts allow-same-origin"
                srcDoc={previewHtml}
              />
            </div>
          </div>
        ) : null}

        {error ? <div className="inline-error">{error}</div> : null}
      </div>
    );
  }

  window.EmbedGenerator = EmbedGenerator;
})();
