import type React from "react";
import { AbsoluteFill, interpolate, random, useCurrentFrame, useVideoConfig } from "remotion";

type SpeedLinesLayerProps = {
  readonly color?: string;
  readonly opacityMax?: number;
};

export const SpeedLinesLayer: React.FC<SpeedLinesLayerProps> = ({
  color = "#FB7299",
  opacityMax = 0.28,
}) => {
  const frame = useCurrentFrame();
  const { width, height, durationInFrames } = useVideoConfig();
  const seed = Math.floor(frame / 3);
  const cx = width / 2;
  const cy = height / 2;
  const far = Math.hypot(width, height);

  const lines = new Array(48).fill(true).map((_, i) => {
    const angle = (i / 48) * Math.PI * 2 + random(`angle-${i}-${seed}`) * 0.07;
    const spread = 0.004 + random(`spread-${i}-${seed}`) * 0.011;
    const inner = 0.42 + random(`inner-${i}-${seed}`) * 0.24;
    const x1 = cx + Math.cos(angle - spread) * far;
    const y1 = cy + Math.sin(angle - spread) * far;
    const x2 = cx + Math.cos(angle + spread) * far;
    const y2 = cy + Math.sin(angle + spread) * far;
    const xi = cx + Math.cos(angle) * inner * (width / 2);
    const yi = cy + Math.sin(angle) * inner * (height / 2);
    return `M ${xi.toFixed(1)} ${yi.toFixed(1)} L ${x1.toFixed(1)} ${y1.toFixed(1)} L ${x2.toFixed(1)} ${y2.toFixed(1)} Z`;
  });

  const opacity = interpolate(
    frame,
    [0, 6, Math.max(8, durationInFrames - 8), durationInFrames],
    [0, opacityMax, opacityMax, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  return (
    <AbsoluteFill style={{ opacity, pointerEvents: "none" }}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        {lines.map((d, idx) => (
          <path
            key={idx}
            d={d}
            fill={idx % 3 === 0 ? "#00AEEC" : color}
          />
        ))}
      </svg>
    </AbsoluteFill>
  );
};
