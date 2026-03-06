import React, { useMemo } from "react";
import { FlatList, StyleSheet, Text, View } from "react-native";

import { useARCHONMobileContext } from "./useARCHONMobile";

function shortJson(value: unknown, maxChars = 220): string {
  let text = "";
  try {
    text = typeof value === "string" ? value : JSON.stringify(value);
  } catch (_err) {
    text = String(value);
  }
  return text.length > maxChars ? `${text.slice(0, maxChars)}...` : text;
}

export function HistoryScreen() {
  const { history, costState } = useARCHONMobileContext();

  const rows = useMemo(() => {
    return [...history].slice(-100).reverse();
  }, [history]);

  return (
    <View style={styles.shell}>
      <View style={styles.metaRow}>
        <Text style={styles.metaText}>Events: {history.length}</Text>
        <Text style={styles.metaText}>
          Spend: ${Number(costState.spent || 0).toFixed(4)} / ${Number(costState.budget || 0).toFixed(2)}
        </Text>
      </View>

      <FlatList
        data={rows}
        keyExtractor={(_item, index) => `history-${index}`}
        contentContainerStyle={styles.list}
        renderItem={({ item }) => (
          <View style={styles.row}>
            <Text style={styles.type}>{String(item.type || "event")}</Text>
            <Text style={styles.payload}>{shortJson(item.output || item.payload || item.result || item, 260)}</Text>
          </View>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  shell: {
    flex: 1,
    backgroundColor: "#020617",
  },
  metaRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    borderBottomWidth: 1,
    borderBottomColor: "#1e293b",
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  metaText: {
    color: "#94a3b8",
    fontSize: 12,
  },
  list: {
    padding: 12,
    gap: 8,
  },
  row: {
    borderWidth: 1,
    borderColor: "#1e293b",
    borderRadius: 10,
    backgroundColor: "#0f172a",
    padding: 10,
    gap: 5,
  },
  type: {
    color: "#67e8f9",
    fontWeight: "700",
    fontSize: 12,
  },
  payload: {
    color: "#cbd5e1",
    fontSize: 12,
    lineHeight: 17,
  },
});

export default HistoryScreen;
