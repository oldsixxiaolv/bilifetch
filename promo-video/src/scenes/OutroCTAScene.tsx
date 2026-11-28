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
import { FoxLogo } from "../components/FoxLogo";
import { FONT_MONO, FONT_SANS, FONT_SERIF, PALETTE } from "../fonts";
import { RadialBurst } from "./radial-burst.element";

type OutroCTASceneProps = {
  readonly repoUrl: string;
  readonly ctaText: string;
  readonly flowOutroVideo?: string;
};

const SANLIAN = [
  { kind: "like", label: "点赞", sub: "让更多人看到", color: "#FB7299" },
  { kind: "coin", label: "投币", sub: "支持开源更新", color: "#00AEEC" },
  { kind: "star", label: "收藏", sub: "备着随时用", color: "#FF9F2E" },
] as const;

const SanlianGlyph: React.FC<{ readonly kind: "like" | "coin" | "star"; readonly color: string }> = ({
  kind,
  color,
}) => {
  if (kind === "like") {
    return (
      <svg width={48} height={48} viewBox="0 0 24 24" fill={color}>
        <path d="M9 21H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h4v11zm2-11.58L14.29 4.2a1.75 1.75 0 0 1 3.19 1.01v3.79h3.12a2 2 0 0 1 1.96 2.39l-1.36 7A2 2 0 0 1 19.24 20H11V9.42z" />
      </svg>
    );
  }
  if (kind === "coin") {
    return (
      <svg width={48} height={48} viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="10" fill={color} />
        <circle cx="12" cy="12" r="7.5" stroke="#191A22" strokeWidth="1.5" opacity={0.35} />
        <path
          d="M9 8h6M12 8v8M9.5 12h5"
          stroke="#191A22"
          strokeWidth="2.1"
          strokeLinecap="round"
        />
      </svg>
    );
  }
  return (
    <svg width={48} height={48} viewBox="0 0 24 24" fill={color}>
      <path d="M12 2.5l2.92 5.91 6.53.95-4.72 4.6 1.11 6.5L12 17.38l-5.84 3.08 1.11-6.5-4.72-4.6 6.53-.95L12 2.5z" />
    </svg>
  );
};

