import React from "react";
import { StyleSheet, Text, View } from "react-native";

export type TimelineStep = {
  title: string;
  date: string;
  detail?: string;
};

export type TimelineCardData = {
  title?: string;
  steps: TimelineStep[];
};

type Props = {
  data: TimelineCardData;
};

export function TimelineCard({ data }: Props) {
  return (
    <View style={styles.card}>
      <Text style={styles.title}>{data.title || "Plan Timeline"}</Text>
      <View style={styles.track}>
        {data.steps.map((step, index) => (
          <View key={`${step.title}-${index}`} style={styles.stepRow}>
            <View style={styles.markerWrap}>
              <View style={styles.marker} />
              {index < data.steps.length - 1 ? <View style={styles.connector} /> : null}
            </View>
            <View style={styles.stepBody}>
              <Text style={styles.stepTitle}>{step.title}</Text>
              <Text style={styles.stepDate}>{step.date}</Text>
              {step.detail ? <Text style={styles.stepDetail}>{step.detail}</Text> : null}
            </View>
          </View>
        ))}
      </View>
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
    gap: 10,
  },
  title: {
    color: "#f8fafc",
    fontSize: 15,
    fontWeight: "700",
  },
  track: {
    gap: 0,
  },
  stepRow: {
    flexDirection: "row",
    alignItems: "flex-start",
  },
  markerWrap: {
    width: 22,
    alignItems: "center",
  },
  marker: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: "#22d3ee",
    marginTop: 4,
  },
  connector: {
    width: 2,
    flex: 1,
    minHeight: 28,
    backgroundColor: "#334155",
    marginTop: 4,
  },
  stepBody: {
    flex: 1,
    paddingBottom: 14,
  },
  stepTitle: {
    color: "#e2e8f0",
    fontSize: 13,
    fontWeight: "600",
  },
  stepDate: {
    color: "#38bdf8",
    fontSize: 12,
    marginTop: 2,
  },
  stepDetail: {
    color: "#cbd5e1",
    fontSize: 12,
    marginTop: 4,
    lineHeight: 16,
  },
});

export default TimelineCard;
