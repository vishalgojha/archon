import React, { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

export type ReportSection = {
  heading: string;
  body: string;
};

export type ReportCardData = {
  title: string;
  summary: string;
  sections: ReportSection[];
};

type Props = {
  data: ReportCardData;
};

export function ReportCard({ data }: Props) {
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});

  return (
    <View style={styles.card}>
      <Text style={styles.title}>{data.title}</Text>
      <Text style={styles.summary}>{data.summary}</Text>

      {data.sections.map((section, index) => {
        const isOpen = !!expanded[index];
        return (
          <View key={`${section.heading}-${index}`} style={styles.sectionWrap}>
            <Pressable
              onPress={() => setExpanded((prev) => ({ ...prev, [index]: !prev[index] }))}
              style={styles.sectionHeader}
            >
              <Text style={styles.sectionTitle}>{section.heading}</Text>
              <Text style={styles.sectionToggle}>{isOpen ? "Hide" : "Show"}</Text>
            </Pressable>
            {isOpen ? <Text style={styles.sectionBody}>{section.body}</Text> : null}
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: "#111827",
    borderColor: "#1f2937",
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    gap: 8,
  },
  title: {
    color: "#f8fafc",
    fontWeight: "700",
    fontSize: 16,
  },
  summary: {
    color: "#d1d5db",
    fontSize: 13,
    lineHeight: 18,
  },
  sectionWrap: {
    backgroundColor: "#0b1220",
    borderColor: "#1f2937",
    borderWidth: 1,
    borderRadius: 10,
    padding: 8,
    gap: 6,
  },
  sectionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  sectionTitle: {
    color: "#e5e7eb",
    fontWeight: "600",
    fontSize: 13,
  },
  sectionToggle: {
    color: "#38bdf8",
    fontSize: 12,
  },
  sectionBody: {
    color: "#cbd5e1",
    fontSize: 12,
    lineHeight: 17,
  },
});

export default ReportCard;
