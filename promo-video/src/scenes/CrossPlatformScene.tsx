import type React from "react";
import {
  AbsoluteFill,
  Easing,
  Interactive,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
  type InteractivitySchema,
} from "remotion";
import { FlowMediaSlot } from "../components/FlowMediaSlot";
import { FONT_MONO, FONT_SANS, FONT_SERIF, PALETTE } from "../fonts";

type CrossPlatformSceneProps = {
  readonly title: string;
  readonly cliCommand: string;
  readonly flowFinaleVideo?: string;
};

const DOCK_OS = [
  { os: "macOS", sub: ".dmg 50.6 MB · 开箱即用", accent: "#FB7299", at: 24 },
  { os: "Windows", sub: ".exe 免安装 · 内置 FFmpeg", accent: "#00AEEC", at: 50 },
  { os: "Linux", sub: ".deb 519 KB & .tar.gz", accent: "#2BB673", at: 76 },
] as const;

const CrossPlatformSceneInner: React.FC<CrossPlatformSceneProps> = ({
  title,
  cliCommand,
  flowFinaleVideo,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const headerIn = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 180 },
  });

  const typedChars = Math.floor(
    interpolate(frame, [68, 160], [0, cliCommand.length], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }),
  );
  const showDone = frame >= 180;

  return (
    <>
      {/* Full-Bleed Cinema Backdrop (Flow Video Slot) */}
      <FlowMediaSlot
        videoFile={flowFinaleVideo}
        fallbackImageFile="assets/fox-finale-light.jpg"
        style={{
          scale: `${interpolate(frame, [0, 315], [1.0, 1.07], {
            extrapolateRight: "clamp",
            easing: Easing.bezier(0.23, 1, 0.32, 1),
          })}`,
        }}
      />

      {/* Subtle top-left & bottom legibility scrim without hiding the 3D fox */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(180deg, rgba(250,249,246,0.88) 0%, rgba(250,249,246,0.12) 38%, rgba(17,18,22,0.15) 68%, rgba(17,18,22,0.86) 100%)",
        }}
      />

      {/* Top Editorial Headline */}
      <div
        style={{
          position: "absolute",
          left: 108,
          top: 38,
          right: 108,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          opacity: headerIn,
          translate: `0px ${(1 - headerIn) * 24}px`,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span
            style={{
              fontFamily: FONT_MONO,
              fontSize: 20,
              fontWeight: 700,
              color: PALETTE.pinkDark,
              letterSpacing: "0.08em",
            }}
          >
            04 / NATIVE EVERYWHERE
          </span>
          <Interactive.Div
            name="Cross Platform Title"
            style={{
              fontFamily: FONT_SERIF,
              fontSize: 48,
              fontWeight: 700,
              color: PALETTE.ink,
              lineHeight: 1.15,
              whiteSpace: "pre-line",
              textShadow: "0 2px 12px rgba(250,249,246,0.9)",
            }}
          >
            {title}
          </Interactive.Div>
        </div>

        <span
          style={{
            fontFamily: FONT_MONO,
            fontSize: 21,
            fontWeight: 700,
            color: PALETTE.ink,
            backgroundColor: "rgba(255,255,255,0.88)",
            backdropFilter: "blur(10px)",
            padding: "12px 22px",
            borderRadius: 999,
            border: "1px solid rgba(22,22,21,0.12)",
          }}
        >
          Apache-2.0 · 完全开源 · 零遥测
        </span>
      </div>

      {/* Bottom Floating Frosted Glass OS Dock + Live Terminal Bar */}
      <div
        style={{
          position: "absolute",
          left: 108,
          right: 108,
          bottom: 64,
          display: "flex",
          flexDirection: "column",
          gap: 18,
        }}
      >
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 20 }}>
          {DOCK_OS.map((item) => {
            const p = spring({
              frame: Math.max(0, frame - item.at),
              fps,
              config: { damping: 16, stiffness: 210 },
            });
            return (
              <div
                key={item.os}
                style={{
                  padding: "20px 26px",
                  borderRadius: 22,
                  backgroundColor: "rgba(255, 255, 255, 0.88)",
                  backdropFilter: "blur(16px)",
                  border: "1.5px solid rgba(255, 255, 255, 0.95)",
                  boxShadow: "0 20px 50px rgba(0, 0, 0, 0.22)",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  opacity: p,
                  translate: `0px ${(1 - p) * 32}px`,
                }}
              >
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <span style={{ fontFamily: FONT_SANS, fontSize: 32, fontWeight: 900, color: PALETTE.ink }}>
                    {item.os}
                  </span>
                  <span style={{ fontFamily: FONT_MONO, fontSize: 19, color: PALETTE.ink2 }}>
                    {item.sub}
                  </span>
                </div>
                <div
                  style={{
                    width: 14,
                    height: 14,
                    borderRadius: "50%",
                    backgroundColor: item.accent,
                    boxShadow: `0 0 14px ${item.accent}`,
                  }}
                />
              </div>
            );
          })}
        </div>

        {/* Floating Dark Glass CLI Terminal */}
        <div
          style={{
            padding: "20px 28px",
            borderRadius: 20,
            backgroundColor: "rgba(18, 19, 25, 0.92)",
            backdropFilter: "blur(16px)",
            border: "1.5px solid rgba(255, 255, 255, 0.16)",
            boxShadow: "0 22px 60px rgba(0, 0, 0, 0.42)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <span style={{ fontFamily: FONT_MONO, fontSize: 24, fontWeight: 800, color: PALETTE.pink }}>
              $
            </span>
            <span style={{ fontFamily: FONT_MONO, fontSize: 24, color: "#F4F4F5" }}>
              {cliCommand.slice(0, typedChars)}
              <span style={{ color: PALETTE.blue, opacity: frame % 20 < 10 ? 1 : 0 }}>_</span>
            </span>
          </div>

          {showDone && (
            <span
              style={{
                fontFamily: FONT_MONO,
                fontSize: 21,
                fontWeight: 700,
                color: PALETTE.green,
                opacity: interpolate(frame, [180, 195], [0, 1], {
                  extrapolateLeft: "clamp",
                  extrapolateRight: "clamp",
                }),
              }}
            >
              ✓ 12/12 集无损混流完成 · 28.6 MB/s
            </span>
          )}
        </div>
      </div>
    </>
  );
};

const crossPlatformSchema = {
  ...Interactive.backgroundSchema,
  title: {
    type: "string",
    default: "全平台原生 · 图形与命令行双修",
    description: "Platform Title",
  },
  cliCommand: {
    type: "string",
    default: 'bilifetch "ep1633643" --all-episodes -q 120',
    description: "CLI Demo Command",
  },
  flowFinaleVideo: {
    type: "string",
    default: "",
    description: "Optional Flow Finale MP4",
  },
} as const satisfies InteractivitySchema;

export const CrossPlatformScene = Interactive.create({
  Component: CrossPlatformSceneInner,
  layout: "absolute-fill",
  schema: crossPlatformSchema,
});
