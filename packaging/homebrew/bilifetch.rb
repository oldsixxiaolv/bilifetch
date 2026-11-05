# Homebrew cask —— macOS 上最省事的装法
#
# 用法：
#   1. 把这个文件放到你的 tap 里，例如 ~/homebrew-tap/Casks/bilifetch.rb
#   2. brew install --cask bilifetch
#
# 注意：url 和 sha256 要在发布新版本后更新（sha256 取 dist/SHA256SUMS 里的值）。
# brew 会在安装时自动去掉隔离属性（com.apple.quarantine），
# 所以不会出现"无法验证开发者"的弹窗。

cask "bilifetch" do
  version "1.1.0"
  sha256 "dc3d695627b78964571f9753a7b043d1cb09d35878209cf49577669b078a60ce"

  url "https://github.com/oldsixxiaolv/bilifetch/releases/download/v#{version}/BiliFetch-#{version}-macOS.dmg"
  name "BiliFetch"
  desc "B 站视频下载器（图形界面 + 命令行，支持番剧 / 分P / b23.tv 短链）"
  homepage "https://github.com/oldsixxiaolv/bilifetch"

  app "BiliFetch.app"

  depends_on macos: ">= :big_sur"

  post_install do
    # 把命令行入口也放进 /usr/local/bin，这样终端里直接敲 bilifetch 就能用。
    # 命令行版在镜像的「便携版」目录里（PyInstaller 打出来的 .app 只有图形界面）。
    dmg_root = Pathname.new(staged_path).parent
    src = dmg_root + "便携版"
    libdir = "/usr/local/lib/bilifetch"
    system_command "/bin/mkdir", "-p", libdir
    system_command "/bin/cp", "#{src}/lib/bilifetch/bilifetch.py", "#{libdir}/bilifetch.py"
    system_command "/bin/cp", "#{src}/bin/bilifetch", "/usr/local/bin/bilifetch"
    system_command "/bin/chmod", "755", "/usr/local/bin/bilifetch", "#{libdir}/bilifetch.py"
  end

  uninstall do
    system_command "/bin/rm", "-f", "/usr/local/bin/bilifetch"
    system_command "/bin/rm", "-rf", "/usr/local/lib/bilifetch"
  end

  caveats <<~EOS
    还需要三个依赖（brew install 一条命令搞定）：
      brew install python ffmpeg && pip3 install requests

    装完在终端里直接用：
      bilifetch 'https://www.bilibili.com/bangumi/play/ep1633643'
  EOS
end
