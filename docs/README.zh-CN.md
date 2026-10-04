# release-fence 简体中文指南

release-fence 是 ZIP 发布包的质量检查工具。它确认必需文件是否存在、检查不应打包的路径，并生成按路径排序的 SHA-256 文件清单。运行时仅依赖 Python 3.10+ 标准库；不会解压到磁盘、执行包内代码或访问网络。

## 使用

在仓库根目录运行：

```sh
python -m pip install .
python examples/make_demo.py
release-fence check examples/demo.zip --policy examples/policy.json
release-fence scan examples/demo.zip > before.json
release-fence diff before.json before.json
```

`required` 是大小写敏感的完整相对文件路径，不是通配符。`forbidden` 使用 Python 的 `fnmatchcase`：`*` 可以匹配 `/` 和开头的点；`**` 没有特殊递归含义。比如 `*.pyc` 匹配任意深度的字节码文件。没有自动去掉顶层目录的行为。

`max_files` 默认 1000，`max_total_bytes` 默认 67108864，`max_member_bytes` 默认 16777216。字节数按实际解压数据计算。未知字段、重复 JSON 键、不合法的类型或路径会报错。没有内置语言配置，也不会猜测项目需要哪些文件。

退出码：0 表示完整扫描、检查通过或没有差异；1 表示 `check` 发现缺失/禁止路径，或 `diff` 发现内容变化；2 表示输入不合法、不支持的 ZIP 特性、资源限制或 I/O 错误。`scan` 记录路径违规但返回 0。超出大小限制会停止读取，不会输出不完整清单。

## 限制与解释

只支持普通 stored/deflated ZIP；不支持 TAR、ZIP64、加密、分卷、自解压前缀和符号链接。固定限制是压缩文件 64 MiB、中央目录 8 MiB、条目 10000 个。拒绝绝对路径、反斜杠、`..`、重复路径和作为父目录的普通文件。Unicode 不做规范化或大小写折叠。

文件记录和内容差异忽略时间戳、权限、压缩方式和空目录；显式目录条目仍可能改变禁止路径违规结果。`diff` 只比较普通文件的内容和长度，不比较策略违规。改名表现为删除加新增。这不是完整 ZIP 规范验证器，也不是恶意软件扫描、密钥检测或来源认证工具。对于不可信输入，请额外使用操作系统隔离和资源限制。

完整格式和保守解析规则见 [英文主文档](../README.md)。测试：`PYTHONPATH=src python -m unittest discover -s tests -v`。

CI 在 Linux 上测试 Python 3.10–3.13，在 Windows 和 macOS 上测试 Python 3.12。每个任务构建 wheel，在干净的临时虚拟环境中离线安装，并在源码目录之外运行完整测试。已安装的命令行工具还会验证 Unicode 成员名、带空格的路径、区分大小写的禁止规则，以及 scan/check/diff 的输出和退出码 0/1/2。测试只使用本地生成的合成数据；准备构建工具可能需要网络。

构建后可运行：`python .github/scripts/check_install.py dist/release_fence-0.1.0-py3-none-any.whl`。
