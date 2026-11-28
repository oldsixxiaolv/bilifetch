import type React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_MONO, FONT_SANS } from "../fonts";

type KeycapPillProps = {
  readonly keys: readonly string[];
  readonly label: string;
  readonly pressAt: number;
  readonly dark?: boolean;
  readonly accent?: string;
};

export const KeycapPill: React.FC<KeycapPillProps> = ({
  keys,
  label,
  pressAt,
  dark = false,
  accent = "#FB7299",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enter = spring({
    frame: Math.max(0, frame - (pressAt - 18)),
    fps,
    config: { damping: 16, stiffness: 220 },
  });

  const isPressed = frame >= pressAt && frame <= pressAt + 14;
  const pressDepth = isPressed
    ? interpolate(frame, [pressAt, pressAt + 4, pressAt + 14], [0, 5, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      })
    : 0;

  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 14,
        padding: "12px 20px",
        borderRadius: 18,
        backgroundColor: dark ? "rgba(28, 29, 36, 0.92)" : "rgba(255, 255, 255, 0.96)",
        border: `1.5px solid ${isPressed ? accent : dark ? "#343642" : "#E5E2DC"}`,
        boxShadow: isPressed
          ? `0 8px 28px rgba(251, 114, 153, 0.25)`
          : "0 14px 34px rgba(16, 16, 20, 0.14)",
        opacity: enter,
        scale: `${0.88 + 0.12 * enter}`,
      }}
    >
      <div style={{ display: "flex", gap: 6 }}>
        {keys.map((k) => (
          <div
            key={k}
            style={{
              minWidth: 44,
              height: 44,
              padding: "0 12px",
              borderRadius: 10,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: FONT_MONO,
              fontSize: 21,
              fontWeight: 700,
              color: isPressed ? "#FFFFFF" : dark ? "#F4F4F5" : "#18191C",
              backgroundColor: isPressed ? accent : dark ? "#2A2B34" : "#F3F2EE",
              border: `1px solid ${isPressed ? accent : dark ? "#404252" : "#D8D4CA"}`,
              boxShadow: isPressed
                ? "0 1px 0 rgba(0,0,0,0.3)"
                : dark
                  ? "0 4px 0 #14151A"
                  : "0 4px 0 #D0CCC2",
              translate: `0px ${pressDepth}px`,
            }}
          >
            {k}
          </div>
        ))}
      </div>
      <span
        style={{
          fontFamily: FONT_SANS,
          fontSize: 24,
          fontWeight: 600,
          color: dark ? "#F4F4F5" : "#18191C",
          whiteSpace: "nowrap",
        }}
      >
        {label}
      </span>
    </div>
  );
};
