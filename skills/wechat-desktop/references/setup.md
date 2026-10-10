# 安装与权限

本 Skill 可完整复制到 `~/.codex/skills/wechat-desktop`，不依赖作者的其他 Skill 或数据库。需要 macOS、Xcode Command Line Tools（含 Swift）、Python 3.12+、已登录且可见的微信。源代码在 `scripts/swift/`。已实测版本见仓库验证记录；其他版本先编译和检查。

在 Skill 目录运行：

```sh
python3 scripts/wechat_ui.py build
python3 scripts/wechat_ui.py status
```

构建产物默认放在 `~/Library/Application Support/WeChatAgent/desktop`，可通过 `WECHAT_AGENT_RUNTIME` 设置独立绝对路径。该目录权限为 0700，截图、临时消息文件为 0600；不要把它设为 Git 仓库目录。

构建包含一个临时编译出的截图可执行文件，以及 `WeChat Agent Keyboard.app`。App 的 bundle ID 为 `org.rebyte.wechatagent.keyboard`，采用本地 ad-hoc 签名。首次运行可能还需系统允许执行本地构建工具。构建器只安装自己的工具，不改变微信。

## 两项独立授权

1. **System Settings → Privacy & Security → Accessibility（辅助功能）**：用 `+` 添加构建输出中的 `WeChat Agent Keyboard.app`，启用开关。通过 Finder 的 `⌘⇧G` 可以粘贴 App 路径。以键盘工具 `status` 返回 true 为准。
2. **Screen Recording / Screen & System Audio Recording（屏幕录制）**：允许实际运行截图工具的终端/Agent 宿主或系统列出的截图工具。名称随系统版本变化。`capture --request-permission` 是显式请求屏幕录制授权的入口；不授权时普通截图会退出。系统要求重启宿主时按提示处理。

如果用户要求打开设置，可以运行相应深链：

```sh
open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'
open 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'
```

这些操作会显示设置窗口，不应在用户要求全程后台时自动执行。脚本不替用户点系统授权开关，不修改 TCC 数据库。

`build` 在源码及编译工具版本未变时复用已有产物，避免无意义重签。源码变化后会重新构建；系统可能需要重新授权。不要把作者机器上的授权状态当作你的机器已经授权。

## 首次验证

先运行 `status` 和 `capture`，确认可读取画面。再在用户授权下将微信置前台，先测试 `search` 并观察，不要上来就按回车。身份明确后先给用户自己发送一条用户授权的测试消息。

`activate --allow-foreground` 只将已存在的唯一微信进程对应 App 激活；零个或多个进程时拒绝。它不退出或重启微信。后续键盘操作若微信失去前台会中止，可能留下部分草稿；检查现状后再决定如何继续。

删除运行目录即可移除工具和私有截图；如系统仍列出它，在辅助功能设置手动移除授权。不会安装开机任务或驻留服务。
