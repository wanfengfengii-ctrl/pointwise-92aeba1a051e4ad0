# 接纳现场交付

补测组在同一归档复核多个现场交付的孔洞报告。接纳后的冻结分析可以作为本地报告的父项。已有修订、队列、分析、报告与包格式见 [CONTRACT.md](CONTRACT.md)。

## 接口

- `exchange.import_check.accept_package(store, source_id, path)` 接受一个 `ArtifactStore`、调用方指定的稳定来源 ID 和现有 `export_report` 生成的 V1 ZIP 路径。
- `store.find_acceptance(source_id, report_request_id)` 查询已完成接纳的回执，未接纳返回 `None`。
- 两个入口返回的回执均可按值比较，字段为 `source_id`、`report_request_id`、`study_id`、`analysis_id`、`report_id`。后三项使用包内原始 ID。来源 ID 和报告请求号沿用 V1 非空文本规则，保留原值。非法文本抛 `ValueError`。

## 接纳与本地出具

验包职责沿用 V1 校验并向归档交接同一次校验所确认的队列、分析和报告记录。接纳使用该批记录。来源由调用方指定，ZIP 格式沿用 V1。

归档对三个层级分别维护 `(source_id, kind, request_id)` 到原始 ID 的绑定，`kind` 分别为 `study`、`analysis`、`report`，请求号取对应成员的原始值。同键同成果可复用，同键异成果抛 `PublicationConflict`。同一来源重投同一报告，返回原回执。另一个来源可使用相同请求号，也可交付同一份成果并取得自己的回执。本地冻结与发布的请求空间独立，继续按 V1 裁决。来源回执由 `find_acceptance` 查询，本地回执由原 `find_receipt` 查询。

相同原始 ID 复用同一份固定成果，也适用于来件和本地成果的 ID 恰好相同的情形。接纳在同一事务提交三项记录、来源绑定和回执。验包失败沿用 `PackageVerificationError`，来源冲突或存储失败撤销整次接纳中的新增状态。提交前失败可用现有 `ArtifactStore` 的 `before_commit` 回调核验。撤掉故障后，同一来件可重试。

关闭并重开后，按原 ID 使用 `StudyService.get_study` 和 `ArtifactStore.read_artifact` 读取接纳成果。`ReportService.create_report` 可用已接纳的原分析 ID 出具本地报告。`export_report` 可导出原报告或本地新报告，且 `verify_package` 可核对两者的 V1 包。原报告的三个规范成员保持原身份及内容，本地新报告引用确切的原分析 ID 和队列 ID。接纳范围是来件内的冻结成果及回执，源修订仍由原归档管理。已有 V1 归档须可重开并继续按原接口读写。

## 来件与预期

`python3 -B -S intake_examples.py` 用现有 V1 发布和导出入口生成并校验样例，输出手算报告及成员 ID。测试中可调用 `write_fixtures(directory)` 获得按下表名称索引的 ZIP 路径。请使用空样例目录。所有有效包均在时刻 900 采样一次，使用同一组顶点和三条边。空心三角有一个 `[0,0,1]` 寿命，实心三角没有孔洞。

| 来件 | 队列请求 | 分析请求 | 报告请求 | 手算寿命 |
| --- | --- | --- | --- | --- |
| `a` | `morning` | `morning` | `morning` | `[[0,0,1]]` |
| `followup` | `morning` | `morning` | `followup` | `[[0,0,1]]` |
| `b` | `morning` | `morning` | `morning` | `[]` |
| `study_conflict` | `morning` | `other-analysis` | `study-conflict` | `[]` |
| `analysis_conflict` | `other-study` | `morning` | `analysis-conflict` | `[]` |
| `report_conflict` | `other-study` | `other-analysis` | `morning` | `[]` |

`a` 与 `followup` 共享队列及分析。先以来源 A 接纳 `a` 后，分别以 A 单独提交三个冲突变体，各自在对应层级冲突。`damaged` 的队列成员与清单摘要不符。

以下调用展示新增接口完成后的结果。`directory` 为本次样例工作目录，接收库尚未出具本地 `morning` 报告。

```python
from pathlib import Path

from delivery.analysis_store import ArtifactStore
from delivery.database import ArchiveDatabase
from exchange.export import export_report
from exchange.import_check import accept_package, verify_package
from intake_examples import write_fixtures
from quality.reports import ReportService

root = Path(directory)
paths = write_fixtures(root / 'packages')
archive = root / 'receiver.sqlite'
with ArchiveDatabase.open(archive) as db:
    store = ArtifactStore(db)
    a = accept_package(store, 'A', paths['a'])
    b = accept_package(store, 'B', paths['b'])
    followup = accept_package(store, 'A', paths['followup'])
    assert a.report_request_id == b.report_request_id == 'morning'
    assert a.analysis_id == followup.analysis_id
    assert a.analysis_id != b.analysis_id
with ArchiveDatabase.open(archive) as db:
    store = ArtifactStore(db)
    assert store.find_acceptance('A', 'morning') == a
    report = ReportService(store).create_report(a.analysis_id, 'morning')
    assert report.payload['intervals'] == [[0, 0, 1]]
    original_path = export_report(store, a.report_id, root / 'original.zip')
    local_path = export_report(store, report.artifact_id, root / 'local.zip')
assert verify_package(original_path).report_id == a.report_id
assert verify_package(local_path).analysis.study_id == a.study_id
```

## 核验与演示

沿用 `.pointwise-runtime.json` 的版本 1 与 `cli` 类型。`setup` 为参数数组列表，`verify` 和 `demo` 各为一条命令的参数数组。完成后，核验入口运行全部原回归及接纳业务核验，失败返回非零。演示入口用实际来件展示异源同名、共享父项，以及重开后从指定原分析重出并核验报告。
