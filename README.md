# 随身论文库 · Portable Paper Library

把论文、译文和不同出版版本放在一起，用中文或英文关键词快速找到研究文件夹，再选择具体文件。数据保存在本地目录，可连同程序一起复制到 U 盘。

这是一个中文界面的本地单用户工具：Python 标准库 + SQLite + 原生 HTML/CSS/JavaScript，无需 MySQL、Node.js 或在线账号。

## 功能

- 标题、关键词、独立版本编号检索；通过可编辑双语词表扩展查询。
- 同一研究共用文件夹，每个语言或出版版本保留独立入库编号。
- 已打印、未打印、待补电子文件筛选。
- 上传附件、在浏览器打开 PDF、打开本地研究文件夹。
- 标记电子版与纸本的核对状态；同标题或同来源收录前提示查重。
- JSON 目录导出、SQLite 索引备份、包含附件的完整备份及 SHA-256 清单。
- 命令行 JSON 查询，便于本地 AI 工具读取。

双语搜索基于 `data/glossary.json` 和填写的元数据，不是自动翻译或语义向量搜索。不读取 PDF 正文，也不自动搜索、下载或翻译论文。当前没有 AI 插件或 Codex skill。

## 启动

需要 Python 3.9 或更新版本。首个源码发行包不附带 Python 运行环境，首次启动会创建空库。

Linux：

```sh
sh Start-Linux.sh
```

Windows 10 / 11：安装 Python 3，并启用 Python 启动器或添加到 PATH，然后双击 `Start-Windows.cmd`。

也可以在项目目录直接运行：

```sh
python app/library.py
```

程序仅监听本机 `127.0.0.1`，自动选择空闲端口并打开浏览器。第一次点击“收录论文”建立记录。退出时点击页面“退出系统”，等程序结束后再安全弹出 U 盘。

如果自行配备兼容的运行环境，启动脚本也识别 `runtime/linux-x64/bin/python3` 和 `runtime/windows-x64/python.exe`。此仓库不分发这些二进制文件。

## 数据与移动

```text
app/                 程序与界面
Start-Linux.sh       Linux 入口
Start-Windows.cmd    Windows 入口
data/glossary.json  可编辑双语词表
data/library.sqlite3  首次运行后创建的个人索引
papers/G0001/0001/   首次收录后创建的研究组 / 版本附件目录
```

移动论文库时，关闭程序并复制整个目录。使用可写文件系统；Windows 与 Linux 共享 U 盘时应选择两端都能读写的格式。不支持两台电脑同时写同一份库。

编号按版本入库顺序分配。把译文作为同组新版本收录，不要覆盖原文。纸本打印状态、电子文件是否存在、纸本版本是否一致是三个不同状态。

“待补电子版”当前判断版本目录内是否存在附件，因此请不要把封面照片或占位文件当作全文上传。

## AI / 命令行查询

```sh
python app/library.py --query "隐私推理"
python app/library.py --query "1"
python app/library.py --query "" --status unprinted
python app/library.py --export
```

查询输出是 JSON，Unicode 转义不影响解析。目录包含本机路径，导出文件也可能包含个人备注；对外分享前请自行检查。

研究时应先根据项目需要检索已有论文，同时扩展外部文献；建议 AI 在新增论文或新版本前向使用者展示候选并取得确认。工具自身不会执行这些外部操作。

## 备份与恢复

“备份与恢复”提供索引备份和完整备份。索引备份不包含 PDF；完整备份保存在项目目录旁的 `PaperLibrary-Backups/`，包含个人资料，不能作为公开发布包。

恢复完整备份：退出程序，将 ZIP 解压到一个新的可写目录，再运行解压后的启动入口。不要覆盖正在运行的库。源码包不含 Python，因此恢复后仍需要可用的 Python。

## 验证与边界

```sh
python -m unittest discover -s tests -v
```

测试使用临时目录和虚构记录，覆盖空库初始化、双语搜索、查重、分组、打印状态、HTTP 附件访问、写入令牌和完整备份恢复。

核心程序曾在 Linux 与 Windows 11 环境进行验证；本公开版本的本地回归在 Linux 执行。Windows 10 尚未实测。仓库配置了 Linux / Windows CI，具体结果以 Actions 为准；CI 不等于 Windows 桌面交互或 Windows 10 兼容性实测。

这是本地工具，不是可部署到公网的多用户服务。当前不提供账号、远程协作、自动版本关系识别或 PDF 全文搜索。

## 发布与隐私

仓库以空库发布，不包含真实文献目录、论文 PDF、译文、纸本照片、下载记录、个人数据库或旧 Git 历史。个人数据目录被 `.gitignore` 排除；手工强制添加文件仍可能公开资料。

源码使用 MIT 许可证，见 [LICENSE](LICENSE)。用户自行放入的论文、附件与运行环境不因本项目许可证而改变其原有授权。
