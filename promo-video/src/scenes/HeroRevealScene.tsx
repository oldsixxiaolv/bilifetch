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
import { BiliFetchWindowLive } from "../components/BiliFetchWindowLive";
import { CursorOverlay, type CursorWaypoint } from "../components/CursorOverlay";
import { FoxLogo } from "../components/FoxLogo";
import { FONT_MONO, FONT_SANS, FONT_SERIF, PALETTE } from "../fonts";

type HeroRevealSceneProps = {
  readonly headline: string;
  readonly demoUrl: string;
};

// Coordinates aligned to the 3D-zoomed stage around frames 60..220
const CURSOR_PATH: readonly CursorWaypoint[] = [
  { frame: 55, x: 1380, y: 810 },
  { frame: 95, x: 700, y: 430, click: true },
  { frame: 185, x: 1494, y: 430, click: true },
  { frame: 265, x: 1196, y: 637 },
];

const HeroRevealSceneInner: React.FC<HeroRevealSceneProps> = ({
  headline,
  demoUrl,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const headerEnter = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 200 },
  });

  // Apple-keynote 3-beat camera choreography over the live interactive app UI:
  // Beat 1 (0..65): 3D tilted hero entry -> flat
  // Beat 2 (65..195): Macro zoom into URL input + Parse button
  // Beat 3 (195..310): Smooth glide down onto live 64-thread Queue Row 3
  // Beat 4 (310..375): Pull back to clean full product frame
  const camScale = interpolate(
    frame,
    [0, 50, 85, 185, 225, 315, 355],
    [0.84, 0.9, 1.32, 1.32, 1.18, 1.18, 0.92],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.bezier(0.42, 0, 0.58, 1),
    },
  );

  const camX = interpolate(
    frame,
    [0, 50, 85, 185, 225, 315, 355],
    [0, 0, 40, -60, 0, 0, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.bezier(0.42, 0, 0.58, 1),
    },
  );

  const camY = interpolate(
    frame,
    [0, 50, 85, 185, 225, 315, 355],
    [130, 110, 260, 260, -45, -45, 105],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.bezier(0.42, 0, 0.58, 1),
    },
  );

  const tiltX = interpolate(frame, [0, 48, 85, 315, 355], [14, 4, 0, 0, 5], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.23, 1, 0.32, 1),
  });
  const tiltY = interpolate(frame, [0, 48, 85, 315, 355], [-8, -2, 0, 0, 3], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.23, 1, 0.32, 1),
  });

  const headerOpacity = interpolate(frame, [0, 20, 70, 95, 315, 345], [0, 1, 1, 0.14, 0.14, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <>
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(circle at 75% 18%, rgba(251,114,153,0.14) 0%, rgba(250,249,246,1) 56%)",
        }}
      />

      {/* Editorial Header (dims cleanly during macro camera focus) */}
      <div
        style={{
          position: "absolute",
          left: 108,
          right: 108,
          top: 66,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          opacity: headerEnter * headerOpacity,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <FoxLogo name="Hero Fox Logo" size={76} borderRadius={20} />
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <span
                style={{
                  fontFamily: FONT_SANS,
                  fontSize: 40,
                  fontWeight: 900,
                  color: PALETTE.ink,
                }}
              >
                BiliFetch
              </span>
              <span
                style={{
                  fontFamily: FONT_MONO,
                  fontSize: 20,
                  fontWeight: 700,
                  color: PALETTE.pinkDark,
                  backgroundColor: PALETTE.pinkSoft,
                  padding: "4px 12px",
                  borderRadius: 999,
                }}
              >
                v1.2.0
              </span>
            </div>
            <span style={{ fontFamily: FONT_MONO, fontSize: 18, color: PALETTE.ink2 }}>
              64 路并发 · 整季番剧 · 开源无广告
            </span>
          </div>
        </div>

        <Interactive.Div
          name="Hero Main Headline"
          style={{
            fontFamily: FONT_SERIF,
            fontSize: 52,
            fontWeight: 700,
            color: PALETTE.ink,
            textAlign: "right",
            lineHeight: 1.2,
            whiteSpace: "pre-line",
          }}
        >
          {headline}
        </Interactive.Div>
      </div>

      {/* 3D Perspective Camera Stage */}
      <AbsoluteFill
        style={{
          justifyContent: "center",
          alignItems: "center",
          perspective: "1800px",
        }}
      >
        <div
          style={{
            transform: `translate3d(${camX}px, ${camY}px, 0px) scale(${camScale}) rotateX(${tiltX}deg) rotateY(${tiltY}deg)`,
            transformStyle: "preserve-3d",
          }}
        >
          <BiliFetchWindowLive
            demoUrl={demoUrl}
            typingStartFrame={98}
            typingEndFrame={158}
            parseClickFrame={185}
            downloadStartFrame={205}
          />
        </div>
      </AbsoluteFill>

      {/* Bottom Floating Live Caption Bar during Macro Tour */}
      <div
        style={{
          position: "absolute",
          left: "50%",
          bottom: 42,
          translate: "-50% 0px",
          padding: "12px 28px",
          borderRadius: 999,
          backgroundColor: "rgba(22, 22, 21, 0.88)",
          backdropFilter: "blur(10px)",
          color: "#FFFFFF",
          fontFamily: FONT_SANS,
          fontSize: 25,
          fontWeight: 700,
          boxShadow: "0 16px 40px rgba(0,0,0,0.22)",
          opacity: interpolate(frame, [75, 92, 335, 360], [0, 1, 1, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        {frame < 195
          ? "粘贴链接自动识别「番剧 / 剧集」· 一键解析整季"
          : "64 路并发拉满 28.6 MB/s · FFmpeg 零重编码极速成片"}
      </div>

      {frame < 260 && <CursorOverlay waypoints={CURSOR_PATH} size={42} />}
    </>
  );
};

const heroRevealSchema = {
  ...Interactive.backgroundSchema,
  headline: {
    type: "string",
    default: "安静、满速地保存\nB 站视频与整季番剧",
    description: "Hero Headline",
  },
  demoUrl: {
    type: "string",
    default: "https://www.bilibili.com/bangumi/play/ep1633643",
    description: "Demo Bilibili URL",
  },
} as const satisfies InteractivitySchema;

export const HeroRevealScene = Interactive.create({
  Component: HeroRevealSceneInner,
  layout: "absolute-fill",
  schema: heroRevealSchema,
});
