import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadJetBrainsMono } from "@remotion/google-fonts/JetBrainsMono";

const inter = loadInter("normal", {
  weights: ["400", "500", "600", "700", "800"],
  subsets: ["latin"],
});

const jbMono = loadJetBrainsMono("normal", {
  weights: ["400", "500", "700"],
  subsets: ["latin"],
});

export const FONT_SANS = `${inter.fontFamily}, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei UI", "Noto Sans CJK SC", sans-serif`;
export const FONT_SERIF = `"Songti SC", "Noto Serif SC", "STSong", Georgia, serif`;
export const FONT_MONO = `${jbMono.fontFamily}, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;

export const PALETTE = {
  pink: "#FB7299",
  pinkSoft: "#FFF0F4",
  pinkDark: "#E8628A",
  blue: "#00AEEC",
  blueSoft: "#E6F7FD",
  foxOrange: "#F07B32",
  foxDark: "#DD6A2A",
  foxCream: "#FFF6EC",
  foxTile: "#FFF1E6",
  green: "#2BB673",
  greenSoft: "#E9F8F0",
  orange: "#FF9F2E",
  red: "#F25D59",
  alabaster: "#FAF9F6",
  surface: "#FFFFFF",
  obsidian: "#111216",
  graphite: "#18181C",
  cardDark: "#1F2026",
  borderDark: "#32343D",
  ink: "#161615",
  ink2: "#575550",
  ink3: "#8A867E",
  inkDark: "#F5F5F7",
  inkDark2: "#A1A1AA",
} as const;
