# 7-Zip 兼容运行时信任模型

KOI 4.0.0 使用 NanaZip 7.0.1832.0（7-Zip engine 2609.1）的 Windows x64 控制台处理 7z/RAR。运行时不解析 `PATH`，每次使用前都会验证公开锁与编译进 `koi.exe` 的锁完全一致、完整目录清单和 SHA-256，并调用 Windows WinVerifyTrust 验证随包分发的 x64 MSIX 发布者签名。

## 发布者签名与文件绑定

- 上游来源固定为 [M2-Team NanaZip 7.0.1832.0 release](https://github.com/M2Team/NanaZip/releases/tag/7.0.1832.0)，release commit 为 `4f6f082858cb959a82c0d64a46352d7fb40ff146`。
- 官方 `NanaZip_7.0.1832.0.msixbundle` 的 GitHub release digest 固定为 `10ce4246ea9efc0dcc7780e676cdcc6c7c74eca0abeb19a5ea76f384d9be2a75`。
- 其中 x64 包 `NanaZipPackage_7.0.1832.0_x64.msix` 的 SHA-256 固定为 `df0469573ec269a5bc1dc589a68a19dda3dc8dfe4b4a8d849de81ee42c422e40`。其 Authenticode 状态必须为 `Valid`，签名者固定为 `CN=E310A153-74A9-4D81-800B-857A8D58408A`，证书由 Microsoft Marketplace CA 签发并带 Microsoft 时间戳。
- `NanaZip.Universal.Console.exe`、`NanaZip.Core.dll`、`NanaZip.Codecs.dll`、`K7Base.dll` 和 `K7User.dll` 本身没有单独的 Authenticode 签名。KOI 不把它们描述成独立签名文件，而是要求它们与已验证签名 MSIX 中的对应条目逐字节一致。
- `AppxManifest.xml` 中的包名、发布者、版本、x64 架构和控制台入口也会再次校验。

因此，执行文件的信任链来自发布者签名 MSIX，SHA-256 用于锁定经审查的 release 和防止包外替换；两者缺一不可。

## Fail-closed 规则

`archive-runtime.lock.json` 使用 `koi-archive-runtime-v3`，信任模型固定为 `publisher-signed-msix-runtime-binding-v1`。以下任一情况都会拒绝运行或发布：

- 公开锁与编译进 `koi.exe` 的锁不完全一致；
- MSIX 缺失、字节变化、Windows 信任验证失败、签名者或时间戳不匹配；
- MSIX 包身份、版本、架构或控制台入口漂移；
- 包外运行时文件与签名 MSIX 内条目不一致；
- 运行时文件缺失、多出文件、发生字节变化或不是 x64 PE；
- 发布清单没有继续公开 `publisherAuthenticated: true` 和精确的签名/绑定元数据。

升级 NanaZip 必须重新核验 release commit、GitHub digest、Microsoft Marketplace 签名、时间戳、包身份、许可文本和所有包内外文件哈希，并通过 Rust 与 Node 的正负向测试。
