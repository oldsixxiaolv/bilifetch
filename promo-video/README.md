# BiliFetch Bilibili Promo Video (Remotion)

基于 `guanmo-ai/awesome-ai-motion` 爆款产品片结构（120 BPM 节拍同步 + 连续 UI 状态变形 + 硬核工程数据可视化）与 `BiliFetch v1.2.0` 真实界面素材打造的高清宣传视频工程。

## 视频结构（1920×1080 · 60fps · 36s / 2160 frames）

| 段落 | 时间轴 | 内容亮点 |
|---|---|---|
| `HookScene` | `0.0s – 4.0s` | 痛点暴击（100 KB/s / 断流 / VIP 广告）→ 3D 小狐狸冲破红圈卡顿，配合速度线切入 Drop 1 |
| `HeroRevealScene` | `4.0s – 10.0s` | 暖白主页揭示，模拟鼠标输入 `ep1633643`，触发「番剧 / 剧集」胶囊分类并点击解析 |
| `BatchWorkflowScene` | `10.0s – 18.0s` | 批量选集窗口 + `⌘F` / `Shift` 物理键帽动画 → 剪贴裁剪转场切入深色外观 + 扫码解锁 4K 卡片 |
| `EngineArchitectureScene` | `18.0s – 26.0s` | 多 CDN 探速实时进度条（绕过慢节点）+ 64 路 TLS 保活池 / 0.4ms 秒恢复 / `-c copy` 指标卡片 |
| `CrossPlatformScene` | `26.0s – 31.0s` | 3D 狐狸与桌面展台 + macOS / Windows / Linux 发行包一览 + CLI 命令行打字机演示 |
| `OutroCTAScene` | `31.0s – 36.0s` | BiliFetch 品牌锁定 + GitHub 仓库 + B 站一键三连动效（点赞 / 投币 / 收藏 Star） |

另外附带 `<Still id="BiliFetchCover">` 用于一键导出 B 站 16:9 爆款视频封面。

## 常用命令

```bash
npm run dev      # 启动 Remotion Studio（http://localhost:3100）实时可视化微调与预览
npm run lint     # ESLint + TypeScript 类型检查
npm run render   # 渲染完整 1080p60 MP4 成片至 out/BiliFetch-promo-1080p60.mp4
npm run cover    # 导出视频封面至 out/BiliFetch-cover.png
```
