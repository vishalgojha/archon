import React from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";

export type ComparisonRow = {
  label: string;
  values: Array<string | number>;
};

export type ComparisonTableData = {
  headers: string[];
  rows: ComparisonRow[];
  winner_column?: number;
};

type Props = {
  data: ComparisonTableData;
};

export function ComparisonTable({ data }: Props) {
  const winner = Number.isInteger(data.winner_column) ? Number(data.winner_column) : -1;

  return (
    <ScrollView horizontal style={styles.card} contentContainerStyle={styles.content}>
      <View>
        <View style={styles.row}>
          {data.headers.map((header, index) => (
            <View key={`${header}-${index}`} style={[styles.cell, index === winner ? styles.winnerCell : null]}>
              <Text style={styles.headerText}>{header}</Text>
            </View>
          ))}
        </View>

        {data.rows.map((row, rowIndex) => (
          <View key={`${row.label}-${rowIndex}`} style={styles.row}>
            <View style={[styles.cell, styles.rowLabelCell]}>
              <Text style={styles.rowLabel}>{row.label}</Text>
            </View>
            {row.values.map((value, colIndex) => (
              <View
                key={`${row.label}-${colIndex}`}
                style={[styles.cell, colIndex + 1 === winner ? styles.winnerCell : null]}
              >
                <Text style={styles.valueText}>{String(value)}</Text>
              </View>
            ))}
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: "#0f172a",
    borderWidth: 1,
    borderColor: "#1e293b",
    borderRadius: 12,
  },
  content: {
    padding: 10,
  },
  row: {
    flexDirection: "row",
  },
  cell: {
    minWidth: 110,
    borderWidth: 1,
    borderColor: "#1f2937",
    paddingHorizontal: 8,
    paddingVertical: 7,
    justifyContent: "center",
  },
  rowLabelCell: {
    backgroundColor: "#0b1220",
  },
  winnerCell: {
    backgroundColor: "#052e16",
    borderColor: "#15803d",
  },
  headerText: {
    color: "#e2e8f0",
    fontSize: 12,
    fontWeight: "700",
  },
  rowLabel: {
    color: "#cbd5e1",
    fontSize: 12,
    fontWeight: "600",
  },
  valueText: {
    color: "#d1d5db",
    fontSize: 12,
  },
});

export default ComparisonTable;
