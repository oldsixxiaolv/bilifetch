import type React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_SANS } from "../fonts";

type DanmakuItem = {
  readonly text: string;
  readonly startFrame: number;
  readonly row: number;
  readonly color: string;
  readonly speed: number;
};

const DANMAKU_ITEMS: readonly DanmakuItem[] = [
  { text: "64路并发直接拉满太爽了！！", startFrame: 195, row: 0, color: "#FB7299", speed: 6.8 },
  { text: "开源零广告泪目 😭", startFrame: 560, row: 0, color: "#FFFFFF", speed: 6.4 },
  { text: "整季番剧不用一集集复制了", startFrame: 690, row: 0, color: "#00AEEC", speed: 6.2 },
  { text: "这暗黑模式也太丝滑了", startFrame: 890, row: 0, color: "#FFFFFF", speed: 6.0 },
  { text: "自动测速绕过慢CDN真懂痛点", startFrame: 1120, row: 0, color: "#FB7299", speed: 6.5 },
  { text: "断点秒恢复还不归零 nb!", startFrame: 1340, row: 0, color: "#00AEEC", speed: 6.1 },
  { text: "Mac/Win/Linux 全平台都有！", startFrame: 1610, row: 0, color: "#FFFFFF", speed: 6.0 },
  { text: "已三连 + GitHub Star ⭐", startFrame: 1900, row: 0, color: "#FB7299", speed: 5.7 },
];

type DanmakuLayerProps = {
  readonly enabled?: boolean;
};

export const DanmakuLayer: React.FC<DanmakuLayerProps> = ({ enabled = true }) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();

  if (!enabled) return null;

  return (
    <AbsoluteFill style={{ pointerEvents: "none", overflow: "hidden" }}>
      {DANMAKU_ITEMS.map((item) => {
        const local = frame - item.startFrame;
        if (local < 0 || local > 420) return null;
        const x = width + 40 - local * item.speed;
        const y = 8 + item.row * 34;
        const opacity = interpolate(local, [0, 20, 320, 380], [0, 0.84, 0.84, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });

        return (
          <div
            key={`${item.startFrame}-${item.text}`}
            style={{
              position: "absolute",
              left: 0,
              top: y,
              translate: `${x}px 0px`,
              opacity,
              padding: "4px 14px",
              borderRadius: 999,
              backgroundColor: "rgba(18, 19, 24, 0.62)",
              border: "1px solid rgba(255,255,255,0.16)",
              backdropFilter: "blur(6px)",
              fontFamily: FONT_SANS,
              fontSize: 18,
              fontWeight: 700,
              color: item.color,
              whiteSpace: "nowrap",
              textShadow: "0 2px 6px rgba(0,0,0,0.45)",
            }}
          >
            {item.text}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};
