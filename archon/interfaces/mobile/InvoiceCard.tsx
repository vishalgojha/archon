import React from "react";
import { StyleSheet, Text, View } from "react-native";

export type InvoiceLineItem = {
  description: string;
  quantity: number;
  unit_price: number;
  total: number;
};

export type InvoiceCardData = {
  invoice_number?: string;
  due_date: string;
  currency?: string;
  line_items: InvoiceLineItem[];
  total: number;
};

type Props = {
  data: InvoiceCardData;
};

function fmtMoney(value: number, currency?: string): string {
  const code = (currency || "USD").toUpperCase();
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: code }).format(value);
  } catch (_err) {
    return `${code} ${value.toFixed(2)}`;
  }
}

export function InvoiceCard({ data }: Props) {
  return (
    <View style={styles.card}>
      <View style={styles.headerRow}>
        <Text style={styles.title}>Invoice</Text>
        {data.invoice_number ? <Text style={styles.meta}>#{data.invoice_number}</Text> : null}
      </View>

      <View style={styles.tableHeader}>
        <Text style={[styles.headerCell, styles.description]}>Item</Text>
        <Text style={styles.headerCell}>Qty</Text>
        <Text style={styles.headerCell}>Rate</Text>
        <Text style={styles.headerCell}>Total</Text>
      </View>

      {data.line_items.map((item, index) => (
        <View key={`${item.description}-${index}`} style={styles.tableRow}>
          <Text style={[styles.cell, styles.description]} numberOfLines={2}>
            {item.description}
          </Text>
          <Text style={styles.cell}>{item.quantity}</Text>
          <Text style={styles.cell}>{fmtMoney(item.unit_price, data.currency)}</Text>
          <Text style={styles.cell}>{fmtMoney(item.total, data.currency)}</Text>
        </View>
      ))}

      <View style={styles.footer}>
        <Text style={styles.meta}>Due: {data.due_date}</Text>
        <Text style={styles.total}>{fmtMoney(data.total, data.currency)}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: "#0f172a",
    borderColor: "#1e293b",
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    gap: 10,
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  title: {
    color: "#f8fafc",
    fontSize: 16,
    fontWeight: "700",
  },
  meta: {
    color: "#94a3b8",
    fontSize: 12,
  },
  tableHeader: {
    flexDirection: "row",
    borderBottomColor: "#1e293b",
    borderBottomWidth: 1,
    paddingBottom: 6,
  },
  tableRow: {
    flexDirection: "row",
    borderBottomColor: "#0b1220",
    borderBottomWidth: 1,
    paddingVertical: 6,
  },
  headerCell: {
    flex: 1,
    color: "#cbd5e1",
    fontSize: 12,
    fontWeight: "700",
  },
  cell: {
    flex: 1,
    color: "#e2e8f0",
    fontSize: 12,
  },
  description: {
    flex: 2,
    paddingRight: 6,
  },
  footer: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 2,
  },
  total: {
    color: "#22c55e",
    fontSize: 15,
    fontWeight: "700",
  },
});

export default InvoiceCard;
