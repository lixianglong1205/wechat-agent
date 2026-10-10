# Swift 桌面工具

源码统一保存在 [wechat-desktop Skill](../skills/wechat-desktop/SKILL.md) 中，避免教程和 Skill 维护两份不同实现：

- [截图源码](../skills/wechat-desktop/scripts/swift/WeChatCaptureProbe.swift)
- [键盘源码](../skills/wechat-desktop/scripts/swift/WeChatKeyboard.swift)
- [构建与命令入口](../skills/wechat-desktop/scripts/wechat_ui.py)
- [安装、权限及首次验证](../skills/wechat-desktop/references/setup.md)

```sh
cd skills/wechat-desktop
python3 scripts/wechat_ui.py build
python3 scripts/wechat_ui.py status
python3 scripts/wechat_ui.py capture
```

截图有三种输出：`01-direct-window.png`（独立主窗口）、`02-refreshed-stream.png`（更新过滤器后的流）、`03-app-windows.png`（同应用窗口，包含搜索下拉框）。最后一种裁剪到主窗口范围，伸出范围的弹窗仍可能被裁掉。三者只采集屏幕画面，不采集音频。输出在私有运行目录。

键盘命令只针对一个前台微信进程；每次命令执行后退出。工具本身没有 AI、收件人判断或发送队列，也不会自动重复发送。首次授权需要用户处理；后续顺序由 Agent 根据新截图决定。
