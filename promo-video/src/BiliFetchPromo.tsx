import type React from "react";
import { Audio } from "@remotion/media";
import { TransitionSeries, linearTiming, springTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import { wipe } from "@remotion/transitions/wipe";
import { staticFile, Track, useVideoConfig } from "remotion";
import { DanmakuLayer } from "./components/DanmakuLayer";
import { BatchWorkflowScene } from "./scenes/BatchWorkflowScene";
import { CrossPlatformScene } from "./scenes/CrossPlatformScene";
import { EngineArchitectureScene } from "./scenes/EngineArchitectureScene";
import { HeroRevealScene } from "./scenes/HeroRevealScene";
import { HookScene } from "./scenes/HookScene";
import { OutroCTAScene } from "./scenes/OutroCTAScene";

export type BiliFetchPromoProps = {
  readonly showDanmaku: boolean;
  readonly bgmVolume: number;
  readonly flowHookVideo: string;
  readonly flowEngineVideo: string;
  readonly flowFinaleVideo: string;
  readonly flowOutroVideo: string;
};

export const BiliFetchPromo: React.FC<BiliFetchPromoProps> = ({
  showDanmaku,
  bgmVolume,
  flowHookVideo,
  flowEngineVideo,
  flowFinaleVideo,
  flowOutroVideo,
}) => {
  const { fps } = useVideoConfig();
  const tr = Math.round(0.25 * fps); // 15 frames

  return (
    <>
      <Track name="Scenes">
        <TransitionSeries>
          {/* Scene 1: 0s -> 4.0s (effective 240f) */}
          <TransitionSeries.Sequence name="Hook" durationInFrames={255}>
            <HookScene
              name="Pain Hook & Fox Burst"
              hookTitle="B站存 4K 番剧 / 百集课程？"
              burstTitle={"别忍了，\n直接满速破局！"}
              flowHookVideo={flowHookVideo}
              style={{ backgroundColor: "#0C0D12" }}
            />
          </TransitionSeries.Sequence>

          <TransitionSeries.Transition
            presentation={wipe({ direction: "from-left" })}
            timing={linearTiming({ durationInFrames: tr })}
            motionBlur={{ shutterAngle: 180, samples: 10 }}
          />

          {/* Scene 2: 4.0s -> 10.0s (effective 360f) */}
          <TransitionSeries.Sequence name="Hero Reveal" durationInFrames={375}>
            <HeroRevealScene
              name="3D Macro Tour & Live Queue"
              headline={"安静、满速地保存\nB 站视频与整季番剧"}
              demoUrl="https://www.bilibili.com/bangumi/play/ep1633643"
              style={{ backgroundColor: "#FAF9F6" }}
            />
          </TransitionSeries.Sequence>

          <TransitionSeries.Transition
            presentation={slide({ direction: "from-right" })}
            timing={springTiming({ config: { damping: 200 }, durationInFrames: tr })}
            motionBlur={{ shutterAngle: 180, samples: 10 }}
          />

          {/* Scene 3: 10.0s -> 18.0s (effective 480f) */}
          <TransitionSeries.Sequence name="Batch & Dark Mode" durationInFrames={495}>
            <BatchWorkflowScene
              name="Batch Picker & Iris Dark Mode"
              title={"整季番剧与百集合集\n一屏勾选批量拉满"}
              darkTitle={"深色外观护眼直切\n扫码解锁 4K 原画"}
              style={{ backgroundColor: "#FAF9F6" }}
            />
          </TransitionSeries.Sequence>

          <TransitionSeries.Transition
            presentation={wipe({ direction: "from-bottom" })}
            timing={linearTiming({ durationInFrames: tr })}
            motionBlur={{ shutterAngle: 180, samples: 10 }}
          />

          {/* Scene 4: 18.0s -> 26.0s (effective 480f) */}
          <TransitionSeries.Sequence name="Core Engine" durationInFrames={495}>
            <EngineArchitectureScene
              name="Exploded Stack & 64-Thread Stream"
              title="把功夫花在看不见的稳定性上"
              flowEngineVideo={flowEngineVideo}
              style={{ backgroundColor: "#0E0F14" }}
            />
          </TransitionSeries.Sequence>

          <TransitionSeries.Transition
            presentation={slide({ direction: "from-left" })}
            timing={springTiming({ config: { damping: 200 }, durationInFrames: tr })}
            motionBlur={{ shutterAngle: 180, samples: 10 }}
          />

          {/* Scene 5: 26.0s -> 31.0s (effective 300f) */}
          <TransitionSeries.Sequence name="Cross Platform" durationInFrames={315}>
            <CrossPlatformScene
              name="macOS / Windows / Linux & CLI"
              title={"全平台原生 · 图形与命令行双修"}
              cliCommand='bilifetch "ep1633643" --all-episodes -q 120'
              flowFinaleVideo={flowFinaleVideo}
              style={{ backgroundColor: "#FAF9F6" }}
            />
          </TransitionSeries.Sequence>

          <TransitionSeries.Transition
            presentation={fade()}
            timing={linearTiming({ durationInFrames: tr })}
          />

          {/* Scene 6: 31.0s -> 36.0s (300f) */}
          <TransitionSeries.Sequence name="Outro CTA" durationInFrames={300}>
            <OutroCTAScene
              name="Long-Press Sanlian & Star CTA"
              repoUrl="github.com/oldsixxiaolv/bilifetch"
              ctaText="开源免费无广，欢迎一键三连！"
              flowOutroVideo={flowOutroVideo}
              style={{ backgroundColor: "#0E0F14" }}
            />
          </TransitionSeries.Sequence>
        </TransitionSeries>
      </Track>

      <Track name="Danmaku">
        <DanmakuLayer enabled={showDanmaku} />
      </Track>

      <Track name="BGM">
        <Audio
          name="Upbeat Tech Groove (Freesound CC0)"
          src={staticFile("audio/bgm-120bpm.wav")}
          volume={(f) => {
            const hookEase = f < 240 ? 0.88 : 1;
            const sparkleDuck = f >= 1972 && f <= 2035 ? 0.84 : 1;
            return bgmVolume * hookEase * sparkleDuck;
          }}
          durationInFrames={36 * fps}
        />
      </Track>

      <Track name="Impact & Transition SFX">
        <Audio name="Strobe Drop 1" from={0} durationInFrames={24} src={staticFile("sfx/slam-punch.wav")} volume={0.72} />
        <Audio name="Pain Slam 2" from={36} durationInFrames={24} src={staticFile("sfx/slam-punch.wav")} volume={0.72} />
        <Audio name="Pain Slam 3" from={72} durationInFrames={24} src={staticFile("sfx/slam-punch.wav")} volume={0.76} />
        <Audio name="Fox Burst Whoosh" from={124} durationInFrames={21} src={staticFile("sfx/whoosh.wav")} volume={0.78} />
        <Audio name="Drop 1 Impact" from={240} durationInFrames={70} src={staticFile("sfx/hit-drop.wav")} volume={0.82} />
        <Audio name="Scene 3 Transition" from={600} durationInFrames={21} src={staticFile("sfx/whoosh.wav")} volume={0.62} />
        <Audio name="Iris Dark Switch" from={832} durationInFrames={8} src={staticFile("sfx/switch.wav")} volume={0.78} />
        <Audio name="Bridge Core Sweep" from={1080} durationInFrames={78} src={staticFile("sfx/glitch-whoosh.wav")} volume={0.74} />
        <Audio name="Drop 2 Impact" from={1560} durationInFrames={70} src={staticFile("sfx/hit-drop.wav")} volume={0.8} />
        <Audio name="Outro Swoosh" from={1860} durationInFrames={21} src={staticFile("sfx/whoosh.wav")} volume={0.65} />
        <Audio name="Sanlian Burst Chime" from={1980} durationInFrames={55} src={staticFile("sfx/chime-done.wav")} volume={0.88} />
      </Track>

      <Track name="UI Foley SFX">
        <Audio name="URL Field Click" from={335} durationInFrames={3} src={staticFile("sfx/click.wav")} volume={0.68} />
        <Audio name="URL Type Tick 1" from={346} durationInFrames={10} src={staticFile("sfx/key-pop.wav")} volume={0.34} />
        <Audio name="URL Type Tick 2" from={360} durationInFrames={10} src={staticFile("sfx/key-pop.wav")} volume={0.34} />
        <Audio name="URL Type Tick 3" from={375} durationInFrames={10} src={staticFile("sfx/key-pop.wav")} volume={0.36} />
        <Audio name="Parse Click" from={425} durationInFrames={3} src={staticFile("sfx/click.wav")} volume={0.75} />
        <Audio name="Queue Done Ding" from={570} durationInFrames={19} src={staticFile("sfx/ding.wav")} volume={0.58} />
        <Audio name="Shortcut Cmd+F" from={662} durationInFrames={10} src={staticFile("sfx/key-pop.wav")} volume={0.72} />
        <Audio name="Shortcut Shift" from={735} durationInFrames={10} src={staticFile("sfx/key-pop.wav")} volume={0.72} />
        <Audio name="QR Login Ding" from={900} durationInFrames={19} src={staticFile("sfx/ding.wav")} volume={0.55} />
        <Audio name="Pause Lock" from={1320} durationInFrames={8} src={staticFile("sfx/switch.wav")} volume={0.7} />
        <Audio name="Resume Burst" from={1410} durationInFrames={3} src={staticFile("sfx/click.wav")} volume={0.72} />
        <Audio name="macOS Dock" from={1584} durationInFrames={5} src={staticFile("sfx/click-soft.wav")} volume={0.62} />
        <Audio name="Windows Dock" from={1610} durationInFrames={5} src={staticFile("sfx/click-soft.wav")} volume={0.62} />
        <Audio name="Linux Dock" from={1636} durationInFrames={5} src={staticFile("sfx/click-soft.wav")} volume={0.62} />
        <Audio name="CLI Done" from={1750} durationInFrames={19} src={staticFile("sfx/ding.wav")} volume={0.6} />
      </Track>

      <Track name="Cute Fox Foley">
        <Audio name="Hook Fox Hop" from={136} durationInFrames={8} src={staticFile("sfx/fox-pop.wav")} volume={0.72} />
        <Audio name="Hook Fox Sparkle" from={158} durationInFrames={21} src={staticFile("sfx/wink-sparkle.wav")} volume={0.58} />
        <Audio name="Desk Fox Pop" from={1575} durationInFrames={8} src={staticFile("sfx/fox-pop.wav")} volume={0.68} />
        <Audio name="Desk Fox Paw Tap" from={1622} durationInFrames={24} src={staticFile("sfx/low-thud.wav")} volume={0.55} />
        <Audio name="Desk Fox Wink" from={1740} durationInFrames={21} src={staticFile("sfx/wink-sparkle.wav")} volume={0.78} />
        <Audio name="Outro Fox Wave" from={1872} durationInFrames={8} src={staticFile("sfx/fox-pop.wav")} volume={0.65} />
        <Audio name="Outro Sanlian Wink" from={1976} durationInFrames={21} src={staticFile("sfx/wink-sparkle.wav")} volume={0.82} />
      </Track>
    </>
  );
};
