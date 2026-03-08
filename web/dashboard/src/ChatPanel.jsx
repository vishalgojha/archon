import React, { useRef, useState } from "react";

import { useArchonStream } from "./archonStream";

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

export default function ChatPanel({
  sessionId = "",
  token = "",
  apiBase = "",
  wsBase = "",
  transport = "webchat",
  stream,
}) {
  const [autonomy, setAutonomy] = useState(50);
  const [inputValue, setInputValue] = useState("");
  const inputRef = useRef(null);
  const liveStream =
    stream ||
    useArchonStream({
      sessionId,
      token,
      apiBase,
      wsBase,
      transport,
    });
  const cards = liveStream.messages;
  const activeCard = liveStream.activeMessage;
  const sessionRestored = liveStream.sessionRestored;
  const effectiveSessionId = liveStream.sessionId;
  const connectionStatus = liveStream.status;

  const onSubmit = (event) => {
    event.preventDefault();
    const content = inputValue.trim();
    if (!content) {
      return;
    }
    liveStream.send({
      type: "message",
      session_id: effectiveSessionId,
      autonomy,
      content,
    });
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
      setInputValue((prev) => nextWordChunk(prev, transcript));
      inputRef.current?.focus();
    };
    recognition.start();
  };

  return (
    <div className="chat-panel-root">
      <div className="chat-status-banner">WebSocket: {connectionStatus}</div>
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
          ref={inputRef}
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
          placeholder="Ask ARCHON anything..."
        />
        <button type="submit">Send</button>
      </form>
    </div>
  );
}
