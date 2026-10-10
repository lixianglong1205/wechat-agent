# 原型的命令与实现细节

这份文档保留 README 中移出的技术细节。**档案、阅读服务和移动客户端源码尚未合入公开仓库，下面对应命令暂时不能直接在这个仓库运行。** 目前可独立使用的是 [wechat-desktop Skill](../skills/wechat-desktop/SKILL.md)。

## 依赖记录

| 模块 | 原型使用的版本或要求 |
| --- | --- |
| Python | 3.12+，uv 管理依赖 |
| 取钥 | Frida 17.18.0 |
| SILK 解码 | pilk 0.2.4；其他部分格式依赖 ffmpeg |
| 桌面工具 | Apple Swift 6.4、Xcode 27.0 |
| 阅读服务 | Docker、Tinode 服务端及 Web 0.25.3、PostgreSQL |
| 移动应用 | Capacitor 8.5.3，Node 22+，Xcode 26+；Android 使用 JDK 21、SDK 36 |

这是原型记录，其他依赖由各自锁文件固定。不是所有组合都经过兼容验证。

## 数据恢复与同步

在原型项目根目录运行：

```sh
# 复用已有密钥，只处理副本。
./skill/scripts/wechat refresh

# 缺钥时显式尝试捕获，先满足采用方法的进程访问条件。
./skill/scripts/wechat refresh --capture

# 未安装专用 helper、且需要单次管理员授权时。
./skill/scripts/wechat refresh --capture --admin

# 每次只同步一次；不安装定时任务。
./skill/scripts/wechat sync
./skill/scripts/wechat status
```

恢复顺序为：发现文件 → 一致性复制数据库与 WAL → 验证缓存密钥 → 按需捕获 → 逐页认证解密 → SQLite `integrity_check` → 导入。各数据库快照有自己的时间点，不是跨全部数据库的同一事务快照。

密钥缓存按账号隔离，只有对目标数据库首页 HMAC 验证通过的密钥才写入，权限为 0600。已验证密钥优先复用，不因每次查询重新取钥。升级不一定换钥，但库可能被重建，所以复用时仍需验证。

| 状态 | 含义 |
| --- | --- |
| verified | 通过解密和完整性检查 |
| missing_key | 没有可验证的密钥 |
| snapshot_failed | 副本不满足要求 |
| decrypt_failed | 解密或页认证失败 |
| integrity_failed | 解密后数据库逻辑校验失败，不应只靠重复取钥处理 |

专用管理员 helper 限定账号和固定入口，减少重复授权；不保证能解决当前版本的进程访问限制。完整历史见[验证记录](verification.md)。

## 档案和媒体

```text
data/
  archive.duckdb       消息、联系人、来源、处理状态、转写文字
  keyring.json         当前账号的已验证密钥
  recovery-runs/       明文副本和逐库恢复结果
  objects/            独立媒体文件
  voice-results/      转写结果与恢复回执
```

消息保留原始标识、发送者、会话、时间、类型、来源分片和表，导入按标识去重，内容更新保留旧版本。同步独占锁，查询共享锁；查询使用只读 DuckDB 连接。普通问题不运行 embedding 任务。

```sh
./skill/scripts/wechat sync
./skill/scripts/wechat voice extract
./skill/scripts/wechat voice status
./skill/scripts/wechat voice transcribe \
  --key-file /absolute/path/to/private-gemini-key \
  --model '<项目当前可用的音频模型>' --limit 10

# 更新媒体文件副本，不代表做了图片识别。
./skill/scripts/wechat sync --media
```

音频原件和解码 WAV 存在文件系统，DuckDB 保存路径和关联。转写不覆盖原消息，查询视图合并最新成功转写，标明来源和模型。任务按音频哈希、模型和配置去重；失败保留状态。普通 Gemini 音频模型走 generateContent，专用转写模型有单独适配，使用前检查接口兼容性。

图片支持普通格式和部分旧式 XOR `.dat` 解码；新版加密图片保留文件并标记 encrypted。没有批量 OCR，图片与消息也未全部精确关联。文件修改时间不能冒充消息发送时间。

收藏主库曾校验通过，收藏全文检索库未通过完整性校验；尚无通用收藏查询入口。公众号正文可能在其他库或网页，主消息中的链接和标题不等于完整文章。

## 查询

```sh
./skill/scripts/wechat contacts '联系人名字'
./skill/scripts/wechat overview --conversation '<已确认的 username>'
./skill/scripts/wechat messages --conversation '<已确认的 username>' \
  --since 2026-10-01 --until 2026-10-09 --limit 80
./skill/scripts/wechat context '<message_id>' --radius 8
```

日期参数按北京时间解释。查询结果包含分页与正文截断信息，Agent 需要按问题范围继续取证。同步时间、最新消息时间和不同媒体的覆盖率分别报告。

## 阅读服务

```sh
uv sync --extra reader
.venv/bin/python -m reader.manage start
.venv/bin/python -m reader.manage import
.venv/bin/python -m reader.verify
.venv/bin/python -m reader.manage status
.venv/bin/python -m reader.manage stop
```

本机入口为 `http://127.0.0.1:8768`。生成部署者自己的随机凭据；DuckDB 是来源，PostgreSQL 是展示副本。历史主题只读，服务端角色拒绝修改历史消息。原始图片附件和音频播放未接入。

新增消息需要先 `sync`，再 `reader.manage import`。导入暂停的是独立查看器进程，不是微信。新消息时间早于会话已导入的末尾时会回滚，历史回填需要额外重建流程；更新已有文字或转写后，客户端缓存可能需要刷新。

```sh
# 先确认已有 Serve 配置，避免覆盖别的服务。
tailscale serve status
tailscale serve --bg --https=443 http://127.0.0.1:8768
tailscale serve status
```

使用当前设备输出的 HTTPS 地址。固定地址依赖设备身份和名称，Mac、Tailscale、Docker、查看器需在线；没有启用公网 Funnel。

## 移动客户端

```sh
npm ci --prefix mobile
npm ci --ignore-scripts --prefix mobile/vendor/tinode-web
# 先完成阅读端静态资源准备，配置自己的后端地址。
npm run sync --prefix mobile

cd mobile/android
./gradlew assembleDebug
```

iOS 用自己的 Bundle ID、Apple 团队和签名配置，在 Xcode 中归档并上传 TestFlight。发布的 App 只带公开界面资源，数据库和密码不打包。

原型是 Capacitor 包装的 Web 界面：iOS 使用 WKWebView，Android 使用 WebView；不是 Tinode Swift/Java 原生客户端的改版。服务端和 Web 固定 0.25.3，Tinode Web 来源提交为 `70a9ab8996466ba2460bef957d23b50f9ccc99cc`。保留对应上游许可证；本仓库 MIT 不覆盖未来引入的第三方代码。
