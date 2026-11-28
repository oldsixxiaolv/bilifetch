import type React from "react";
import { Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FoxLogo } from "./FoxLogo";
import { FONT_MONO, FONT_SANS, PALETTE } from "../fonts";

type BiliFetchWindowLiveProps = {
  readonly demoUrl: string;
  readonly typingStartFrame: number;
  readonly typingEndFrame: number;
  readonly parseClickFrame: number;
  readonly downloadStartFrame: number;
};

export const BiliFetchWindowLive: React.FC<BiliFetchWindowLiveProps> = ({
  demoUrl,
  typingStartFrame,
  typingEndFrame,
  parseClickFrame,
  downloadStartFrame,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const typedCount = Math.floor(
    interpolate(frame, [typingStartFrame, typingEndFrame], [0, demoUrl.length], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }),
  );
  const shownUrl = demoUrl.slice(0, typedCount);

  const badgePop = spring({
    frame: Math.max(0, frame - (typingEndFrame - 4)),
    fps,
    config: { damping: 14, stiffness: 260 },
  });

  const isParsePressed = frame >= parseClickFrame && frame <= parseClickFrame + 10;

  // Live episode 3 progress & speed after parse click
  const dlProgress = interpolate(frame, [downloadStartFrame, downloadStartFrame + 125], [14, 100], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.23, 1, 0.32, 1),
  });
  const dlDone = dlProgress >= 99.9;

  const speedVal = dlDone
    ? 0
    : interpolate(
        frame,
        [downloadStartFrame, downloadStartFrame + 35, downloadStartFrame + 105, downloadStartFrame + 125],
        [4.2, 28.6, 26.4, 0],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
      );

  const ringCirc = 2 * Math.PI * 16;
  const ringOffset = ringCirc * (1 - dlProgress / 100);

  return (
    <div
      style={{
        width: 1120,
        height: 820,
        borderRadius: 22,
        backgroundColor: "#F6F7F8",
        border: "1.5px solid #DCDFE4",
        boxShadow:
          "0 40px 100px rgba(22, 22, 21, 0.16), 0 8px 24px rgba(22, 22, 21, 0.08)",
        display: "flex",
        flexDirection: "column",
        padding: "24px 28px",
        gap: 18,
        overflow: "hidden",
      }}
    >
      {/* Top Window Bar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <FoxLogo name="Mockup Fox" size={44} borderRadius={11} />
          <span
            style={{
              fontFamily: FONT_SANS,
              fontSize: 24,
              fontWeight: 800,
              color: "#18191C",
            }}
          >
            BiliFetch
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "5px 14px 5px 6px",
              borderRadius: 999,
              border: "1.5px solid #FB7299",
              backgroundColor: "#FFF0F4",
            }}
          >
            <div
              style={{
                width: 24,
                height: 24,
                borderRadius: 6,
                backgroundColor: "#FB7299",
                color: "#FFFFFF",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontFamily: FONT_SANS,
                fontSize: 13,
                fontWeight: 800,
              }}
            >
              H
            </div>
            <span style={{ fontFamily: FONT_SANS, fontSize: 15, fontWeight: 600, color: "#18191C" }}>
              Hello
            </span>
          </div>
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: 10,
              backgroundColor: "#FFFFFF",
              border: "1px solid #E3E5E7",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 16,
            }}
          >
            🌙
          </div>
        </div>
      </div>

      {/* Card 1: Input Card */}
      <div
        style={{
          backgroundColor: "#FFFFFF",
          borderRadius: 18,
          border: "1px solid #E6E8EB",
          padding: "18px 20px",
          display: "flex",
          flexDirection: "column",
          gap: 14,
          boxShadow: "0 4px 14px rgba(0,0,0,0.03)",
        }}
      >
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <div
            style={{
              flex: 1,
              height: 52,
              borderRadius: 12,
              backgroundColor: frame >= typingStartFrame ? "#FFFFFF" : "#F1F2F3",
              border: `2px solid ${frame >= typingStartFrame ? PALETTE.pink : "#E3E5E7"}`,
              padding: "0 16px",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <span style={{ fontFamily: FONT_MONO, fontSize: 17, color: "#18191C" }}>
              {shownUrl || "粘贴 B 站视频 / 番剧 / 收藏夹链接或 BV 号..."}
              {frame >= typingStartFrame && frame < parseClickFrame && (
                <span style={{ color: PALETTE.pink, opacity: frame % 20 < 10 ? 1 : 0 }}>|</span>
              )}
            </span>
            {frame >= typingEndFrame - 4 && (
              <span
                style={{
                  fontFamily: FONT_SANS,
                  fontSize: 14,
                  fontWeight: 700,
                  color: "#D97706",
                  backgroundColor: "#FFF4E6",
                  padding: "4px 12px",
                  borderRadius: 8,
                  scale: `${badgePop}`,
                }}
              >
                番剧 / 剧集
              </span>
            )}
          </div>

          <div
            style={{
              height: 52,
              padding: "0 26px",
              borderRadius: 12,
              backgroundColor: isParsePressed ? PALETTE.pinkDark : PALETTE.pink,
              color: "#FFFFFF",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: FONT_SANS,
              fontSize: 18,
              fontWeight: 700,
              scale: `${isParsePressed ? 0.94 : 1}`,
              boxShadow: "0 6px 16px rgba(251, 114, 153, 0.35)",
            }}
          >
            🔍 解析
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontFamily: FONT_SANS, fontSize: 15, color: "#61666D" }}>保存到</span>
            <span
              style={{
                fontFamily: FONT_MONO,
                fontSize: 14,
                fontWeight: 600,
                color: "#18191C",
                backgroundColor: "#F1F2F3",
                padding: "6px 12px",
                borderRadius: 9,
              }}
            >
              📁 ~/Downloads/BiliFetch
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontFamily: FONT_SANS, fontSize: 15, color: "#61666D" }}>画质</span>
            <span
              style={{
                fontFamily: FONT_SANS,
                fontSize: 15,
                fontWeight: 700,
                color: "#18191C",
                backgroundColor: "#F1F2F3",
                padding: "6px 14px",
                borderRadius: 9,
              }}
            >
              4K 超清 · 最高画质 ▾
            </span>
          </div>
        </div>
      </div>

      {/* Card 2: Live Queue Card */}
      <div
        style={{
          flex: 1,
          backgroundColor: "#FFFFFF",
          borderRadius: 18,
          border: "1px solid #E6E8EB",
          padding: "18px 22px",
          display: "flex",
          flexDirection: "column",
          gap: 16,
          boxShadow: "0 4px 14px rgba(0,0,0,0.03)",
        }}
      >
        {/* Toolbar */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <div
              style={{
                display: "flex",
                backgroundColor: "#F1F2F3",
                padding: 4,
                borderRadius: 10,
                gap: 6,
              }}
            >
              <span
                style={{
                  fontFamily: FONT_SANS,
                  fontSize: 15,
                  fontWeight: 700,
                  color: "#18191C",
                  backgroundColor: "#FFFFFF",
                  padding: "5px 14px",
                  borderRadius: 8,
                }}
              >
                下载 <span style={{ color: PALETTE.pink }}>6</span>
              </span>
              <span
                style={{
                  fontFamily: FONT_SANS,
                  fontSize: 15,
                  color: "#61666D",
                  padding: "5px 14px",
                }}
              >
                日志
              </span>
            </div>
            <span style={{ fontFamily: FONT_MONO, fontSize: 15, color: "#61666D" }}>
              {dlDone ? "3 / 6 · 已满速完成" : `2 / 6 · ${speedVal.toFixed(1)} MB/s`}
            </span>
          </div>

          <div style={{ display: "flex", gap: 10 }}>
            <span
              style={{
                fontFamily: FONT_SANS,
                fontSize: 15,
                fontWeight: 700,
                color: "#FFFFFF",
                backgroundColor: PALETTE.pink,
                padding: "7px 16px",
                borderRadius: 9,
              }}
            >
              ▶ 全部开始
            </span>
            <span
              style={{
                fontFamily: FONT_SANS,
                fontSize: 15,
                fontWeight: 600,
                color: "#18191C",
                backgroundColor: "#F1F2F3",
                padding: "7px 16px",
                borderRadius: 9,
              }}
            >
              ⏸ 全部暂停
            </span>
          </div>
        </div>

        {/* Completed Row 1 */}
        <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "8px 0", borderBottom: "1px solid #F1F2F3" }}>
          <div
            style={{
              width: 38,
              height: 38,
              borderRadius: 10,
              backgroundColor: "#E9F8F0",
              color: PALETTE.green,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 18,
              fontWeight: 800,
            }}
          >
            ✓
          </div>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 3 }}>
            <span style={{ fontFamily: FONT_SANS, fontSize: 17, fontWeight: 700, color: "#18191C" }}>
              第01集 末世桃源
            </span>
            <span style={{ fontFamily: FONT_MONO, fontSize: 14, color: "#8A9099" }}>
              4K 超清 · 512.0 MB · ~/Downloads/BiliFetch/第01集 末世桃源.mp4
            </span>
          </div>
          <span style={{ fontFamily: FONT_SANS, fontSize: 15, fontWeight: 700, color: PALETTE.green }}>
            已完成
          </span>
        </div>

        {/* Completed Row 2 */}
        <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "8px 0", borderBottom: "1px solid #F1F2F3" }}>
          <div
            style={{
              width: 38,
              height: 38,
              borderRadius: 10,
              backgroundColor: "#E9F8F0",
              color: PALETTE.green,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 18,
              fontWeight: 800,
            }}
          >
            ✓
          </div>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 3 }}>
            <span style={{ fontFamily: FONT_SANS, fontSize: 17, fontWeight: 700, color: "#18191C" }}>
              第02集 波澜初起
            </span>
            <span style={{ fontFamily: FONT_MONO, fontSize: 14, color: "#8A9099" }}>
              4K 超清 · 512.0 MB · ~/Downloads/BiliFetch/第02集 波澜初起.mp4
            </span>
          </div>
          <span style={{ fontFamily: FONT_SANS, fontSize: 15, fontWeight: 700, color: PALETTE.green }}>
            已完成
          </span>
        </div>

        {/* Hero Active Row 3 */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 16,
            padding: "14px 16px",
            borderRadius: 14,
            backgroundColor: dlDone ? "#F4FBF7" : "#F5FBFF",
            border: `1.5px solid ${dlDone ? "rgba(43,182,115,0.4)" : "rgba(0,174,236,0.35)"}`,
          }}
        >
          {dlDone ? (
            <div
              style={{
                width: 40,
                height: 40,
                borderRadius: 10,
                backgroundColor: "#E9F8F0",
                color: PALETTE.green,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 20,
                fontWeight: 800,
              }}
            >
              ✓
            </div>
          ) : (
            <div style={{ position: "relative", width: 40, height: 40 }}>
              <svg width={40} height={40} viewBox="0 0 40 40">
                <circle cx="20" cy="20" r="16" stroke="#E3E5E7" strokeWidth="3.5" fill="none" />
                <circle
                  cx="20"
                  cy="20"
                  r="16"
                  stroke={PALETTE.blue}
                  strokeWidth="3.5"
                  fill="none"
                  strokeDasharray={ringCirc}
                  strokeDashoffset={ringOffset}
                  strokeLinecap="round"
                  transform="rotate(-90 20 20)"
                />
              </svg>
              <span
                style={{
                  position: "absolute",
                  inset: 0,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontFamily: FONT_MONO,
                  fontSize: 12,
                  fontWeight: 700,
                  color: "#18191C",
                }}
              >
                {Math.round(dlProgress)}
              </span>
            </div>
          )}

          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontFamily: FONT_SANS, fontSize: 18, fontWeight: 800, color: "#18191C" }}>
                第03集 长夜（4K 修复版）
              </span>
              <span
                style={{
                  fontFamily: FONT_MONO,
                  fontSize: 17,
                  fontWeight: 800,
                  color: dlDone ? PALETTE.green : PALETTE.blue,
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {dlDone ? "已完成 · ffmpeg -c copy" : `${speedVal.toFixed(1)} MB/s`}
              </span>
            </div>

            <div
              style={{
                height: 8,
                borderRadius: 999,
                backgroundColor: "#E5E7EB",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  height: "100%",
                  width: `${dlProgress}%`,
                  borderRadius: 999,
                  background: dlDone
                    ? PALETTE.green
                    : "linear-gradient(90deg, #FB7299, #00AEEC)",
                }}
              />
            </div>

            <span style={{ fontFamily: FONT_MONO, fontSize: 14, color: "#61666D" }}>
              64 路 TLS 并发 · 4K 超清 · {((498.0 * dlProgress) / 100).toFixed(1)} MB / 498.0 MB
            </span>
          </div>
        </div>

        {/* Row 4 */}
        <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "8px 0", opacity: 0.72 }}>
          <div
            style={{
              width: 38,
              height: 38,
              borderRadius: 10,
              backgroundColor: "#FFF4E6",
              color: PALETTE.orange,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 16,
              fontWeight: 800,
            }}
          >
            ⏸
          </div>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontFamily: FONT_SANS, fontSize: 17, fontWeight: 700, color: "#18191C" }}>
              第04集 雷云
            </span>
            <span style={{ fontFamily: FONT_MONO, fontSize: 14, color: "#8A9099" }}>
              已暂停 · .part.state 字节锁定 168.0 MB / 400.0 MB
            </span>
          </div>
          <span style={{ fontFamily: FONT_SANS, fontSize: 15, fontWeight: 700, color: PALETTE.orange }}>
            秒恢复
          </span>
        </div>
      </div>
    </div>
  );
};
