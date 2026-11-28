import type React from "react";
import {
  AbsoluteFill,
  Easing,
  Interactive,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
  type InteractivitySchema,
} from "remotion";
import { FlowMediaSlot } from "../components/FlowMediaSlot";
import { SpeedLinesLayer } from "../components/SpeedLinesLayer";
import { FONT_MONO, FONT_SANS, PALETTE } from "../fonts";
import { ImpactShake } from "./impact-shake.element";
import { RadialBurst } from "./radial-burst.element";

type HookSceneProps = {
  readonly hookTitle: string;
  readonly burstTitle: string;
  readonly flowHookVideo?: string;
};

const HookSceneInner: React.FC<HookSceneProps> = ({
  hookTitle,
  burstTitle,
  flowHookVideo,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const burstEnter = spring({
    frame: Math.max(0, frame - 128),
    fps,
    config: { damping: 14, stiffness: 170 },
  });

  const phase1Opacity = interpolate(frame, [112, 134], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Rapid strobe kinetic pain words before burst
  const activeWord =
    frame < 36
      ? "100 KB/s 龟速？"
      : frame < 72
        ? "单连接必断线？"
        : "满屏广告开 VIP？";

  const wordColor =
    frame < 36 ? "#FFFFFF" : frame < 72 ? "#F25D59" : "#FF9F2E";

  return (
    <>
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(circle at 50% 45%, rgba(242,93,89,0.16) 0%, rgba(12,13,18,1) 64%)",
        }}
      />

      {/* PHASE 1: Strobe Kinetic Pain Impact + Sculptural Radial Burst */}
      <AbsoluteFill style={{ opacity: phase1Opacity }}>
        {frame < 95 && (
          <ImpactShake
            from={0}
            durationInFrames={95}
            name="Pain Impact Shake"
            backgroundColor="transparent"
            intensity={1.15}
            speed={1.2}
          >
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                textAlign: "center",
                gap: 20,
                padding: "0 100px",
              }}
            >
              <span
                style={{
                  fontFamily: FONT_MONO,
                  fontSize: 30,
                  fontWeight: 700,
                  color: "#A1A1AA",
                  letterSpacing: "0.14em",
                }}
              >
                {hookTitle}
              </span>
              <span
                style={{
                  fontFamily: FONT_SANS,
                  fontSize: 120,
                  fontWeight: 900,
                  color: wordColor,
                  letterSpacing: "-0.04em",
                  whiteSpace: "nowrap",
                  textShadow: "0 12px 40px rgba(0,0,0,0.65)",
                }}
              >
                {activeWord}
              </span>
            </div>
          </ImpactShake>
        )}

        <RadialBurst
          from={72}
          durationInFrames={90}
          name="Transition Burst"
          backgroundColor="transparent"
          color={PALETTE.pink}
          accentColor={PALETTE.blue}
          segments={10}
          speed={1.7}
          style={{ position: "absolute", inset: 0 }}
        />
      </AbsoluteFill>

      {/* PHASE 2: 3D Fox Speed Breakthrough (Flow Video Slot starts cleanly at local 0s) */}
      {frame >= 122 && (
        <AbsoluteFill style={{ opacity: burstEnter }}>
          <Sequence from={122} durationInFrames={135}>
            <FlowMediaSlot
              videoFile={flowHookVideo}
              fallbackImageFile="assets/fox-speed-dark.jpg"
              playbackRate={1.15}
              style={{
                scale: `${interpolate(frame, [122, 255], [1.1, 1.0], {
                  extrapolateLeft: "clamp",
                  extrapolateRight: "clamp",
                  easing: Easing.bezier(0.23, 1, 0.32, 1),
                })}`,
              }}
            />
          </Sequence>
          <AbsoluteFill
            style={{
              background:
                "linear-gradient(95deg, rgba(12,13,18,0.92) 0%, rgba(12,13,18,0.45) 45%, rgba(12,13,18,0.16) 100%)",
            }}
          />
          <SpeedLinesLayer color={PALETTE.pink} opacityMax={0.26} />

          <div
            style={{
              position: "absolute",
              left: 108,
              top: 0,
              bottom: 0,
              width: 640,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center",
              gap: 24,
            }}
          >
            <div
              style={{
                display: "inline-flex",
                alignSelf: "flex-start",
                alignItems: "center",
                gap: 10,
                padding: "10px 22px",
                borderRadius: 999,
                backgroundColor: "rgba(251, 114, 153, 0.18)",
                border: "1.5px solid rgba(251, 114, 153, 0.6)",
                fontFamily: FONT_MONO,
                fontSize: 22,
                fontWeight: 700,
                color: PALETTE.pink,
              }}
            >
              ⚡ 64-THREAD BURST · ZERO ADS
            </div>

            <Interactive.Div
              name="Breakthrough Headline"
              style={{
                fontFamily: FONT_SANS,
                fontSize: 88,
                fontWeight: 900,
                color: "#FFFFFF",
                lineHeight: 1.12,
                letterSpacing: "-0.03em",
                whiteSpace: "pre-line",
                translate: interpolate(frame, [130, 158], ["-60px 0px", "0px 0px"], {
                  extrapolateLeft: "clamp",
                  extrapolateRight: "clamp",
                  easing: Easing.bezier(0.23, 1, 0.32, 1),
                }),
                opacity: interpolate(frame, [130, 150], [0, 1], {
                  extrapolateLeft: "clamp",
                  extrapolateRight: "clamp",
                }),
              }}
            >
              {burstTitle}
            </Interactive.Div>

            <span
              style={{
                fontFamily: FONT_SANS,
                fontSize: 34,
                fontWeight: 600,
                color: "#D4D4D8",
              }}
            >
              64 路并发满速直连 · 完全开源免费
            </span>
          </div>
        </AbsoluteFill>
      )}
    </>
  );
};

const hookSceneSchema = {
  ...Interactive.backgroundSchema,
  hookTitle: { type: "string", default: "B站存 4K 番剧 / 百集课程？", description: "Hook Headline" },
  burstTitle: { type: "string", default: "别忍了，\n直接满速破局！", description: "Burst Headline" },
  flowHookVideo: { type: "string", default: "", description: "Optional Flow Hook MP4" },
} as const satisfies InteractivitySchema;

export const HookScene = Interactive.create({
  Component: HookSceneInner,
  layout: "absolute-fill",
  schema: hookSceneSchema,
});
