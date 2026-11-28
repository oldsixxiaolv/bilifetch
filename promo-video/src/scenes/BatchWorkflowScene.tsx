import type React from "react";
import {
  AbsoluteFill,
  Easing,
  Img,
  Interactive,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  type InteractivitySchema,
} from "remotion";
import { KeycapPill } from "../components/KeycapPill";
import { FONT_MONO, FONT_SANS, FONT_SERIF, PALETTE } from "../fonts";

type BatchWorkflowSceneProps = {
  readonly title: string;
  readonly darkTitle: string;
};

const BatchWorkflowSceneInner: React.FC<BatchWorkflowSceneProps> = ({
  title,
  darkTitle,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Radial iris wipe expanding out of the Moon button area (84% 16%) at frame 232!
  const irisRadius = interpolate(frame, [232, 286], [0, 150], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.77, 0, 0.175, 1),
  });

  const stageEnter = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 150 },
  });

  const qrEnter = spring({
    frame: Math.max(0, frame - 300),
    fps,
    config: { damping: 16, stiffness: 180 },
  });

  const tiltY = interpolate(frame, [0, 120, 232, 495], [8, 0, 0, -4], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.23, 1, 0.32, 1),
  });

  const isDark = frame >= 256;

  return (
    <>
      {/* LIGHT BASE LAYER */}
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(circle at 80% 20%, rgba(251,114,153,0.12) 0%, rgba(250,249,246,1) 60%)",
        }}
      />

      {/* DARK IRIS MORPH LAYER */}
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(circle at 84% 18%, rgba(0,174,236,0.14) 0%, rgba(17,18,22,1) 62%)",
          clipPath: `circle(${irisRadius}% at 84% 18%)`,
        }}
      />

      {/* Top Left Editorial Title Overlay */}
      <div
        style={{
          position: "absolute",
          left: 108,
          top: 72,
          right: 108,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          zIndex: 4,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <span
            style={{
              fontFamily: FONT_MONO,
              fontSize: 21,
              fontWeight: 700,
              color: PALETTE.pink,
              letterSpacing: "0.08em",
            }}
          >
            {isDark ? "02 / GRAPHITE DARK MODE & 4K LOGIN" : "01 / BATCH EPISODE PICKER"}
          </span>
          <Interactive.Div
            name="Batch Section Title"
            style={{
              fontFamily: FONT_SERIF,
              fontSize: 60,
              fontWeight: 700,
              lineHeight: 1.16,
              color: isDark ? "#FFFFFF" : PALETTE.ink,
              whiteSpace: "pre-line",
            }}
          >
            {isDark ? darkTitle : title}
          </Interactive.Div>
        </div>

        {/* Floating Clean Feature Pills (replaces heavy bullet cards) */}
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", maxWidth: 680, justifyContent: "flex-end" }}>
          {[
            "正片 / PV 智能分流",
            "自动补齐 第01集 防覆盖",
            "收藏夹自动剔除失效稿件",
            "一键只下 .m4a 音频",
          ].map((tag) => (
            <span
              key={tag}
              style={{
                fontFamily: FONT_SANS,
                fontSize: 22,
                fontWeight: 700,
                color: isDark ? "#E4E4E7" : PALETTE.ink,
                backgroundColor: isDark ? "rgba(31,32,38,0.88)" : "rgba(255,255,255,0.94)",
                border: `1.5px solid ${isDark ? "#343642" : "#E5E2DC"}`,
                padding: "10px 18px",
                borderRadius: 999,
                boxShadow: "0 8px 24px rgba(0,0,0,0.08)",
              }}
            >
              ✓ {tag}
            </span>
          ))}
        </div>
      </div>

      {/* Main 3D Stage Showcase */}
      <AbsoluteFill
        style={{
          justifyContent: "flex-end",
          alignItems: "center",
          paddingBottom: 112,
          perspective: "1800px",
        }}
      >
        <div
          style={{
            position: "relative",
            width: 1180,
            height: 610,
            borderRadius: 28,
            overflow: "hidden",
            opacity: stageEnter,
            transform: `translateY(${(1 - stageEnter) * 60}px) scale(${0.92 + 0.08 * stageEnter}) rotateY(${tiltY}deg)`,
            boxShadow: isDark
              ? "0 36px 100px rgba(0,0,0,0.72)"
              : "0 32px 90px rgba(22,22,21,0.16)",
            border: `1.5px solid ${isDark ? "#32343D" : "#E3E0D8"}`,
            backgroundColor: isDark ? "#181818" : "#FFFFFF",
          }}
        >
          <Img
            src={staticFile("assets/screenshot-batch.png")}
            style={{
              position: "absolute",
              inset: 0,
              width: "100%",
              height: "100%",
              objectFit: "contain",
              padding: 14,
            }}
          />

          <div
            style={{
              position: "absolute",
              inset: 0,
              backgroundColor: "#181818",
              clipPath: `circle(${irisRadius}% at 88% 12%)`,
            }}
          >
            <Img
              src={staticFile("assets/screenshot-batch-dark.png")}
              style={{
                width: "100%",
                height: "100%",
                objectFit: "contain",
                padding: 14,
              }}
            />
          </div>
        </div>
      </AbsoluteFill>

      {/* Bottom Left Tactile Keyboard Shortcuts */}
      <div
        style={{
          position: "absolute",
          left: 108,
          bottom: 26,
          display: "flex",
          gap: 16,
          zIndex: 5,
        }}
      >
        <KeycapPill keys={["⌘", "F"]} label="秒搜标题" pressAt={62} dark={isDark} />
        <KeycapPill keys={["⇧", "Click"]} label="区间连选" pressAt={135} dark={isDark} />
      </div>

      {/* Floating QR Login Card in Dark Mode */}
      {frame >= 295 && (
        <div
          style={{
            position: "absolute",
            right: 96,
            bottom: 84,
            width: 300,
            padding: 16,
            borderRadius: 24,
            backgroundColor: "#FFFFFF",
            border: "2px solid #FB7299",
            boxShadow: "0 26px 70px rgba(0,0,0,0.65)",
            opacity: qrEnter,
            scale: `${0.84 + 0.16 * qrEnter}`,
            translate: `0px ${(1 - qrEnter) * 44}px`,
            display: "flex",
            flexDirection: "column",
            gap: 10,
            alignItems: "center",
            zIndex: 6,
          }}
        >
          <Img
            src={staticFile("assets/screenshot-login.png")}
            style={{ width: "100%", height: 240, objectFit: "contain", borderRadius: 14 }}
          />
          <span
            style={{
              fontFamily: FONT_SANS,
              fontSize: 21,
              fontWeight: 800,
              color: PALETTE.ink,
            }}
          >
            手机扫码 · 解锁 4K / 杜比
          </span>
        </div>
      )}
    </>
  );
};

const batchWorkflowSchema = {
  ...Interactive.backgroundSchema,
  title: {
    type: "string",
    default: "整季番剧与百集合集\n一屏勾选批量拉满",
    description: "Light Phase Title",
  },
  darkTitle: {
    type: "string",
    default: "深色外观护眼直切\n扫码解锁 4K 原画",
    description: "Dark Phase Title",
  },
} as const satisfies InteractivitySchema;

export const BatchWorkflowScene = Interactive.create({
  Component: BatchWorkflowSceneInner,
  layout: "absolute-fill",
  schema: batchWorkflowSchema,
});
