# 澄川传感网络质量归档

设备组提交网络修订，数据员确认闭包并保存明确的修订引用。分析员冻结采样队列，检查单版与交集上的连通性和孔洞，再从固定分析生成质量报告。补测人员使用报告的寿命区间及来源位置，也可脱离源归档核验交付包。

在项目根目录使用 Python 3.11 和标准库运行。

```sh
python3 -B -S verify.py
python3 -B -S demo.py
python3 -B -S -m unittest discover -s tests -v
```

演示在临时目录接纳两版各有一个孔洞的网络，保存分析与报告、更正源修订、重开归档，并在归档关闭后核验独立包。两个孔洞各有一个单点寿命。

```python
from delivery.database import ArchiveDatabase
from delivery.analysis_store import ArtifactStore
from network.revisions import RevisionRepository
from study.cohorts import StudyService
from topology.inclusions import AnalysisService
from quality.reports import ReportService
from exchange.export import export_report
from exchange.import_check import verify_package

with ArchiveDatabase.open('archive.sqlite') as db:
    revisions = RevisionRepository(db)
    ref = revisions.save_network('north', 1, [1, 2, 3], [(1, 2), (2, 3), (3, 1)], [])
    studies = StudyService(db)
    cohort = studies.freeze_study('morning', [(900, ref)])
    artifacts = ArtifactStore(db)
    analysis = AnalysisService(studies, artifacts).analyze_study(cohort.study_id, 'review')
    report = ReportService(artifacts).create_report(analysis.artifact_id, 'delivery')
    export_report(artifacts, report.artifact_id, 'quality.zip')

result = verify_package('quality.zip')
print(result.report.intervals)
```

接口的身份、位置、编码和错误语义见 [CONTRACT.md](CONTRACT.md)。
