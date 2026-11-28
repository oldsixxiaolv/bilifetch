import type React from "react";
import {
  AbsoluteFill,
  Easing,
  Interactive,
  interpolate,
  random,
  spring,
  useCurrentFrame,
  useVideoConfig,
  type InteractivitySchema,
} from "remotion";
import { FlowMediaSlot } from "../components/FlowMediaSlot";
import { FONT_MONO, FONT_SANS, FONT_SERIF, PALETTE } from "../fonts";
import { ExplodedView } from "./exploded-view.element";

type EngineArchitectureSceneProps = {
  readonly title: string;
  readonly flowEngineVideo?: string;
};

const CDN_NODES = [
  { host: "upos-sz-estghw", pct: 94, speed: 28.6, tag: "主链 28.6 MB/s", color: "#FB7299" },
  { host: "upos-sz-mirrorhw", pct: 74, speed: 21.4, tag: "并发 21.4 MB/s", color: "#00AEEC" },
  { host: "upos-sz-mirrorali", pct: 56, speed: 15.8, tag: "热备 15.8 MB/s", color: "#2BB673" },
  { host: "upos-sz-mirrorcoso1", pct: 6, speed: 0.1, tag: "慢节点已绕过", color: "#F25D59" },
] as const;

const FIBER_LANES = Array.from({ length: 12 }, (_, idx) => ({
  idx,
  speed: 18 + (idx % 5) * 4,
  offset: random(`lane-${idx}`) * 400,
  color: idx % 2 === 0 ? "#FB7299" : "#00AEEC",
}));

