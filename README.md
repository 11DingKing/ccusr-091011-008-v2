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

## 容器

```bash
docker build -t custody-service .
docker run --rm custody-service
```

## 盘点差异调查

盘点发现账实不符时，不直接改库存，而是发起调查单，全程留痕：

1. `POST /api/investigations/` 发起调查：自动记录盘点快照（系统值、发现值、快照时间）与责任范围（责任人、责任部门）。账实相符或同一货物存在调查中的单子时拒绝创建。
2. `POST /api/investigations/{id}/notes/` 追加调查记录：原因分析（reason）、证据材料（evidence）、复核意见（review），仅可追加，不可修改。调查期间物资照常收发，不做锁定。
3. `POST /api/investigations/{id}/close/` 批准结案（管理员，且不能是创建人）：结案时重新读取账面，检测基线是否因后续收发而变化，按快照重算差额并生成独立调整分录（`wh_stock_adjustment`）修正数量；三类记录齐全方可结案。
4. `POST /api/investigations/{id}/revoke/` 撤销结论（管理员）：生成反向冲回分录抵销调整，原结论与分录全部保留，不覆盖旧记录。调查中的单子可用 `POST /api/investigations/{id}/cancel/` 作废，不影响库存。
5. `GET /api/investigations/{id}/reconciliation/` 差异还原：输出发现值、系统值、后续收发变动、实际调整分录及勾稽校验（系统值 + 后续变动 + 调整合计 = 当前库存）。
