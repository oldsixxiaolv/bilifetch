import type React from "react";
import { Video } from "@remotion/media";
import { Img, staticFile } from "remotion";

type FlowMediaSlotProps = {
  readonly videoFile?: string;
  readonly fallbackImageFile: string;
  readonly style?: React.CSSProperties;
  readonly playbackRate?: number;
};

/**
 * Renders an animated Google Flow video clip when provided,
 * falling back cleanly to the matched 3D keyframe still.
 */
export const FlowMediaSlot: React.FC<FlowMediaSlotProps> = ({
  videoFile,
  fallbackImageFile,
  style,
  playbackRate = 1,
}) => {
  if (videoFile) {
    return (
      <Video
        src={staticFile(videoFile)}
        muted
        loop
        objectFit="cover"
        playbackRate={playbackRate}
        style={{
          width: "100%",
          height: "100%",
          ...style,
        }}
      />
    );
  }

  return (
    <Img
      src={staticFile(fallbackImageFile)}
      style={{
        width: "100%",
        height: "100%",
        objectFit: "cover",
        ...style,
      }}
    />
  );
};
