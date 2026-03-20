# PicShrink

一个面向小白用户的图片批量压缩与尺寸调整工具（桌面 GUI）。

## macOS 本地运行

```bash
cd /Users/bytedance/Task/picshrink
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
python -m picshrink
```

如果启动时提示需要同意 Xcode License，可执行：

```bash
sudo xcodebuild -license accept
```

## Windows 打包（单文件 .exe）

在 Windows 上：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -U pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
pyinstaller --onefile --windowed -n PicShrink picshrink/__main__.py
```

产物位于 `dist/PicShrink.exe`。

## Windows 打包（GitHub Actions）

没有 Windows 环境时，推荐用 GitHub Actions 的 Windows Runner 构建并下载 `PicShrink.exe`。

1. 把 `/Users/bytedance/Task/picshrink` 作为一个仓库推到 GitHub
2. 在 GitHub 页面打开 Actions，选择 `Build PicShrink (Windows)`
3. 点击 `Run workflow` 触发构建
4. 构建完成后，在该次运行页面的 Artifacts 下载 `PicShrink-windows-exe`

下载到的 artifact 内就是单文件 `PicShrink.exe`，可直接交付给 Windows 用户。

说明：
- 该 exe 为 PyInstaller `--onefile` 形态，交付物只有一个 exe；运行时会在用户临时目录自解压依赖后启动（用户侧不需要额外安装 Python/Qt）。
- 若你希望“解压后可携带的一整个文件夹”形态，可把 `--onefile` 改为默认的 `onedir`，再把 `dist/PicShrink/` 压缩成 zip 交付。
