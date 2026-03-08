# Mac Over Speak - Implementation Plan & Task Tracker

## 1. Purify 机制 (音频过滤与文本净化) [P1]
- [ ] **音频门限 (Audio Gating)**
  - 实现 RMS 音量计算，在 `sd.InputStream` 回调中检测。
  - 设置 `MIN_DB_THRESHOLD` (建议 -45dB)。低于此值则不计入 `audio_data`。
- [ ] **文本长度过滤 (Text Filtering)**
  - 在 `_run_inference_and_type` 中使用正则 `re.sub(r'[^\w\s]', '', text)` 去除标点。
  - 若 `len(clean_text) < 2` 则直接中断后续逻辑，不执行打字操作。
  - **状态反馈**: 被过滤时不显示绿色 "TYPE" 状态，直接淡出 UI。

## 2. 指示器 UI 优化 (Indicator Polish) [P2]
- [ ] **视觉设计升级 (Dictation Style)**
  - 将简易红点改为带阴影和发光效果的球体/胶囊形状。
  - 实现录音时的“呼吸灯”动画或电平波纹效果。
- [ ] **坐标适配优化**
  - 针对 Retina 屏幕和多显示器，精确计算 Quartz 坐标到 Tkinter 屏显坐标的转换。
  - 优化 `update_position_loop` 的资源占用。

## 3. 设置界面与预加载 (Settings & Warm-up) [P3]
- [x] **配置持久化**
  - 使用 `~/.mac_over_speak_config.json` 存储用户自定义设置。
- [x] **自定义快捷键**
  - 在设置界面提供 GUI 录入快捷键 (如 `Cmd+Option+S`)。
  - 迁移至 `pynput.keyboard.GlobalHotKeys` 以支持更复杂的组合键。
- [x] **LLM 预热 (Warm-up)**
  - API 端点新增 `/warmup` 接口，触发模型 `to(device)` 加载。
  - 客户端启动或点击设置时，异步发送预热请求，避免首次识别的冷启动延迟。

## 4. macOS 应用打包 (Packaging) [P4]
- [ ] **打包流程自动化**
  - 使用 `PyInstaller` 或 `Nuitka` 进行 Bundle 打包。
  - 注入 `Info.plist` 必要权限声明 (Microphone, Accessibility)。
- [ ] **制作安装镜像 (.dmg)**
  - 使用 `dmgbuild` 或 `create-dmg` 制作标准拖拽安装包。

## 5. 快速启动 [P5]
- [x] **编写启动脚本**
  - 创建了 `start.sh` 脚本，可一键启动 API 服务和客户端。
  - 脚本包含自动等待 API 就绪和退出时自动清理进程的逻辑。

---

实施策略
P1 P2 暂时忽略
先完成P3
P4 暂时忽略
