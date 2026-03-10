import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useARCHONMobileContext } from "./useARCHONMobile";
import { ComparisonTable } from "./ComparisonTable";
import { InvoiceCard } from "./InvoiceCard";
import { ReportCard } from "./ReportCard";
import { TimelineCard } from "./TimelineCard";

const TOKEN_KEY = "archon.mobile.token";
const SESSION_KEY = "archon.mobile.session_id";
const AUTONOMY_KEY = "archon.mobile.autonomy";

type ChatRole = "user" | "assistant" | "system";

type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  content_type?: string;
  payload?: Record<string, unknown>;
  approval?: Record<string, unknown>;
};

function resolveApiBase(): string {
  const base = (globalThis as any).ARCHON_API_BASE;
  if (typeof base === "string" && base.trim()) {
    return base.replace(/\/$/, "");
  }
  return "http://127.0.0.1:8000";
}

function parseMaybeJson(text: string): Record<string, unknown> | null {
  const trimmed = String(text || "").trim();
  if (!trimmed.startsWith("{") || !trimmed.endsWith("}")) {
    return null;
  }
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed && typeof parsed === "object") {
      return parsed as Record<string, unknown>;
    }
  } catch (_err) {
    return null;
  }
  return null;
}

function hydrateMessage(row: Record<string, unknown>, index: number): ChatMessage {
  const content = String(row.content || "");
  const metadata = row.metadata && typeof row.metadata === "object" ? (row.metadata as Record<string, unknown>) : {};
  const parsed = parseMaybeJson(content);
  const contentType = String(
    row.content_type || metadata.content_type || parsed?.content_type || "",
  ).toLowerCase();

  const payload =
    (parsed?.data && typeof parsed.data === "object" ? (parsed.data as Record<string, unknown>) : null) ||
    (parsed && typeof parsed === "object" ? parsed : null);

  return {
    id: String(row.id || `msg-${index}`),
    role: row.role === "assistant" ? "assistant" : row.role === "user" ? "user" : "system",
    content,
    content_type: contentType || undefined,
    payload: payload || undefined,
  };
}

function ThinkingDots() {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => setTick((value) => (value + 1) % 4), 420);
    return () => clearInterval(timer);
  }, []);

  return <Text style={styles.thinking}>ARCHON is thinking{".".repeat(tick)}</Text>;
}

