import React, { useEffect, useMemo, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { useARCHONMobileContext } from "./useARCHONMobile";

const AUTONOMY_KEY = "archon.mobile.autonomy";
const PROVIDERS = ["openai", "anthropic", "openrouter", "gemini", "groq", "mistral"];

type SliderLikeProps = {
  value: number;
  minimumValue: number;
  maximumValue: number;
  step?: number;
  onValueChange: (value: number) => void;
  minimumTrackTintColor?: string;
  maximumTrackTintColor?: string;
  thumbTintColor?: string;
};

const SliderMaybe: React.ComponentType<SliderLikeProps> | null = (() => {
  try {
    return require("@react-native-community/slider").default;
  } catch (_err) {
    return null;
  }
})();

function keyForProvider(provider: string): string {
  return `archon.mobile.byok.${provider}`;
}

function autonomyLabel(value: number): string {
  if (value <= 25) {
    return "Low autonomy: ARCHON waits for explicit direction.";
  }
  if (value <= 60) {
    return "Balanced autonomy: proposes and executes low-risk actions.";
  }
  return "High autonomy: ARCHON pursues broader execution paths.";
}

export function SettingsScreen() {
  const { clearHistory, disconnect, connect } = useARCHONMobileContext();

  const [providerKeys, setProviderKeys] = useState<Record<string, string>>({});
  const [autonomy, setAutonomy] = useState(50);
  const [savedStamp, setSavedStamp] = useState("");

  useEffect(() => {
    void (async () => {
      const rows = await AsyncStorage.multiGet([
        AUTONOMY_KEY,
        ...PROVIDERS.map((provider) => keyForProvider(provider)),
      ]);

      const mapped: Record<string, string> = {};
      rows.forEach(([key, value]) => {
        if (key === AUTONOMY_KEY) {
          const parsed = Number(value || "50");
          if (Number.isFinite(parsed)) {
            setAutonomy(Math.max(0, Math.min(100, Math.round(parsed))));
          }
          return;
        }
        const provider = key.replace("archon.mobile.byok.", "");
        mapped[provider] = String(value || "");
      });

      setProviderKeys(mapped);
    })();
  }, []);

  const saveProviderKey = async (provider: string) => {
    const value = String(providerKeys[provider] || "").trim();
    await AsyncStorage.setItem(keyForProvider(provider), value);
    setSavedStamp(`${provider} saved`);
  };

  const updateAutonomy = async (nextValue: number) => {
    const bounded = Math.max(0, Math.min(100, Math.round(nextValue)));
    setAutonomy(bounded);
    await AsyncStorage.setItem(AUTONOMY_KEY, String(bounded));
  };

  const clearSession = async () => {
    await clearHistory();
    await AsyncStorage.removeItem("archon.mobile.session_id");
    await AsyncStorage.removeItem("archon.mobile.token");
    disconnect();
    const token = await AsyncStorage.getItem("archon.mobile.token");
    const sessionId = await AsyncStorage.getItem("archon.mobile.session_id");
    if (token && sessionId) {
      connect(sessionId, token);
    }
    setSavedStamp("session cleared");
  };

  const sliderNode = useMemo(() => {
    if (!SliderMaybe) {
      return (
        <View style={styles.fallbackSlider}>
          <Pressable style={styles.smallBtn} onPress={() => void updateAutonomy(autonomy - 10)}>
            <Text style={styles.smallBtnText}>-10</Text>
          </Pressable>
          <Text style={styles.autonomyValue}>{autonomy}%</Text>
          <Pressable style={styles.smallBtn} onPress={() => void updateAutonomy(autonomy + 10)}>
            <Text style={styles.smallBtnText}>+10</Text>
          </Pressable>
        </View>
      );
    }

    return (
      <SliderMaybe
        value={autonomy}
        minimumValue={0}
        maximumValue={100}
        step={1}
        onValueChange={(value: number) => {
          void updateAutonomy(value);
        }}
        minimumTrackTintColor="#06b6d4"
        maximumTrackTintColor="#334155"
        thumbTintColor="#22d3ee"
      />
    );
  }, [autonomy]);

  const appVersion = String((globalThis as any).APP_VERSION || "0.1.0-mobile");
  const archonVersion = String((globalThis as any).ARCHON_VERSION || "0.1.0");

  return (
    <ScrollView style={styles.shell} contentContainerStyle={styles.content}>
      <View style={styles.card}>
        <Text style={styles.cardTitle}>BYOK Keys (on device only)</Text>
        {PROVIDERS.map((provider) => (
          <View key={provider} style={styles.providerRow}>
            <Text style={styles.providerLabel}>{provider}</Text>
            <TextInput
              value={providerKeys[provider] || ""}
              onChangeText={(next) =>
                setProviderKeys((prev) => ({
                  ...prev,
                  [provider]: next,
                }))
              }
              placeholder={`${provider} key`}
              placeholderTextColor="#64748b"
              secureTextEntry
              style={styles.input}
            />
            <Pressable style={styles.saveBtn} onPress={() => void saveProviderKey(provider)}>
              <Text style={styles.saveBtnText}>Save</Text>
            </Pressable>
          </View>
        ))}
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Autonomy</Text>
        <Text style={styles.autonomyValue}>{autonomy}%</Text>
        {sliderNode}
        <Text style={styles.labelHint}>{autonomyLabel(autonomy)}</Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Session</Text>
        <Pressable style={styles.clearBtn} onPress={() => void clearSession()}>
          <Text style={styles.clearBtnText}>Clear session history</Text>
        </Pressable>
        {savedStamp ? <Text style={styles.savedStamp}>{savedStamp}</Text> : null}
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Versions</Text>
        <Text style={styles.labelHint}>App: {appVersion}</Text>
        <Text style={styles.labelHint}>ARCHON: {archonVersion}</Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  shell: {
    flex: 1,
    backgroundColor: "#020617",
  },
  content: {
    padding: 12,
    gap: 10,
  },
  card: {
    backgroundColor: "#0f172a",
    borderColor: "#1e293b",
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    gap: 8,
  },
  cardTitle: {
    color: "#f8fafc",
    fontWeight: "700",
    fontSize: 14,
  },
  providerRow: {
    gap: 6,
    borderWidth: 1,
    borderColor: "#1e293b",
    borderRadius: 10,
    padding: 8,
    backgroundColor: "#020617",
  },
  providerLabel: {
    color: "#cbd5e1",
    fontSize: 12,
    textTransform: "uppercase",
  },
  input: {
    borderWidth: 1,
    borderColor: "#334155",
    borderRadius: 10,
    height: 40,
    color: "#f8fafc",
    paddingHorizontal: 10,
    backgroundColor: "#0f172a",
  },
  saveBtn: {
    alignSelf: "flex-start",
    backgroundColor: "#0891b2",
    borderRadius: 9,
    paddingVertical: 6,
    paddingHorizontal: 12,
  },
  saveBtnText: {
    color: "#ecfeff",
    fontWeight: "700",
    fontSize: 12,
  },
  autonomyValue: {
    color: "#67e8f9",
    fontSize: 13,
    fontWeight: "700",
  },
  labelHint: {
    color: "#94a3b8",
    fontSize: 12,
    lineHeight: 17,
  },
  clearBtn: {
    backgroundColor: "#b91c1c",
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    alignItems: "center",
  },
  clearBtnText: {
    color: "#fef2f2",
    fontWeight: "700",
    fontSize: 12,
  },
  savedStamp: {
    color: "#22d3ee",
    fontSize: 12,
  },
  fallbackSlider: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  smallBtn: {
    borderColor: "#334155",
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  smallBtnText: {
    color: "#cbd5e1",
    fontSize: 12,
  },
});

export default SettingsScreen;
