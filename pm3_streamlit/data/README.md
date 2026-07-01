# data/

运行时数据文件。被 `.gitignore` 大量排除（每个子目录通常只保留结构，不保留内容）。

| 文件/目录             | 来源                                | 是否进 git | 备注 |
| --------------------- | ----------------------------------- | ---------- | ---- |
| `protein.txt`         | 项目自带                            | ✅ 进        | 蛋白缩写映射，启动时由 `app/core/query.py` 读取 |
| `xml_papers/`         | `python -m app.data_io.download_papers` 的输出 | ❌ 不进      | 运行时下载的 BioC XML；目录保留以便挂载 |
| `pdf_convert/`        | MinerU 转换示例（PubMed 23689641）  | ✅ 进（少量示例） | 用于演示 `app.mineru` 客户端的产物格式 |

> Docker 镜像中只 `COPY data/protein.txt ./data/protein.txt`，其余数据不进镜像。运行期产生的上传临时文件写到 `tempfile.gettempdir()`，不落盘到这里。
