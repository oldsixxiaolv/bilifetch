import type React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";

export type CursorWaypoint = {
  readonly frame: number;
  readonly x: number;
  readonly y: number;
  readonly click?: boolean;
};

type CursorOverlayProps = {
  readonly waypoints: readonly CursorWaypoint[];
  readonly size?: number;
  readonly accentColor?: string;
};

export const CursorOverlay: React.FC<CursorOverlayProps> = ({
  waypoints,
  size = 38,
  accentColor = "#FB7299",
}) => {
  const frame = useCurrentFrame();
  if (waypoints.length === 0) return null;

  const first = waypoints[0];
  let x = first.x;
  let y = first.y;
  let pressScale = 1;

  for (let i = 0; i < waypoints.length - 1; i++) {
    const a = waypoints[i];
    const b = waypoints[i + 1];
    if (frame >= a.frame && frame <= b.frame) {
      const dur = Math.max(1, b.frame - a.frame);
      const t = interpolate(frame, [a.frame, b.frame], [0, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.bezier(0.23, 1, 0.32, 1),
      });
      x = a.x + (b.x - a.x) * t;
      y = a.y + (b.y - a.y) * t;
      if (dur > 2 && b.click && frame >= b.frame - 6) {
        pressScale = interpolate(frame, [b.frame - 6, b.frame], [1, 0.86], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
      }
      break;
    } else if (frame > b.frame) {
      x = b.x;
      y = b.y;
    }
  }

  // Click rebound & ripple rings
  const activeClicks = waypoints.filter(
    (wp) => wp.click && frame >= wp.frame && frame <= wp.frame + 28,
  );

  for (const wp of activeClicks) {
    if (frame >= wp.frame && frame <= wp.frame + 10) {
      pressScale = interpolate(frame, [wp.frame, wp.frame + 4, wp.frame + 10], [0.84, 1.05, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
    }
  }

  const opacity = interpolate(frame, [first.frame, first.frame + 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        opacity,
      }}
    >
      {activeClicks.map((wp, idx) => {
        const local = frame - wp.frame;
        const rSize = interpolate(local, [0, 26], [10, 76], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.bezier(0.23, 1, 0.32, 1),
        });
        const rOpacity = interpolate(local, [0, 26], [0.85, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        return (
          <div
            key={`${wp.frame}-${idx}`}
            style={{
              position: "absolute",
              left: wp.x - rSize / 2,
              top: wp.y - rSize / 2,
              width: rSize,
              height: rSize,
              borderRadius: "50%",
              border: `3px solid ${accentColor}`,
              backgroundColor: "rgba(251, 114, 153, 0.14)",
              opacity: rOpacity,
            }}
          />
        );
      })}
      <div
        style={{
          position: "absolute",
          left: x,
          top: y,
          scale: `${pressScale}`,
          transformOrigin: "4px 4px",
          filter: "drop-shadow(0 6px 14px rgba(0,0,0,0.32))",
        }}
      >
        <svg width={size} height={size} viewBox="0 0 28 28" fill="none">
          <path
            d="M4.5 2.5L23.5 14.5L14.2 16.4L10.2 24.5L4.5 2.5Z"
            fill="#161615"
            stroke="#FFFFFF"
            strokeWidth="2.2"
            strokeLinejoin="round"
          />
        </svg>
      </div>
    </div>
  );
};
