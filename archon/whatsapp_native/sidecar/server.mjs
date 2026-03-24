import { mkdirSync } from "node:fs";
import { createServer } from "node:http";
import { resolve } from "node:path";

import {
  DisconnectReason,
  fetchLatestBaileysVersion,
  makeWASocket,
  useMultiFileAuthState,
} from "@whiskeysockets/baileys";
import pino from "pino";

const host = process.env.ARCHON_BAILEYS_HOST || "127.0.0.1";
const port = Number(process.env.ARCHON_BAILEYS_PORT || "3210");
const sessionDir = resolve(
  process.env.ARCHON_BAILEYS_SESSION_DIR || resolve(process.cwd(), ".session"),
);
const logger = pino({ level: process.env.ARCHON_BAILEYS_LOG_LEVEL || "info" });

mkdirSync(sessionDir, { recursive: true });

let sock = null;
let latestQr = null;
let connectionState = "starting";
let lastError = null;
let identity = null;
const inbox = [];
const maxInboxItems = 200;

function sendJson(res, statusCode, payload) {
  res.writeHead(statusCode, { "Content-Type": "application/json" });
  res.end(JSON.stringify(payload));
}

function normalizeChatId(value) {
  const chatId = String(value || "").trim();
  if (!chatId) {
    return "";
  }
  if (chatId.includes("@")) {
    return chatId;
  }
  const digits = chatId.replace(/\D/g, "");
  if (digits) {
    return `${digits}@s.whatsapp.net`;
  }
  return chatId;
}

function extractText(message) {
  if (!message || typeof message !== "object") {
    return "";
  }
  if (typeof message.conversation === "string") {
    return message.conversation;
  }
  if (typeof message.extendedTextMessage?.text === "string") {
    return message.extendedTextMessage.text;
  }
  if (typeof message.imageMessage?.caption === "string") {
    return message.imageMessage.caption;
  }
  if (typeof message.videoMessage?.caption === "string") {
    return message.videoMessage.caption;
  }
  return "";
}

function parseBody(req) {
  return new Promise((resolveBody, rejectBody) => {
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk;
    });
    req.on("end", () => {
      if (!raw.trim()) {
        resolveBody({});
        return;
      }
      try {
        resolveBody(JSON.parse(raw));
      } catch (error) {
        rejectBody(error);
      }
    });
    req.on("error", rejectBody);
  });
}

async function connectSocket() {
  connectionState = "connecting";
  const { state, saveCreds } = await useMultiFileAuthState(sessionDir);
  let version;
  try {
    const latest = await fetchLatestBaileysVersion();
    version = latest.version;
  } catch (error) {
    logger.warn({ error }, "failed to fetch latest Baileys version");
  }

  sock = makeWASocket({
    auth: state,
    logger,
    printQRInTerminal: false,
    version,
  });

  sock.ev.on("creds.update", saveCreds);
  sock.ev.on("messages.upsert", (event) => {
    const messages = Array.isArray(event?.messages) ? event.messages : [];
    for (const item of messages) {
      if (!item || item.key?.fromMe) {
        continue;
      }
      const text = extractText(item.message);
      if (!text) {
        continue;
      }
      inbox.unshift({
        message_id: item.key?.id || null,
        chat_id: item.key?.remoteJid || null,
        sender_id: item.key?.participant || item.key?.remoteJid || null,
        text,
        timestamp: item.messageTimestamp || null,
      });
    }
    if (inbox.length > maxInboxItems) {
      inbox.length = maxInboxItems;
    }
  });
  sock.ev.on("connection.update", async (update) => {
    if (update.qr) {
      latestQr = update.qr;
    }
    if (update.connection) {
      connectionState = update.connection;
    }
    if (update.isNewLogin && sock?.user) {
      identity = sock.user;
    }

    if (update.connection === "open") {
      latestQr = null;
      identity = sock?.user || identity;
      logger.info({ user: identity?.id }, "whatsapp connected");
      return;
    }

    if (update.connection === "close") {
      const disconnectCode =
        update.lastDisconnect?.error?.output?.statusCode ||
        update.lastDisconnect?.error?.statusCode ||
        null;
      lastError = update.lastDisconnect?.error?.message || "connection closed";
      logger.warn({ disconnectCode, lastError }, "whatsapp connection closed");
      const shouldReconnect = disconnectCode !== DisconnectReason.loggedOut;
      if (shouldReconnect) {
        setTimeout(() => {
          connectSocket().catch((error) => {
            lastError = error?.message || String(error);
            logger.error({ error }, "reconnect failed");
          });
        }, 1200);
      }
    }
  });
}

const server = createServer(async (req, res) => {
  try {
    const requestUrl = new URL(req.url || "/", `http://${host}:${port}`);

    if (req.method === "GET" && requestUrl.pathname === "/health") {
      sendJson(res, 200, {
        ok: true,
        state: connectionState,
        paired: Boolean(identity?.id),
      });
      return;
    }

    if (req.method === "GET" && requestUrl.pathname === "/session/status") {
      sendJson(res, 200, {
        ok: true,
        state: connectionState,
        paired: Boolean(identity?.id),
        user: identity,
        qr: latestQr,
        last_error: lastError,
      });
      return;
    }

    if (req.method === "GET" && requestUrl.pathname === "/messages/inbox") {
      const limit = Number(requestUrl.searchParams.get("limit") || "20");
      sendJson(res, 200, {
        ok: true,
        messages: inbox.slice(0, Math.max(1, limit)),
      });
      return;
    }

    if (req.method === "POST" && requestUrl.pathname === "/messages/ack") {
      let body;
      try {
        body = await parseBody(req);
      } catch (error) {
        sendJson(res, 400, { ok: false, error: "Invalid JSON body." });
        return;
      }
      const ids = Array.isArray(body.message_ids) ? body.message_ids.map(String) : [];
      const before = inbox.length;
      for (let index = inbox.length - 1; index >= 0; index -= 1) {
        if (ids.includes(String(inbox[index]?.message_id || ""))) {
          inbox.splice(index, 1);
        }
      }
      sendJson(res, 200, {
        ok: true,
        removed: before - inbox.length,
      });
      return;
    }

    if (req.method === "POST" && requestUrl.pathname === "/messages/send") {
      if (!sock || connectionState !== "open") {
        sendJson(res, 503, {
          ok: false,
          error: "WhatsApp session is not connected yet.",
          state: connectionState,
          qr: latestQr,
        });
        return;
      }

      let body;
      try {
        body = await parseBody(req);
      } catch (error) {
        sendJson(res, 400, { ok: false, error: "Invalid JSON body." });
        return;
      }

      const chatId = normalizeChatId(body.chat_id);
      const text = String(body.text || "").trim();
      if (!chatId || !text) {
        sendJson(res, 400, { ok: false, error: "chat_id and text are required." });
        return;
      }

      const sent = await sock.sendMessage(chatId, { text });
      sendJson(res, 200, {
        ok: true,
        state: connectionState,
        chat_id: chatId,
        message_id: sent?.key?.id || null,
      });
      return;
    }

    sendJson(res, 404, { ok: false, error: "Not found." });
  } catch (error) {
    logger.error({ error }, "sidecar request failed");
    sendJson(res, 500, { ok: false, error: error?.message || String(error) });
  }
});

await connectSocket();

server.listen(port, host, () => {
  logger.info({ host, port, sessionDir }, "archon whatsapp native sidecar listening");
});