const EngineArchitectureSceneInner: React.FC<EngineArchitectureSceneProps> = ({
  title,
  flowEngineVideo,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const headerIn = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 180 },
  });

  const liveSpeed = interpolate(frame, [16, 130], [1.8, 28.6], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.23, 1, 0.32, 1),
  });

  const pauseStateText =
    frame < 240
      ? "64 路分片高速传输中"
      : frame < 330
        ? "⏸ 已暂停 · .part.state 字节锁保留 63%"
        : "▶ 0.4ms 瞬时恢复 · 无损合并完成";

  return (
    <>
      <div style={{ position: "absolute", inset: 0, opacity: 0.42, pointerEvents: "none" }}>
        <FlowMediaSlot
          videoFile={flowEngineVideo}
          fallbackImageFile="assets/flow-engine-keyframe.jpg"
          playbackRate={0.95}
        />
      </div>

      <AbsoluteFill
        style={{
          background:
            "linear-gradient(90deg, rgba(14,15,20,0.56) 0%, rgba(14,15,20,0.44) 48%, rgba(14,15,20,0.82) 100%)",
        }}
      />

      {/* Left Isometric Architecture Exploded View (Remocn uses 1920x1080 scene config, scaled cleanly) */}
      <div
        style={{
          position: "absolute",
          left: -175,
          top: 225,
          width: 1920,
          height: 1080,
          transformOrigin: "top left",
          transform: "scale(0.67)",
          pointerEvents: "none",
        }}
      >
        <ExplodedView
          from={0}
          durationInFrames={495}
          name="BiliFetch Stack Exploded"
          layers={4}
          labels={["PyQt5 原生界面", "64路 TLS并发池", "6节点 CDN自愈", "FFmpeg 无损合流"]}
          highlight={1}
          backgroundColor="transparent"
          speed={0.42}
          colors={{
            background: "transparent",
            top: "#E4E4E7",
            left: "#8E8E98",
            right: "#585862",
            highlightTop: "#FB7299",
            highlightLeft: "#D9567E",
            highlightRight: "#A33658",
            line: "#00AEEC",
            label: "#FFFFFF",
          }}
        />
      </div>

      {/* Top Header */}
      <div
        style={{
          position: "absolute",
          left: 108,
          right: 108,
          top: 72,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          opacity: headerIn,
          translate: `0px ${(1 - headerIn) * 24}px`,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <span
            style={{
              fontFamily: FONT_MONO,
              fontSize: 21,
              fontWeight: 700,
              color: PALETTE.blue,
              letterSpacing: "0.08em",
            }}
          >
            03 / CORE ENGINE ARCHITECTURE
          </span>
          <Interactive.Div
            name="Architecture Headline"
            style={{
              fontFamily: FONT_SERIF,
              fontSize: 64,
              fontWeight: 700,
              color: "#FFFFFF",
            }}
          >
            {title}
          </Interactive.Div>
        </div>

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "flex-end",
            padding: "12px 24px",
            borderRadius: 18,
            backgroundColor: "rgba(25,26,34,0.92)",
            border: "1.5px solid #2F313E",
          }}
        >
          <span style={{ fontFamily: FONT_MONO, fontSize: 16, color: "#A1A1AA" }}>
            THROUGHPUT · 40× SPEEDUP
          </span>
          <span
            style={{
              fontFamily: FONT_MONO,
              fontSize: 42,
              fontWeight: 800,
              color: PALETTE.pink,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {liveSpeed.toFixed(1)} MB/s
          </span>
        </div>
      </div>

      {/* Right Column: Live 64-Lane Optical Stream + CDN Race */}
      <div
        style={{
          position: "absolute",
          right: 96,
          top: 230,
          width: 760,
          bottom: 72,
          display: "flex",
          flexDirection: "column",
          gap: 22,
        }}
      >
        {/* 64-Lane Fiber Stream Visualizer */}
        <div
          style={{
            backgroundColor: "rgba(22, 23, 30, 0.88)",
            border: "1.5px solid #2D303D",
            borderRadius: 24,
            padding: "24px 28px",
            display: "flex",
            flexDirection: "column",
            gap: 14,
            overflow: "hidden",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontFamily: FONT_SANS, fontSize: 26, fontWeight: 800, color: "#FFFFFF" }}>
              64 路 TLS 保活分片并发流
            </span>
            <span
              style={{
                fontFamily: FONT_MONO,
                fontSize: 18,
                fontWeight: 700,
                color: frame >= 240 && frame < 330 ? PALETTE.orange : PALETTE.green,
              }}
            >
              {pauseStateText}
            </span>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {FIBER_LANES.map((lane) => {
              const paused = frame >= 240 && frame < 330;
              const effectiveFrame = paused ? 240 : frame > 330 ? frame - 90 : frame;
              const packetX = ((effectiveFrame * lane.speed + lane.offset) % 780) - 120;
              return (
                <div
                  key={lane.idx}
                  style={{
                    position: "relative",
                    height: 6,
                    borderRadius: 999,
                    backgroundColor: "#232530",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      position: "absolute",
                      top: 0,
                      bottom: 0,
                      left: packetX,
                      width: 110,
                      borderRadius: 999,
                      background: `linear-gradient(90deg, transparent, ${lane.color})`,
                      opacity: paused ? 0.35 : 0.95,
                    }}
                  />
                </div>
              );
            })}
          </div>
        </div>

        {/* Multi-CDN Probe Bars */}
        <div
          style={{
            flex: 1,
            backgroundColor: "rgba(22, 23, 30, 0.88)",
            border: "1.5px solid #2D303D",
            borderRadius: 24,
            padding: "26px 28px",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
          }}
        >
          <span style={{ fontFamily: FONT_SANS, fontSize: 26, fontWeight: 800, color: "#FFFFFF" }}>
            多 CDN 并发探速 · 断流毫秒级切流
          </span>

          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            {CDN_NODES.map((node, i) => {
              const prog = interpolate(frame, [24 + i * 16, 120 + i * 16], [0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
                easing: Easing.bezier(0.23, 1, 0.32, 1),
              });
              const bypassed = node.pct < 10 && frame >= 125;
              return (
                <div key={node.host} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span
                      style={{
                        fontFamily: FONT_MONO,
                        fontSize: 20,
                        color: bypassed ? "#71717A" : "#E4E4E7",
                        textDecoration: bypassed ? "line-through" : "none",
                      }}
                    >
                      {node.host}.bilivideo.com
                    </span>
                    <span
                      style={{
                        fontFamily: FONT_MONO,
                        fontSize: 19,
                        fontWeight: 700,
                        color: node.color,
                      }}
                    >
                      {node.tag}
                    </span>
                  </div>
                  <div
                    style={{
                      height: 12,
                      borderRadius: 999,
                      backgroundColor: "#252732",
                      overflow: "hidden",
                    }}
                  >
                    <div
                      style={{
                        height: "100%",
                        width: `${node.pct * prog}%`,
                        borderRadius: 999,
                        background:
                          i === 0
                            ? "linear-gradient(90deg, #FB7299, #00AEEC)"
                            : node.color,
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </>
  );
};

const engineSchema = {
  ...Interactive.backgroundSchema,
  title: {
    type: "string",
    default: "把功夫花在看不见的稳定性上",
    description: "Architecture Headline",
  },
  flowEngineVideo: {
    type: "string",
    default: "assets/flow-engine.mp4",
    description: "Optional Flow Engine MP4",
  },
} as const satisfies InteractivitySchema;

export const EngineArchitectureScene = Interactive.create({
  Component: EngineArchitectureSceneInner,
  layout: "absolute-fill",
  schema: engineSchema,
});
