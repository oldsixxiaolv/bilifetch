import type React from "react";
import { Interactive, type InteractivitySchema } from "remotion";

type FoxLogoProps = {
  readonly size?: number;
  readonly tileColor?: string;
  readonly borderRadius?: number;
  readonly style?: React.CSSProperties;
};

const FoxLogoInner: React.FC<FoxLogoProps> = ({
  size = 120,
  tileColor = "#FFF1E6",
  borderRadius = 26,
  style,
}) => {
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius,
        backgroundColor: tileColor,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        boxShadow: "0 12px 32px rgba(240, 123, 50, 0.22), inset 0 1px 0 rgba(255,255,255,0.8)",
        ...style,
      }}
    >
      <Interactive.Svg
        name="BiliFetch Fox Vector"
        width={Math.round(size * 0.84)}
        height={Math.round(size * 0.84)}
        viewBox="0 0 100 100"
      >
        <Interactive.Path
          name="Left Outer Ear"
          d="M 24 40 L 14 8 L 44 26 Z"
          fill="#F07B32"
        />
        <Interactive.Path
          name="Right Outer Ear"
          d="M 76 40 L 86 8 L 56 26 Z"
          fill="#F07B32"
        />
        <Interactive.Path
          name="Left Inner Ear"
          d="M 27 37 L 21 17 L 38 28 Z"
          fill="#DD6A2A"
        />
        <Interactive.Path
          name="Right Inner Ear"
          d="M 73 37 L 79 17 L 62 28 Z"
          fill="#DD6A2A"
        />
        <ellipse cx="50" cy="54" rx="30" ry="28" fill="#F07B32" />
        <Interactive.Path
          name="Fox Muzzle"
          d="M 50 92 L 31 60 Q 50 46 69 60 Z"
          fill="#FFF6EC"
        />
        <ellipse cx="37.5" cy="53.5" rx="4.5" ry="5.5" fill="#3A2A20" />
        <ellipse cx="62.5" cy="53.5" rx="4.5" ry="5.5" fill="#3A2A20" />
        <ellipse cx="36.7" cy="51" rx="1.7" ry="2" fill="#FFFFFF" />
        <ellipse cx="61.7" cy="51" rx="1.7" ry="2" fill="#FFFFFF" />
        <ellipse cx="50" cy="61.5" rx="4.5" ry="3.5" fill="#F2748A" />
      </Interactive.Svg>
    </div>
  );
};

const foxLogoSchema = {
  size: {
    type: "number",
    min: 40,
    max: 500,
    step: 4,
    default: 120,
    description: "Logo Size",
    hiddenFromList: false,
  },
  tileColor: { type: "color", default: "#FFF1E6", description: "Tile Background" },
  borderRadius: {
    type: "number",
    min: 0,
    max: 120,
    step: 2,
    default: 26,
    description: "Corner Radius",
    hiddenFromList: false,
  },
} as const satisfies InteractivitySchema;

export const FoxLogo = Interactive.create({
  Component: FoxLogoInner,
  layout: "none",
  schema: foxLogoSchema,
});