const OutroCTASceneInner: React.FC<OutroCTASceneProps> = ({
  repoUrl,
  ctaText,
  flowOutroVideo,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const logoIn = spring({
    frame,
    fps,
    config: { damping: 14, stiffness: 180 },
  });

  // Bilibili authentic long-press Sanlian ring charge (frames 32..118 -> pop at 120!)
  const holdProgress = interpolate(frame, [32, 118], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.35, 0, 0.25, 1),
  });
  const fired = frame >= 120;
  const popSpring = spring({
    frame: Math.max(0, frame - 120),
    fps,
    config: { damping: 10, stiffness: 240 },
  });

  const ringR = 54;
  const ringCirc = 2 * Math.PI * ringR;
  const ringOffset = ringCirc * (1 - holdProgress);

  // Subtle breathing aurora position
  const orbShift = Math.sin(frame * 0.04) * 24;

  return (
    <>
      <div style={{ position: "absolute", inset: 0, opacity: 1, pointerEvents: "none" }}>
        <FlowMediaSlot
          videoFile={flowOutroVideo}
          fallbackImageFile="assets/flow-outro-keyframe.jpg"
        />
      </div>

      {/* Left contrast scrim only so the waving velvet fox on the right stays vibrant */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(circle at ${28 + orbShift * 0.1}% 48%, rgba(251,114,153,0.14) 0%, rgba(12,13,18,0.45) 45%, rgba(12,13,18,0) 72%), linear-gradient(90deg, rgba(12,13,18,0.78) 0%, rgba(12,13,18,0.48) 46%, rgba(12,13,18,0.02) 70%, rgba(12,13,18,0) 100%)`,
        }}
      />

      {fired && (
        <div
          style={{
            position: "absolute",
            left: -380,
            top: 0,
            width: 1920,
            height: 1080,
            opacity: 0.28,
            pointerEvents: "none",
          }}
        >
          <RadialBurst
            from={120}
            durationInFrames={110}
            name="Sanlian Burst"
            backgroundColor="transparent"
            color={PALETTE.pink}
            accentColor={PALETTE.blue}
            segments={12}
            speed={1.3}
            style={{ position: "absolute", inset: 0 }}
          />
        </div>
      )}

      <AbsoluteFill
        style={{
          padding: "88px 108px",
          justifyContent: "center",
          alignItems: "flex-start",
        }}
      >
        <div
          style={{
            width: 900,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 30,
          }}
        >
          {/* Brand Lockup */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 26,
              opacity: logoIn,
              scale: `${0.84 + 0.16 * logoIn}`,
            }}
          >
            <FoxLogo name="Outro Fox Logo" size={108} borderRadius={26} />
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <span
                style={{
                  fontFamily: FONT_SANS,
                  fontSize: 72,
                  fontWeight: 900,
                  color: "#FFFFFF",
                  letterSpacing: "-0.03em",
                  lineHeight: 1.05,
                }}
              >
                BiliFetch
              </span>
              <span
                style={{
                  fontFamily: FONT_MONO,
                  fontSize: 23,
                  fontWeight: 700,
                  color: PALETTE.pink,
                }}
              >
                v1.2.0 · 跨平台 B 站 4K 下载神器
              </span>
            </div>
          </div>

          {/* GitHub Repo Pill */}
          <div
            style={{
              padding: "14px 32px",
              borderRadius: 999,
              backgroundColor: "rgba(25,26,34,0.92)",
              border: "2px solid rgba(251, 114, 153, 0.55)",
              boxShadow: "0 18px 50px rgba(251, 114, 153, 0.18)",
            }}
          >
            <span style={{ fontFamily: FONT_MONO, fontSize: 28, fontWeight: 700, color: "#FFFFFF" }}>
              {repoUrl}
            </span>
          </div>

          {/* Bilibili Long-Press Sanlian Rings */}
          <div style={{ display: "flex", gap: 44, marginTop: 8 }}>
            {SANLIAN.map((item) => {
              const cardScale = fired
                ? 1 + 0.14 * Math.sin(Math.min(1, popSpring) * Math.PI)
                : 0.96 + 0.04 * holdProgress;
              return (
                <div
                  key={item.label}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    gap: 14,
                    scale: `${cardScale}`,
                  }}
                >
                  <div
                    style={{
                      position: "relative",
                      width: 128,
                      height: 128,
                      borderRadius: "50%",
                      backgroundColor: fired ? "rgba(251,114,153,0.12)" : "#191A22",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      boxShadow: fired ? `0 0 40px ${item.color}55` : "0 14px 30px rgba(0,0,0,0.4)",
                    }}
                  >
                    <svg
                      width={128}
                      height={128}
                      viewBox="0 0 128 128"
                      style={{ position: "absolute", inset: 0 }}
                    >
                      <circle
                        cx="64"
                        cy="64"
                        r={ringR}
                        stroke="#2D303D"
                        strokeWidth="6"
                        fill="none"
                      />
                      <circle
                        cx="64"
                        cy="64"
                        r={ringR}
                        stroke={item.color}
                        strokeWidth="6"
                        fill="none"
                        strokeDasharray={ringCirc}
                        strokeDashoffset={ringOffset}
                        strokeLinecap="round"
                        transform="rotate(-90 64 64)"
                      />
                    </svg>
                    <SanlianGlyph kind={item.kind} color={fired || holdProgress > 0.05 ? item.color : "#8A8A98"} />
                  </div>

                  <span style={{ fontFamily: FONT_SANS, fontSize: 30, fontWeight: 800, color: item.color }}>
                    {item.label}
                  </span>
                  <span style={{ fontFamily: FONT_SANS, fontSize: 20, color: "#A1A1AA" }}>
                    {item.sub}
                  </span>
                </div>
              );
            })}
          </div>

          <Interactive.Div
            name="Outro CTA"
            style={{
              fontFamily: FONT_SERIF,
              fontSize: 35,
              fontWeight: 700,
              color: "#FFFFFF",
              marginTop: 4,
              textAlign: "center",
              opacity: interpolate(frame, [20, 48], [0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              }),
            }}
          >
            {fired ? ctaText : "长按点赞，一键触发开源三连 ⚡"}
          </Interactive.Div>
        </div>
      </AbsoluteFill>
    </>
  );
};

const outroSchema = {
  ...Interactive.backgroundSchema,
  repoUrl: {
    type: "string",
    default: "github.com/oldsixxiaolv/bilifetch",
    description: "GitHub Repository URL",
  },
  ctaText: {
    type: "string",
    default: "开源免费无广，欢迎一键三连！",
    description: "Closing Call To Action",
  },
  flowOutroVideo: {
    type: "string",
    default: "assets/flow-outro.mp4",
    description: "Optional Flow Outro MP4",
  },
} as const satisfies InteractivitySchema;

export const OutroCTAScene = Interactive.create({
  Component: OutroCTASceneInner,
  layout: "absolute-fill",
  schema: outroSchema,
});
