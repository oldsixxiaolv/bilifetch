import type React from "react";
import { AbsoluteFill, Img, Interactive, staticFile, type InteractivitySchema } from "remotion";
import { FoxLogo } from "./components/FoxLogo";
import { FONT_MONO, FONT_SANS, PALETTE } from "./fonts";

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
  return (
    <AbsoluteFill style={{ backgroundColor: "#111216" }}>
      {/* Background: 3D Fox Speed Burst */}
      <Img
        src={staticFile("assets/fox-speed-dark.jpg")}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          opacity: 0.92,
        }}
      />
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(95deg, rgba(17,18,22,0.95) 0%, rgba(17,18,22,0.72) 48%, rgba(17,18,22,0.28) 100%)",
        }}
      />

      {/* Left Viral Typography Block */}
      <div
        style={{
          position: "absolute",
          left: 84,
          top: 84,
          bottom: 84,
          width: 780,
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
          <FoxLogo name="Cover Fox Logo" size={96} borderRadius={24} />
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span
              style={{
                fontFamily: FONT_SANS,
                fontSize: 46,
                fontWeight: 900,
                color: "#FFFFFF",
              }}
            >
              BiliFetch v1.2.0
            </span>
            <span
              style={{
                fontFamily: FONT_MONO,
                fontSize: 24,
                fontWeight: 700,
                color: PALETTE.pink,
              }}
            >
              {badge}
            </span>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          <Interactive.Div
            name="Cover Main Title"
            style={{
              fontFamily: FONT_SANS,
              fontSize: 88,
              fontWeight: 900,
              color: "#FFFFFF",
              lineHeight: 1.15,
              letterSpacing: "-0.03em",
              whiteSpace: "pre-line",
              textShadow: "0 10px 30px rgba(0,0,0,0.65)",
            }}
          >
            {mainTitle}
          </Interactive.Div>

          <div
            style={{
              display: "inline-flex",
              alignSelf: "flex-start",
              padding: "14px 28px",
              borderRadius: 18,
              background: "linear-gradient(90deg, #FB7299, #00AEEC)",
              fontFamily: FONT_SANS,
              fontSize: 34,
              fontWeight: 800,
              color: "#FFFFFF",
              boxShadow: "0 14px 34px rgba(251,114,153,0.4)",
            }}
          >
            {subTitle}
          </div>
        </div>

        <div style={{ display: "flex", gap: 16 }}>
          {["macOS", "Windows", "Linux", "零广告开源"].map((t) => (
            <span
              key={t}
              style={{
                fontFamily: FONT_SANS,
                fontSize: 26,
                fontWeight: 700,
                color: "#F4F4F5",
                padding: "10px 22px",
                borderRadius: 14,
                backgroundColor: "rgba(255,255,255,0.1)",
                border: "1px solid rgba(255,255,255,0.22)",
              }}
            >
              {t}
            </span>
          ))}
        </div>
      </div>

      {/* Right Floating App UI Preview */}
      <div
        style={{
          position: "absolute",
          right: 54,
          bottom: 72,
          width: 660,
          height: 515,
          borderRadius: 24,
          padding: 12,
          backgroundColor: "rgba(255,255,255,0.96)",
          border: "2px solid rgba(251,114,153,0.8)",
          boxShadow: "0 30px 90px rgba(0,0,0,0.7)",
          rotate: "-2deg",
        }}
      >
        <Img
          src={staticFile("assets/screenshot.png")}
          style={{ width: "100%", height: "100%", objectFit: "contain", borderRadius: 16 }}
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
