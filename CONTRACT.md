# 数据与接口契约

## 修订和观测

`RevisionRepository.save_network(network_id, revision, vertices, edges, faces)` 返回包含网络 ID、修订号和内容摘要的 `RevisionRef`。`get_revision(ref)` 读取该确切版本。网络 ID 和请求 ID 为非空 Unicode 文本。修订号与传感器 ID 接受整数或非空 Unicode 文本，整数和文本分别表示不同身份。复形显式提交全部顶点、无向边和实心三角面。单纯形的成员和集合均规范排序。每份修订最多 12 个顶点。缺失端点、退化单纯形及缺失面边界抛 `InvalidComplex`。重复接纳幂等，同身份异内容抛 `RevisionConflict`。未知引用或摘要不符抛 `UnknownRevision`。

`StudyService.freeze_study(request_id, samples)` 接受 1 至 16 个 `(time, RevisionRef)`，返回 `FrozenStudy`。时刻为有限数值或非空文本，使用原值及原单位。同一队列的数值时刻按数值大小排列，文本时刻按字典序排列。时刻严格递增。非法时刻或形状抛 `InvalidStudy`，未知引用抛 `UnknownRevision`，同一请求 ID 复用不同输入抛 `StudyConflict`。`get_study(study_id)` 固定读取，未知 ID 抛 `UnknownStudy`。每个相邻交集保留两侧来源，奇数位置是交集，偶数位置是采样。单采样只有位置 0。位置差没有物理时长单位。

## 分析和报告

`AnalysisService.analyze_study(study_id, request_id)` 返回 `PublishedArtifact`。分析负载包含 `study_id`、`positions`、按位置排列的 `summaries` 和完整的 `maps`。`components` 包含孤立点。`holes` 是 F2 上一维循环空间模二维边界的维数。每条关系从交集指向两侧采样之一。`source_dim` 和 `target_dim` 给定线性映射的定义域和值域维数，`columns` 的每个整数以低位到高位编码一列 F2 系数。坐标属于当次冻结分析中对应的位置。

`ReportService.create_report(analysis_id, request_id)` 返回固定报告。`positions` 保留来源，`intervals` 为按端点排序的 `[start, end, multiplicity]` 列表。端点包含在寿命内，允许位于交集，重数为正整数。空结果编码为 `[]`。`AnalysisError` 表示分析关系无效，`InvalidAnalysis` 表示报告不能消费指定成果。报告消费已冻结的关系图。读取和导出保留既有质量结论。

## 归档和交付

`ArchiveDatabase.open(path)` 创建或重开版本 1 的 SQLite 归档。重复打开保留全部数据。版本或结构不兼容抛 `SchemaMismatch`。使用上下文管理器可自动关闭。`ArtifactStore.read_artifact(id)` 返回独立对象，未知 ID 抛 `UnknownArtifact`，固定记录不一致抛 `ArtifactIntegrityError`。分析和报告的请求空间分别按成果类型划分。相同请求和内容重试返回原成果及稳定 `receipt`，同一身份对应异内容抛 `PublicationConflict`。事务失败传播原始存储异常，并撤销成果与回执。

`export_report(store, report_id, path)` 将固定报告、分析、队列和清单写入 ZIP。输出异常抛 `ExportError` 并清理本次临时文件。`verify_package(path)` 返回 `VerifiedPackage`，包含报告、来源和固定分析。它核对规范编码、摘要、成员和身份、确切父链、关系位置与维数以及区间的维数覆盖。验证失败统一抛 `PackageVerificationError`。校验使用包内信息，摘要提供内容完整性。
