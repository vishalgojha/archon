import React, { useCallback, useEffect, useMemo, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { NavigationContainer, DarkTheme } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { ARCHONProvider } from "./useARCHONMobile";
import { ChatScreen } from "./ChatScreen";
import { HistoryScreen } from "./HistoryScreen";
import { HomeScreen } from "./HomeScreen";
import { SettingsScreen } from "./SettingsScreen";

const TOKEN_KEY = "archon.mobile.token";
const SESSION_KEY = "archon.mobile.session_id";

type RootStackParamList = {
  Home: undefined;
  MainTabs: undefined;
  TokenGate: undefined;
};

const Stack = createNativeStackNavigator<RootStackParamList>();
const Tabs = createBottomTabNavigator();

function resolveApiBase(): string {
  const base = (globalThis as any).ARCHON_API_BASE;
  if (typeof base === "string" && base.trim()) {
    return base.replace(/\/$/, "");
  }
  return "http://127.0.0.1:8000";
}

async function fetchAnonymousToken(): Promise<{ token: string; session_id: string }> {
  const response = await fetch(`${resolveApiBase()}/webchat/token`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}",
  });
  if (!response.ok) {
    throw new Error(`Token fetch failed (${response.status})`);
  }
  const payload = await response.json();
  const token = String(payload.token || "").trim();
  const sessionId = String(payload.session?.session_id || payload.identity?.session_id || "").trim();
  if (!token || !sessionId) {
    throw new Error("Token response missing token/session_id");
  }
  return { token, session_id: sessionId };
}

function MainTabs() {
  return (
    <Tabs.Navigator
      screenOptions={{
        headerShown: false,
        tabBarStyle: {
          backgroundColor: "#020617",
          borderTopColor: "#1e293b",
        },
        tabBarActiveTintColor: "#67e8f9",
        tabBarInactiveTintColor: "#64748b",
      }}
    >
      <Tabs.Screen name="Chat" component={ChatScreen} />
      <Tabs.Screen name="History" component={HistoryScreen} />
      <Tabs.Screen name="Settings" component={SettingsScreen} />
    </Tabs.Navigator>
  );
}

function TokenGate({ onReady }: { onReady: () => void }) {
  const [token, setToken] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const saveManual = useCallback(async () => {
    const t = token.trim();
    const s = sessionId.trim();
    if (!t || !s) {
      setError("token and session_id are required");
      return;
    }
    await AsyncStorage.multiSet([
      [TOKEN_KEY, t],
      [SESSION_KEY, s],
    ]);
    onReady();
  }, [onReady, sessionId, token]);

  const fetchAndSave = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const issued = await fetchAnonymousToken();
      await AsyncStorage.multiSet([
        [TOKEN_KEY, issued.token],
        [SESSION_KEY, issued.session_id],
      ]);
      onReady();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to fetch token");
    } finally {
      setBusy(false);
    }
  }, [onReady]);

  return (
    <View style={styles.gateShell}>
      <Text style={styles.title}>ARCHON Mobile</Text>
      <Text style={styles.subtitle}>Token bootstrap required to open secure WebSocket.</Text>

      <TextInput
        value={token}
        onChangeText={setToken}
        placeholder="token"
        placeholderTextColor="#64748b"
        autoCapitalize="none"
        style={styles.input}
      />
      <TextInput
        value={sessionId}
        onChangeText={setSessionId}
        placeholder="session_id"
        placeholderTextColor="#64748b"
        autoCapitalize="none"
        style={styles.input}
      />

      <Pressable style={styles.primaryBtn} disabled={busy} onPress={() => void fetchAndSave()}>
        <Text style={styles.primaryBtnText}>{busy ? "Fetching..." : "Fetch token"}</Text>
      </Pressable>

      <Pressable style={styles.secondaryBtn} onPress={() => void saveManual()}>
        <Text style={styles.secondaryBtnText}>Use entered token</Text>
      </Pressable>

      {error ? <Text style={styles.errorText}>{error}</Text> : null}
    </View>
  );
}

function RootNavigator() {
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void (async () => {
      const [[, token], [, sessionId]] = await AsyncStorage.multiGet([TOKEN_KEY, SESSION_KEY]);
      if (String(token || "").trim() && String(sessionId || "").trim()) {
        setReady(true);
      }
      setLoading(false);
    })();
  }, []);

  const theme = useMemo(
    () => ({
      ...DarkTheme,
      colors: {
        ...DarkTheme.colors,
        background: "#020617",
        card: "#020617",
        border: "#1e293b",
      },
    }),
    [],
  );

  if (loading) {
    return (
      <View style={styles.loadingWrap}>
        <ActivityIndicator size="large" color="#22d3ee" />
      </View>
    );
  }

  return (
    <NavigationContainer theme={theme}>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {!ready ? (
          <Stack.Screen name="TokenGate">
            {() => <TokenGate onReady={() => setReady(true)} />}
          </Stack.Screen>
        ) : (
          <>
            <Stack.Screen name="Home" component={HomeScreen} />
            <Stack.Screen name="MainTabs" component={MainTabs} />
          </>
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}

export function App() {
  return (
    <ARCHONProvider>
      <RootNavigator />
    </ARCHONProvider>
  );
}

const styles = StyleSheet.create({
  loadingWrap: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#020617",
  },
  gateShell: {
    flex: 1,
    backgroundColor: "#020617",
    paddingHorizontal: 16,
    justifyContent: "center",
    gap: 10,
  },
  title: {
    color: "#f8fafc",
    fontSize: 24,
    fontWeight: "700",
  },
  subtitle: {
    color: "#94a3b8",
    fontSize: 12,
    marginBottom: 6,
  },
  input: {
    height: 44,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#334155",
    backgroundColor: "#0f172a",
    color: "#f8fafc",
    paddingHorizontal: 12,
  },
  primaryBtn: {
    height: 44,
    borderRadius: 12,
    backgroundColor: "#0891b2",
    alignItems: "center",
    justifyContent: "center",
  },
  primaryBtnText: {
    color: "#ecfeff",
    fontWeight: "700",
  },
  secondaryBtn: {
    height: 44,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#1e293b",
    backgroundColor: "#0f172a",
    alignItems: "center",
    justifyContent: "center",
  },
  secondaryBtnText: {
    color: "#e2e8f0",
    fontWeight: "600",
  },
  errorText: {
    color: "#fca5a5",
    fontSize: 12,
  },
});

export default App;
