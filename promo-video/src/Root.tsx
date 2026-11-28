import { Composition, Folder, Still } from "remotion";
import { BiliFetchCover } from "./BiliFetchCover";
import { BiliFetchPromo } from "./BiliFetchPromo";
import { FoxLogo } from "./components/FoxLogo";
import { BatchWorkflowScene } from "./scenes/BatchWorkflowScene";
import { CrossPlatformScene } from "./scenes/CrossPlatformScene";
import { EngineArchitectureScene } from "./scenes/EngineArchitectureScene";
import { HeroRevealScene } from "./scenes/HeroRevealScene";
import { HookScene } from "./scenes/HookScene";
import { OutroCTAScene } from "./scenes/OutroCTAScene";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="BiliFetchPromo"
        component={BiliFetchPromo}
        durationInFrames={2160}
        fps={60}
        width={1920}
        height={1080}
        defaultProps={{
          showDanmaku: false,
          bgmVolume: 0.72,
          flowHookVideo: "assets/flow-hook.mp4",
          flowEngineVideo: "assets/flow-engine.mp4",
          flowFinaleVideo: "assets/flow-finale.mp4",
          flowOutroVideo: "assets/flow-outro.mp4",
        }}
      />

      <Still
        id="BiliFetchCover"
        component={BiliFetchCover}
        width={1920}
        height={1080}
        defaultProps={{
          mainTitle: "B站 4K 番剧\n满速下载神器！",
          subTitle: "64路并发 · 整季批量 · 开源无广告",
          badge: "OPEN SOURCE · 28.6 MB/s",
        }}
      />

      <Folder name="Scenes">
        <Composition
          id="HookScene"
          component={HookScene}
          durationInFrames={255}
          fps={60}
          width={1920}
          height={1080}
          defaultProps={{
            hookTitle: "B站存 4K 番剧 / 百集课程？",
            burstTitle: "别忍了，\n直接满速破局！",
            flowHookVideo: "assets/flow-hook.mp4",
            style: { backgroundColor: "#0C0D12" },
          }}
        />
        <Composition
          id="HeroRevealScene"
          component={HeroRevealScene}
          durationInFrames={375}
          fps={60}
          width={1920}
          height={1080}
          defaultProps={{
            headline: "安静、满速地保存\nB 站视频与整季番剧",
            demoUrl: "https://www.bilibili.com/bangumi/play/ep1633643",
            style: { backgroundColor: "#FAF9F6" },
          }}
        />
        <Composition
          id="BatchWorkflowScene"
          component={BatchWorkflowScene}
          durationInFrames={495}
          fps={60}
          width={1920}
          height={1080}
          defaultProps={{
            title: "整季番剧与百集合集\n一屏勾选批量拉满",
            darkTitle: "深色外观护眼直切\n扫码解锁 4K 原画",
            style: { backgroundColor: "#FAF9F6" },
          }}
        />
        <Composition
          id="EngineArchitectureScene"
          component={EngineArchitectureScene}
          durationInFrames={495}
          fps={60}
          width={1920}
          height={1080}
          defaultProps={{
            title: "把功夫花在看不见的稳定性上",
            flowEngineVideo: "assets/flow-engine.mp4",
            style: { backgroundColor: "#0E0F14" },
          }}
        />
        <Composition
          id="CrossPlatformScene"
          component={CrossPlatformScene}
          durationInFrames={315}
          fps={60}
          width={1920}
          height={1080}
          defaultProps={{
            title: "全平台原生 · 图形与命令行双修",
            cliCommand: 'bilifetch "ep1633643" --all-episodes -q 120',
            flowFinaleVideo: "assets/flow-finale.mp4",
            style: { backgroundColor: "#FAF9F6" },
          }}
        />
        <Composition
          id="OutroCTAScene"
          component={OutroCTAScene}
          durationInFrames={300}
          fps={60}
          width={1920}
          height={1080}
          defaultProps={{
            repoUrl: "github.com/oldsixxiaolv/bilifetch",
            ctaText: "开源免费无广，欢迎一键三连！",
            flowOutroVideo: "assets/flow-outro.mp4",
            style: { backgroundColor: "#0E0F14" },
          }}
        />
      </Folder>

      <Folder name="Elements">
        <Composition
          id="FoxLogo"
          component={FoxLogo}
          durationInFrames={120}
          fps={60}
          width={400}
          height={400}
          defaultProps={{
            size: 260,
            tileColor: "#FFF1E6",
            borderRadius: 60,
          }}
        />
      </Folder>
    </>
  );
};
