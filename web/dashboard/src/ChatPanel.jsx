import React, { useEffect, useMemo, useRef, useState } from "react";

function TextCard({ content }) {
  return <div className="chat-card text-card">{content || ""}</div>;
}

function InvoiceCard({ content }) {
  return (
    <div className="chat-card invoice-card">
      <h3>Invoice</h3>
      <pre>{content || ""}</pre>
    </div>
  );
}

function ReportCard({ content }) {
  return (
    <div className="chat-card report-card">
      <h3>Report</h3>
      <pre>{content || ""}</pre>
    </div>
  );
}

function ComparisonTable({ content }) {
  return (
    <div className="chat-card comparison-card">
      <h3>Comparison</h3>
      <pre>{content || ""}</pre>
    </div>
  );
}

function TimelineCard({ content }) {
  return (
    <div className="chat-card timeline-card">
      <h3>Plan</h3>
      <pre>{content || ""}</pre>
    </div>
  );
}

function createCard(type, content) {
  const contentType = String(type || "default").toLowerCase();
  if (contentType === "invoice") {
    return <InvoiceCard content={content} />;
  }
  if (contentType === "report") {
    return <ReportCard content={content} />;
  }
  if (contentType === "comparison") {
    return <ComparisonTable content={content} />;
  }
  if (contentType === "plan") {
    return <TimelineCard content={content} />;
  }
  return <TextCard content={content} />;
}

function nextWordChunk(current, incoming) {
  if (!current) {
    return incoming;
  }
  return `${current} ${incoming}`.trim();
}

export default function ChatPanel({ sessionId, token, wsBase = "" }) {
  const [autonomy, setAutonomy] = useState(50);
  const [inputValue, setInputValue] = useState("");
  const [cards, setCards] = useState([]);
  const [activeCard, setActiveCard] = useState(null);
  const [sessionRestored, setSessionRestored] = useState(false);
  const wsRef = useRef(null);

  const wsUrl = useMemo(() => {
    const origin = wsBase || window.location.origin.replace(/^http/, "ws");
    return `${origin.replace(/\/$/, "")}/webchat/ws/${sessionId}?token=${encodeURIComponent(token)}`;
  }, [sessionId, token, wsBase]);

  useEffect(() => {
    let closed = false;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "session_resume", session_id: sessionId }));
    };
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "session_restored") {
          setSessionRestored(true);
          if (Array.isArray(payload.history) && payload.history.length > 0) {
            const historyCards = payload.history.map((item, idx) => ({
              id: `history-${idx}-${Date.now()}`,
              contentType: item.content_type || "default",
              content: item.content || "",
            }));
            setCards(historyCards);
          }
          return;
        }
        if (payload.type === "done") {
          setActiveCard({
            id: `card-${Date.now()}`,
            contentType: payload.content_type || "default",
            content: "",
          });
          return;
        }
        if (payload.type === "token") {
          const chunk = String(payload.token || "").trim();
          if (!chunk) {
            return;
          }
          setActiveCard((prev) => {
            if (!prev) {
              return {
                id: `card-${Date.now()}`,
                contentType: "default",
                content: chunk,
              };
            }
            return { ...prev, content: nextWordChunk(prev.content, chunk) };
          });
          return;
        }
        if (payload.type === "complete") {
          setCards((prev) => (activeCard ? [...prev, activeCard] : prev));
          setActiveCard(null);
        }
      } catch (_err) {
        return;
      }
    };
    ws.onclose = () => {
      if (!closed) {
        setSessionRestored(true);
      }
    };
    return () => {
      closed = true;
      ws.close();
    };
  }, [wsUrl, sessionId, activeCard]);

  const onSubmit = (event) => {
    event.preventDefault();
    const content = inputValue.trim();
    if (!content || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      return;
    }
    wsRef.current.send(
      JSON.stringify({
        type: "user_message",
        session_id: sessionId,
        autonomy,
        content,
      }),
    );
    setInputValue("");
  };

  const onVoiceInput = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      return;
    }
    const recognition = new SR();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onresult = (event) => {
      const transcript = event.results?.[0]?.[0]?.transcript || "";
      setInputValue((prev) => `${prev} ${transcript}`.trim());
    };
    recognition.start();
  };

  return (
    <div className="chat-panel-root">
      {sessionRestored ? (
        <div className="restore-banner">Session restored from previous history.</div>
      ) : null}
      <div className="chat-feed">
        {cards.map((card) => (
          <div className="chat-card-wrap" key={card.id}>
            {createCard(card.contentType, card.content)}
          </div>
        ))}
        {activeCard ? <div className="chat-card-wrap">{createCard(activeCard.contentType, activeCard.content)}</div> : null}
      </div>
      <div className="chat-controls">
        <label htmlFor="autonomy-slider">Autonomy: {autonomy}</label>
        <input
          id="autonomy-slider"
          type="range"
          min="0"
          max="100"
          value={autonomy}
          onChange={(event) => setAutonomy(Number(event.target.value))}
        />
      </div>
      <form className="chat-input-row" onSubmit={onSubmit}>
        <button type="button" className="voice-btn" onClick={onVoiceInput} aria-label="Voice input">
          Mic
        </button>
        <input
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
          placeholder="Ask ARCHON anything..."
        />
        <button type="submit">Send</button>
      </form>
    </div>
  );
}

