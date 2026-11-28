import type React from "react";
import { AbsoluteFill, Img, Interactive, staticFile, type InteractivitySchema } from "remotion";
import { FoxLogo } from "./components/FoxLogo";
import { FONT_MONO, FONT_SANS } from "./fonts";

type BiliFetchCoverProps = {
  readonly mainTitle: string;
  readonly subTitle: string;
  readonly badge: string;
};

const BiliFetchCoverInner: React.FC<BiliFetchCoverProps> = ({
  mainTitle,
  subTitle,
  badge,
}) => {
  const titleLines = mainTitle.split("\n");
  const line1 = titleLines[0] ?? mainTitle;
  const line2 = titleLines[1] ?? "";

  return (
    <AbsoluteFill style={{ backgroundColor: "#0D0E13" }}>
      {/* Background: Full-brightness Velvet Plush Fox on Neon Tracks */}
      <Img
        src={staticFile("assets/fox-speed-dark.jpg")}
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          objectFit: "cover",
          objectPosition: "75% 45%",
          transform: "scale(1.06)",
        }}
      />

      {/* Directional scrim on left only — keeps the cute plush fox 100% vivid */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(95deg, rgba(11,12,17,0.92) 0%, rgba(11,12,17,0.72) 38%, rgba(11,12,17,0.18) 62%, rgba(11,12,17,0.0) 100%)",
        }}
      />

      {/* Left High-Impact Bilibili Feed Typography Stack */}
      <div
        style={{
          position: "absolute",
          left: 56,
          top: 44,
          bottom: 44,
          width: 980,
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
        }}
      >
        {/* Top Brand + Speed Pill */}
        <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
          <FoxLogo name="Cover Fox Logo" size={96} borderRadius={22} />
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
              <span
                style={{
                  fontFamily: FONT_SANS,
                  fontSize: 52,
                  fontWeight: 900,
                  color: "#FFFFFF",
                  letterSpacing: "-0.02em",
                }}
              >
                BiliFetch
              </span>
              <span
                style={{
                  fontFamily: FONT_MONO,
                  fontSize: 28,
                  fontWeight: 800,
                  color: "#FFFFFF",
                  backgroundColor: "#FB7299",
                  padding: "4px 18px",
                  borderRadius: 999,
                }}
              >
                v1.2.0
              </span>
            </div>
            <span
              style={{
                fontFamily: FONT_MONO,
                fontSize: 28,
                fontWeight: 800,
                color: "#38D0FF",
                letterSpacing: "0.04em",
              }}
            >
              {badge}
            </span>
          </div>
        </div>

        {/* Giant Punchy Headline filling the left core */}
        <div style={{ display: "flex", flexDirection: "column", gap: 26 }}>
          <Interactive.Div
            name="Cover Main Title"
            style={{
              display: "flex",
              flexDirection: "column",
              fontFamily: FONT_SANS,
              fontSize: 146,
              fontWeight: 900,
              lineHeight: 1.08,
              letterSpacing: "-0.04em",
              whiteSpace: "nowrap",
              textShadow: "0 12px 34px rgba(0,0,0,0.92)",
            }}
          >
            <span style={{ color: "#FFFFFF" }}>{line1}</span>
            {line2 && (
              <span
                style={{
                  color: "#FFE14D",
                  textShadow: "0 12px 36px rgba(0,0,0,0.95), 0 0 38px rgba(255,225,77,0.28)",
                }}
              >
                {line2}
              </span>
            )}
          </Interactive.Div>

          <div
            style={{
              display: "inline-flex",
              alignSelf: "flex-start",
              padding: "18px 38px",
              borderRadius: 22,
              background: "linear-gradient(90deg, #FB7299, #00AEEC)",
              fontFamily: FONT_SANS,
              fontSize: 46,
              fontWeight: 900,
              color: "#FFFFFF",
              letterSpacing: "0.01em",
              boxShadow: "0 18px 44px rgba(251,114,153,0.5)",
            }}
          >
            {subTitle}
          </div>
        </div>

        {/* Bottom Platform Chips */}
        <div style={{ display: "flex", gap: 16 }}>
          {["macOS", "Windows", "Linux", "开源无广"].map((t) => (
            <span
              key={t}
              style={{
                fontFamily: FONT_SANS,
                fontSize: 30,
                fontWeight: 800,
                color: "#FFFFFF",
                padding: "12px 26px",
                borderRadius: 14,
                backgroundColor: "rgba(24,26,34,0.86)",
                border: "1.5px solid rgba(255,255,255,0.32)",
                backdropFilter: "blur(8px)",
              }}
            >
              {t}
            </span>
          ))}
        </div>
      </div>

      {/* Right-Bottom Floating App UI Preview (tucked below the plush fox's face) */}
      <div
        style={{
          position: "absolute",
          right: 42,
          bottom: 42,
          width: 610,
          height: 410,
          borderRadius: 22,
          padding: 10,
          backgroundColor: "rgba(255,255,255,0.97)",
          border: "2.5px solid rgba(251,114,153,0.9)",
          boxShadow: "0 28px 80px rgba(0,0,0,0.78)",
          rotate: "-2.5deg",
        }}
      >
        <Img
          src={staticFile("assets/screenshot.png")}
          style={{ width: "100%", height: "100%", objectFit: "contain", borderRadius: 14 }}
        />
      </div>
    </AbsoluteFill>
  );
};

const coverSchema = {
  mainTitle: {
    type: "string",
    default: "B站 4K 番剧\n满速下载神器！",
    description: "Cover Main Headline",
  },
  subTitle: {
    type: "string",
    default: "64路并发 · 整季批量 · 开源无广告",
    description: "Cover Highlight Pill",
  },
  badge: {
    type: "string",
    default: "OPEN SOURCE · 28.6 MB/s",
    description: "Top Badge",
  },
} as const satisfies InteractivitySchema;

export const BiliFetchCover = Interactive.create({
  Component: BiliFetchCoverInner,
  layout: "absolute-fill",
  schema: coverSchema,
});