export function ChatScreen() {
  const { lastEvent, send, agentStates } = useARCHONMobileContext();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const activeAssistantId = useRef<string>("");

  useEffect(() => {
    if (!lastEvent || typeof lastEvent !== "object") {
      return;
    }

    const type = String(lastEvent.type || "").toLowerCase();

    if (type === "session_restored") {
      const rows = Array.isArray(lastEvent.messages) ? (lastEvent.messages as Array<Record<string, unknown>>) : [];
      const hydrated = rows.slice(-20).map((row, index) => hydrateMessage(row, index));
      setMessages(hydrated);
      activeAssistantId.current = "";
      return;
    }

    if (type === "assistant_token") {
      const token = String(lastEvent.token || "");
      if (!token) {
        return;
      }

      setMessages((prev) => {
        const next = [...prev];
        if (!activeAssistantId.current) {
          activeAssistantId.current = `assistant-${Date.now()}`;
          next.push({ id: activeAssistantId.current, role: "assistant", content: token });
          return next;
        }

        const index = next.findIndex((row) => row.id === activeAssistantId.current);
        if (index < 0) {
          next.push({ id: activeAssistantId.current, role: "assistant", content: token });
        } else {
          next[index] = { ...next[index], content: `${next[index].content}${token}` };
        }
        return next;
      });
      return;
    }

    if (type === "done") {
      const message = lastEvent.message && typeof lastEvent.message === "object"
        ? (lastEvent.message as Record<string, unknown>)
        : null;
      const hydrated = hydrateMessage(message || {}, 0);

      setMessages((prev) => {
        const next = [...prev];
        if (!activeAssistantId.current) {
          next.push({ ...hydrated, id: hydrated.id || `assistant-${Date.now()}`, role: "assistant" });
          return next;
        }

        const index = next.findIndex((row) => row.id === activeAssistantId.current);
        if (index >= 0) {
          next[index] = {
            ...next[index],
            content: hydrated.content || next[index].content,
            content_type: hydrated.content_type,
            payload: hydrated.payload,
          };
        } else {
          next.push({ ...hydrated, id: activeAssistantId.current, role: "assistant" });
        }
        return next;
      });

      activeAssistantId.current = "";
      return;
    }

    if (type === "approval_required") {
      const requestId = String(lastEvent.request_id || lastEvent.action_id || "").trim();
      const actionName = String(lastEvent.action || lastEvent.action_type || "approval_required");
      setMessages((prev) => [
        ...prev,
        {
          id: `approval-${requestId || Date.now()}`,
          role: "system",
          content: `Approval required: ${actionName}`,
          approval: {
            ...lastEvent,
            request_id: requestId,
            action: actionName,
          },
        },
      ]);
      return;
    }

    if (type === "error") {
      const message = String(lastEvent.error || "Unknown error");
      setMessages((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: "system",
          content: message,
        },
      ]);
    }
  }, [lastEvent]);

  const onSend = useCallback(async () => {
    const content = String(input || "").trim();
    if (!content) {
      return;
    }

    const autonomyRaw = await AsyncStorage.getItem(AUTONOMY_KEY);
    const autonomy = Number.isFinite(Number(autonomyRaw)) ? Number(autonomyRaw) : 50;

    setMessages((prev) => [
      ...prev,
      {
        id: `user-${Date.now()}`,
        role: "user",
        content,
      },
    ]);

    setInput("");
    send({ type: "message", content, autonomy });
  }, [input, send]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const [[, token], [, sessionId]] = await AsyncStorage.multiGet([TOKEN_KEY, SESSION_KEY]);
      const authToken = String(token || "").trim();
      const sid = String(sessionId || "").trim();
      if (!authToken || !sid) {
        return;
      }

      const response = await fetch(
        `${resolveApiBase()}/webchat/session/${encodeURIComponent(sid)}?token=${encodeURIComponent(authToken)}`,
      );
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      const rows = Array.isArray(payload.messages) ? payload.messages : [];
      setMessages(rows.slice(-20).map((row: Record<string, unknown>, index: number) => hydrateMessage(row, index)));
      activeAssistantId.current = "";
    } finally {
      setRefreshing(false);
    }
  }, []);

  const isThinking = useMemo(
    () => Object.values(agentStates || {}).some((entry) => entry.status === "thinking"),
    [agentStates],
  );

  const renderRow = useCallback(
    ({ item }: { item: ChatMessage }) => {
      if (item.approval) {
        const requestId = String(item.approval.request_id || item.approval.action_id || "");
        const action = String(item.approval.action || item.approval.action_type || "action");
        return (
          <View style={styles.systemWrap}>
            <Text style={styles.systemText}>{item.content}</Text>
            <Text style={styles.approvalLabel}>{action}</Text>
            <View style={styles.approvalRow}>
              <Pressable
                style={[styles.approvalBtn, styles.approve]}
                onPress={() => send({ type: "approve", request_id: requestId })}
              >
                <Text style={styles.approvalBtnText}>Approve</Text>
              </Pressable>
              <Pressable
                style={[styles.approvalBtn, styles.deny]}
                onPress={() => send({ type: "deny", request_id: requestId })}
              >
                <Text style={styles.approvalBtnText}>Deny</Text>
              </Pressable>
            </View>
          </View>
        );
      }

      if (item.role === "assistant") {
        if (item.content_type === "invoice" && item.payload) {
          return <InvoiceCard data={item.payload as any} />;
        }
        if (item.content_type === "report" && item.payload) {
          return <ReportCard data={item.payload as any} />;
        }
        if (item.content_type === "comparison" && item.payload) {
          return <ComparisonTable data={item.payload as any} />;
        }
        if (item.content_type === "plan" && item.payload) {
          return <TimelineCard data={item.payload as any} />;
        }
        return (
          <View style={[styles.bubble, styles.assistantBubble]}>
            <Text style={styles.assistantText}>{item.content}</Text>
          </View>
        );
      }

      if (item.role === "user") {
        return (
          <View style={[styles.bubble, styles.userBubble]}>
            <Text style={styles.userText}>{item.content}</Text>
          </View>
        );
      }

      return (
        <View style={styles.systemWrap}>
          <Text style={styles.systemText}>{item.content}</Text>
        </View>
      );
    },
    [send],
  );

  return (
    <View style={styles.shell}>
      <FlatList
        data={messages}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.listContent}
        renderItem={renderRow}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => void onRefresh()} />}
      />

      {isThinking ? <ThinkingDots /> : null}

      <View style={styles.inputRow}>
        <TextInput
          value={input}
          onChangeText={setInput}
          onSubmitEditing={() => void onSend()}
          placeholder="Type a message"
          placeholderTextColor="#64748b"
          style={styles.input}
        />
        <Pressable style={styles.sendButton} onPress={() => void onSend()}>
          <Text style={styles.sendButtonText}>Send</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  shell: {
    flex: 1,
    backgroundColor: "#020617",
  },
  listContent: {
    padding: 12,
    gap: 8,
  },
  bubble: {
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 12,
    maxWidth: "92%",
  },
  userBubble: {
    marginLeft: "auto",
    backgroundColor: "#0e7490",
    borderTopRightRadius: 4,
  },
  assistantBubble: {
    marginRight: "auto",
    backgroundColor: "#0f172a",
    borderWidth: 1,
    borderColor: "#1e293b",
    borderTopLeftRadius: 4,
  },
  userText: {
    color: "#f0fdfa",
    fontSize: 14,
  },
  assistantText: {
    color: "#e2e8f0",
    fontSize: 14,
    lineHeight: 20,
  },
  systemWrap: {
    borderRadius: 12,
    backgroundColor: "#1f2937",
    borderColor: "#334155",
    borderWidth: 1,
    padding: 10,
  },
  systemText: {
    color: "#e5e7eb",
    fontSize: 12,
  },
  approvalLabel: {
    color: "#facc15",
    fontSize: 12,
    marginTop: 6,
  },
  approvalRow: {
    flexDirection: "row",
    gap: 8,
    marginTop: 8,
  },
  approvalBtn: {
    borderRadius: 9,
    paddingVertical: 7,
    paddingHorizontal: 14,
  },
  approve: {
    backgroundColor: "#166534",
  },
  deny: {
    backgroundColor: "#991b1b",
  },
  approvalBtnText: {
    color: "#f8fafc",
    fontWeight: "700",
    fontSize: 12,
  },
  thinking: {
    color: "#94a3b8",
    fontSize: 12,
    marginHorizontal: 14,
    marginBottom: 8,
  },
  inputRow: {
    flexDirection: "row",
    gap: 8,
    borderTopWidth: 1,
    borderTopColor: "#1e293b",
    paddingHorizontal: 12,
    paddingVertical: 10,
    backgroundColor: "#020617",
  },
  input: {
    flex: 1,
    height: 44,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#334155",
    backgroundColor: "#0f172a",
    color: "#f8fafc",
    paddingHorizontal: 12,
  },
  sendButton: {
    borderRadius: 12,
    backgroundColor: "#0891b2",
    justifyContent: "center",
    paddingHorizontal: 14,
  },
  sendButtonText: {
    color: "#ecfeff",
    fontWeight: "700",
  },
});

export default ChatScreen;
