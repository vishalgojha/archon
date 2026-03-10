import React, { useCallback, useEffect, useMemo, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useNavigation } from "@react-navigation/native";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useARCHONMobileContext } from "./useARCHONMobile";

const AUTONOMY_KEY = "archon.mobile.autonomy";

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

const VoiceMaybe: any = (() => {
  try {
    return require("@react-native-voice/voice").default;
  } catch (_err) {
    return null;
  }
})();

const SpeechMaybe: { speak?: (text: string) => void } = (() => {
  try {
    return require("expo-speech");
  } catch (_err) {
    return {};
  }
})();

export function HomeScreen() {
  const navigation = useNavigation();
  const { send } = useARCHONMobileContext();

  const [text, setText] = useState("");
  const [autonomy, setAutonomy] = useState(50);
  const [listening, setListening] = useState(false);

  useEffect(() => {
    void (async () => {
      const raw = await AsyncStorage.getItem(AUTONOMY_KEY);
      const parsed = Number(raw || "50");
      if (Number.isFinite(parsed)) {
        setAutonomy(Math.max(0, Math.min(100, Math.round(parsed))));
      }
    })();
  }, []);

  const persistAutonomy = useCallback(async (value: number) => {
    const bounded = Math.max(0, Math.min(100, Math.round(value)));
    setAutonomy(bounded);
    await AsyncStorage.setItem(AUTONOMY_KEY, String(bounded));
  }, []);

  const submitMessage = useCallback(
    (rawText: string) => {
      const content = String(rawText || "").trim();
      if (!content) {
        return;
      }
      send({
        type: "message",
        content,
        autonomy,
      });
      setText("");
      navigation.navigate("MainTabs" as never, { screen: "Chat" } as never);
    },
    [autonomy, navigation, send],
  );

  useEffect(() => {
    if (!VoiceMaybe) {
      return undefined;
    }

    VoiceMaybe.onSpeechResults = (event: { value?: string[] }) => {
      const transcript = String(event?.value?.[0] || "").trim();
      setListening(false);
      if (transcript) {
        submitMessage(transcript);
      }
    };

    VoiceMaybe.onSpeechError = () => {
      setListening(false);
    };

    return () => {
      VoiceMaybe.destroy?.();
    };
  }, [submitMessage]);

  const sliderNode = useMemo(() => {
    if (!SliderMaybe) {
      return (
        <View style={styles.fallbackSliderRow}>
          <Pressable onPress={() => void persistAutonomy(autonomy - 10)} style={styles.smallButton}>
            <Text style={styles.smallButtonText}>-10</Text>
          </Pressable>
          <Text style={styles.autonomyValue}>{autonomy}%</Text>
          <Pressable onPress={() => void persistAutonomy(autonomy + 10)} style={styles.smallButton}>
            <Text style={styles.smallButtonText}>+10</Text>
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
          void persistAutonomy(value);
        }}
        minimumTrackTintColor="#06b6d4"
        maximumTrackTintColor="#334155"
        thumbTintColor="#22d3ee"
      />
    );
  }, [autonomy, persistAutonomy]);

  const startVoiceCapture = useCallback(async () => {
    if (!VoiceMaybe) {
      SpeechMaybe.speak?.("Voice input is unavailable on this build.");
      return;
    }

    try {
      if (listening) {
        await VoiceMaybe.stop?.();
        setListening(false);
        return;
      }
      setListening(true);
      await VoiceMaybe.start("en-US");
    } catch (_err) {
      setListening(false);
    }
  }, [listening]);

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      style={styles.shell}
    >
      <View style={styles.centerWrap}>
        <View style={styles.inputRow}>
          <Pressable
            accessibilityRole="button"
            style={[styles.voiceButton, listening ? styles.voiceButtonActive : null]}
            onPress={() => {
              void startVoiceCapture();
            }}
          >
            <Text style={styles.voiceButtonText}>{listening ? "Stop" : "Mic"}</Text>
          </Pressable>

          <TextInput
            value={text}
            onChangeText={setText}
            placeholder="Ask ARCHON"
            placeholderTextColor="#64748b"
            style={styles.input}
            returnKeyType="send"
            onSubmitEditing={() => submitMessage(text)}
          />

          <Pressable onPress={() => submitMessage(text)} style={styles.sendButton}>
            <Text style={styles.sendButtonText}>Send</Text>
          </Pressable>
        </View>

        <View style={styles.sliderBox}>
          <Text style={styles.autonomyLabel}>Autonomy: {autonomy}%</Text>
          {sliderNode}
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  shell: {
    flex: 1,
    backgroundColor: "#020617",
  },
  centerWrap: {
    flex: 1,
    justifyContent: "center",
    paddingHorizontal: 16,
    gap: 14,
  },
  inputRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  voiceButton: {
    width: 52,
    height: 48,
    borderRadius: 14,
    backgroundColor: "#0f172a",
    borderWidth: 1,
    borderColor: "#1e293b",
    alignItems: "center",
    justifyContent: "center",
  },
  voiceButtonActive: {
    backgroundColor: "#7f1d1d",
    borderColor: "#dc2626",
  },
  voiceButtonText: {
    color: "#e2e8f0",
    fontWeight: "600",
  },
  input: {
    flex: 1,
    height: 48,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "#1e293b",
    backgroundColor: "#0f172a",
    color: "#f8fafc",
    paddingHorizontal: 14,
  },
  sendButton: {
    height: 48,
    borderRadius: 14,
    paddingHorizontal: 16,
    backgroundColor: "#0891b2",
    alignItems: "center",
    justifyContent: "center",
  },
  sendButtonText: {
    color: "#ecfeff",
    fontWeight: "700",
  },
  sliderBox: {
    backgroundColor: "#0f172a",
    borderWidth: 1,
    borderColor: "#1e293b",
    borderRadius: 12,
    padding: 12,
    gap: 8,
  },
  autonomyLabel: {
    color: "#cbd5e1",
    fontSize: 12,
  },
  autonomyValue: {
    color: "#e2e8f0",
    fontSize: 13,
    fontWeight: "700",
    minWidth: 54,
    textAlign: "center",
  },
  fallbackSliderRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  smallButton: {
    borderWidth: 1,
    borderColor: "#334155",
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: "#020617",
  },
  smallButtonText: {
    color: "#cbd5e1",
    fontSize: 12,
  },
});

export default HomeScreen;
