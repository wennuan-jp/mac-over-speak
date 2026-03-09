# Mac Over Speak - Implementation Plan & Task Tracker

## 1. Purify 机制 (音频过滤与文本净化) [P1]
- [ ] **音频门限 (Audio Gating)**
  - 实现 RMS 音量计算，在 `sd.InputStream` 回调中检测。
  - 设置 `MIN_DB_THRESHOLD` (建议 -45dB)。低于此值则不计入 `audio_data`。
- [ ] **文本长度过滤 (Text Filtering)**
  - 在 `_run_inference_and_type` 中使用正则 `re.sub(r'[^\w\s]', '', text)` 去除标点。
  - 若 `len(clean_text) < 2` 则直接中断后续逻辑，不执行打字操作。
  - **状态反馈**: 被过滤时不显示绿色 "TYPE" 状态，直接淡出 UI。
ß
## 2. 指示器 UI 优化 (Indicator Polish) [P2]
- [ ] **视觉设计升级 (Dictation Style)**
  - 将简易红点改为带阴影和发光效果的球体/胶囊形状。需要提示当前的输入法。样式要和 Mac OS 一样。
  - 当用户切换输入法的时候，这个提示也需要发跟着发生变化，显示当前的输入法。
- [ ] **坐标适配优化**
  - 针对 Retina 屏幕和多显示器，精确计算 Quartz 坐标到 Tkinter 屏显坐标的转换。这个坐标完全不需要计算，只需要出现在当前的focus下方就可以了。
  - 优化 `update_position_loop` 的资源占用。PS: 这一点是你自己加上去的，我不知道目前是否需要考虑这一点。

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
- [x] **打包流程自动化**
  - 使用 `PyInstaller` 将客户端和后端逻辑打包为单二进制 `.app` 文件。
  - 软件启动时会自动打开设置界面（首次运行友好型）。
  - 创建了 `build_dmg.sh` 脚本，可一键完成从源码到安装镜像的全过程。
- [x] **制作安装镜像 (.dmg)**
  - 使用 `dmgbuild` 制作了标准的“拖拽安装”式磁盘镜像：[MacOverSpeak.dmg](file:///Users/wennuan/dev/projects/mac_over_speak/MacOverSpeak.dmg)。
- [x] 修复installer实际打开什么都没有的问题（在 `dmg_settings.py` 中使用了正确的 `files` 和 `symlinks` 语法）。

## 5. 快速启动 [P5]
- [x] **编写启动脚本**
  - 创建了 `start.sh` 脚本，可一键启动 API 服务和客户端。
  - 脚本包含自动等待 API 就绪和退出时自动清理进程的逻辑。

## 6. 更换快捷键支持按键设置 [P3]
- [x] **交互式快捷键录入 (Interactive Hotkey Recording)**
  - 在设置界面提供“录制”按钮，自动捕获用户的按键组合。
  - 支持组合键（如 `Cmd+Shift+S`）并自动格式化为 pynput 可识别的字符串。
  - **交互流程**: 点击录制 -> 按下组合键 -> 松开非修饰键即完成捕获 -> 自动填入。
  - **保存与生效**: 点击“保存并重启”后，新快捷键即时生效并持久化到配置文件。
  - **MacOS Stability**: Fixed `trace trap` crash by disabling event suppression during recording and managing listener lifecycle to avoid conflicts.

## 7 remove 快捷键支持按键设置监听功能 只支持打字设置
- [x] 但是要user friendly <f12> 这种就不好 要让用户可以直接从现成的按键选项中选择 比如用户点击的时候就弹出常见的按键chip choice, 用户如果输入 则filter相关chip

# Problems

- [x] 当输入法选择为日文的时候, detected language为英文 (已修复: 增加了对日文输入法的识别并映射为 "ja")
- [x] 修复了 API 端语言代码映射导致的 500 错误。
- [x] 扩展了 API 支持的语言列表（30+ 语言）。
- [x] 修复了打包后应用因缺少 Accessibility 权限导致快捷键失效的问题（增加了权限检查提示）。
- [ ] 正在解决打包安装后后端服务显示 "Offline" 的问题（正在增强路径识别和日志输出）。

# Better than none

- [ ] indicator icon in task bar should indicate llm status, when warming up should show a spinner, when ready should show a checkmark with mic, when error or offline should show a cross with mic