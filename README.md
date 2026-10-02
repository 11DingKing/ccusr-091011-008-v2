# 监管物资保管服务

该项目为监管仓、证物室和受控物资保管点提供服务端 API，覆盖人员授权、物资分类、批次登记、收发记录、审批、预警、审计日志与统计报表。数据保存在 SQLite，所有测试和接口验收均可在单个 Linux 应用容器内离线完成。

## 运行环境

- Python 3.11
- Django REST Framework
- SQLite

## 安装与初始化

```bash
python -m pip install -r backend/requirements.txt
cd backend
python manage.py migrate --run-syncdb
```

## 测试

```bash
cd backend
pytest -q
```

## 编译检查

```bash
python -m compileall -q backend
```

## API 验收

```bash
cd backend
python manage.py migrate --run-syncdb
python manage.py shell -c "from rest_framework.test import APIClient; from apps.authentication.models import User; u=User.objects.create_user('smoke','safe-pass',role='admin'); c=APIClient(); r=c.post('/api/auth/login/',{'username':'smoke','password':'safe-pass'},format='json'); print(r.status_code, bool(r.json()['data']['token']))"
```

## 盘点差异调查流程

季度盘点发现数量不一致时，不再直接改库存，统一走差异调查单（`Investigation`），全部库存变动（含调整）以只追加的库存流水分录（`StockLedgerEntry`）留痕：

1. **立案** `POST /api/investigations/`：冻结盘点快照（发现值、系统值、初始差额、流水基线 ID）与责任范围（责任范围、责任人、盘点区域）。
2. **调查** `POST /api/investigations/<id>/records/`：只追加地收集差异原因（`reason`）、证据（`evidence`，可带附件引用）与复核意见（`review`），记录不提供编辑/删除。
3. **调查期间物资正常收发**：`POST /api/stock-in/`、`POST /api/stock-out/` 不被锁定；每笔收发都登记带符号分录并连续回填结余。
4. **批准结案** `POST /api/investigations/<id>/approve/`：
   - 行锁货物，检测流水基线是否已被后续收发推进（`baseline_changed`）；
   - 按结案时点系统值**重新计算差额**（发现值快照 − 当前系统值），不沿用立案时的初始差额；
   - 以**独立调整分录**（`entry_type=adjustment`，引用调查单）修正数量；重算差额为 0 时不产生调整分录。
   - 批准前必须已记录差异原因与复核意见；`reject/` 则记录驳回意见且不动库存。
5. **撤销结论** `POST /api/investigations/<id>/reverse/`（必填原因）：只追加一条反向冲回分录（`adjustment_reversal`）并回退库存，原批准意见、原调整分录与既有调查记录全部保留、不被覆盖，撤销原因另行追加留痕。
6. **关系还原** `GET /api/investigations/<id>/reconstruction/`：返回盘点发现值、系统值快照、调查期间净变动、结案时系统值、重算差额、原始调整/冲回/净调整与结案后收发，并校验恒等式：
   - `系统快照 + 期间净变动 = 结案前系统值`
   - `结案前系统值 + 调整 = 盘点发现值`
   - `结案前系统值 + 净调整 + 结案后收发 = 当前系统值`

单货物流水可经 `GET /api/goods/<goods_id>/ledger/` 查询。

## 容器

```bash
docker build -t custody-service .
docker run --rm custody-service
```
