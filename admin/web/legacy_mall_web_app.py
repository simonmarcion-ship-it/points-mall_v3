from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import json
import secrets
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "crawler"
CUSTOMER_DETAIL_EXCEL = DATA_DIR / "微盟客户详情_解析结果.xlsx"
CUSTOMER_LIST_EXCEL = DATA_DIR / "微盟客户数据_全部13776条.xlsx"
COUPON_EXCEL = DATA_DIR / "微盟客户优惠券明细_解析结果.xlsx"
STATE_JSON = BASE_DIR / "mall_web_state.json"


app = FastAPI(title="积分商城后台原型")

customers: list[dict[str, Any]] = []
customer_by_wid: dict[str, dict[str, Any]] = {}
coupons: list[dict[str, Any]] = []
operation_logs: list[dict[str, Any]] = []
coupon_templates: list[dict[str, Any]] = []


class IssueCouponRequest(BaseModel):
    wid: str
    template_id: str
    quantity: int = 1
    valid_days: int = 30
    operator: str = "员工"
    remark: str = ""


class RedeemCouponRequest(BaseModel):
    code: str
    operator: str = "员工"
    remark: str = ""


def clean_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def records_from_excel(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    df = pd.read_excel(path, dtype=str)
    return [
        {str(key): clean_value(value) for key, value in row.items()}
        for row in df.to_dict("records")
    ]


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def build_coupon_templates(source_coupons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    template_map: dict[str, dict[str, Any]] = {}
    for row in source_coupons:
        template_id = str(row.get("券模板ID") or "")
        if not template_id:
            continue
        if template_id not in template_map:
            template_map[template_id] = {
                "template_id": template_id,
                "name": row.get("券名称") or "未命名优惠券",
                "type": row.get("券类型描述") or row.get("券类型") or "优惠券",
                "rule": row.get("使用规则") or row.get("优惠说明") or "",
                "enabled": True,
            }
    if template_map:
        return list(template_map.values())
    return [
        {
            "template_id": "manual_cash_10",
            "name": "手工补发券",
            "type": "通用券",
            "rule": "线下人工确认后使用",
            "enabled": True,
        }
    ]


def normalize_coupon(row: dict[str, Any], source: str) -> dict[str, Any]:
    status_desc = str(row.get("状态描述") or row.get("状态") or "").strip()
    using_time = row.get("使用时间")
    code = str(row.get("券码") or "")
    status = "unused"
    if using_time:
        status = "used"
    if "已使用" in status_desc or "使用" == status_desc:
        status = "used"
    if "过期" in status_desc:
        status = "expired"
    if "作废" in status_desc:
        status = "voided"

    return {
        "wid": str(row.get("客户编号 wid") or ""),
        "template_id": str(row.get("券模板ID") or ""),
        "template_name": row.get("券名称") or "未命名优惠券",
        "type": row.get("券类型描述") or row.get("券类型") or "",
        "status": status,
        "status_text": status_desc or status,
        "receive_time": row.get("领取时间"),
        "used_time": using_time,
        "code": code or f"NO_CODE_{secrets.token_hex(6)}",
        "valid_period": row.get("有效期"),
        "valid_start": row.get("有效开始时间戳"),
        "valid_end": row.get("有效结束时间戳"),
        "phone": row.get("领取手机号"),
        "source": source,
        "remark": row.get("优惠说明") or "",
    }


def save_state() -> None:
    state = {
        "coupons": [row for row in coupons if row.get("source") == "manual"],
        "operation_logs": operation_logs,
    }
    STATE_JSON.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not STATE_JSON.exists():
        return [], []
    state = json.loads(STATE_JSON.read_text(encoding="utf-8"))
    return state.get("coupons", []), state.get("operation_logs", [])


def load_data() -> None:
    global customers, customer_by_wid, coupons, operation_logs, coupon_templates

    detail_rows = records_from_excel(CUSTOMER_DETAIL_EXCEL)
    list_rows = records_from_excel(CUSTOMER_LIST_EXCEL)
    coupon_rows = records_from_excel(COUPON_EXCEL)
    manual_coupons, saved_logs = load_state()

    if detail_rows:
        customers = detail_rows
        for row in customers:
            row["客户编号 wid"] = str(row.get("客户编号 wid") or "")
    else:
        customers = [
            {
                "客户编号 wid": str(row.get("wid") or ""),
                "手机号": row.get("phone"),
                "昵称": row.get("nickname") or row.get("name"),
                "成为客户时间": row.get("becomeCustomerTime"),
                "客户状态": row.get("customerStatus"),
                "是否黑名单": row.get("blackUser"),
                "可用积分": row.get("point"),
                "累计积分": row.get("totalPoint"),
                "可用余额": row.get("balance"),
                "累计余额": row.get("totalBalance"),
                "归属门店": row.get("belongVidCode") or row.get("belongVid"),
            }
            for row in list_rows
        ]

    customer_by_wid = {str(row.get("客户编号 wid")): row for row in customers if row.get("客户编号 wid")}
    coupons = [normalize_coupon(row, "old_mall") for row in coupon_rows]
    coupons.extend(manual_coupons)
    operation_logs = saved_logs
    coupon_templates = build_coupon_templates(coupon_rows)


def public_customer(row: dict[str, Any]) -> dict[str, Any]:
    wid = str(row.get("客户编号 wid") or "")
    related = [coupon for coupon in coupons if str(coupon.get("wid")) == wid]
    return {
        "wid": wid,
        "phone": row.get("手机号"),
        "nickname": row.get("昵称"),
        "level": row.get("等级名称") or row.get("会员卡"),
        "store": row.get("归属门店"),
        "point": row.get("可用积分"),
        "total_point": row.get("累计积分"),
        "balance": row.get("可用余额"),
        "coupon_count": len(related),
        "unused_coupon_count": sum(1 for item in related if item.get("status") == "unused"),
        "black_user": row.get("是否黑名单"),
        "status": row.get("客户状态"),
    }


@app.on_event("startup")
def startup() -> None:
    load_data()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


@app.get("/api/summary")
def summary() -> dict[str, Any]:
    return {
        "customers": len(customers),
        "coupons": len(coupons),
        "unused_coupons": sum(1 for row in coupons if row.get("status") == "unused"),
        "used_coupons": sum(1 for row in coupons if row.get("status") == "used"),
        "templates": len(coupon_templates),
        "logs": len(operation_logs),
    }


@app.get("/api/customers")
def search_customers(q: str = "", limit: int = 50) -> dict[str, Any]:
    keyword = q.strip().lower()
    result = []
    for row in customers:
        target = " ".join(
            str(row.get(key) or "")
            for key in ["客户编号 wid", "手机号", "昵称", "会员卡", "归属门店"]
        ).lower()
        if not keyword or keyword in target:
            result.append(public_customer(row))
        if len(result) >= limit:
            break
    return {"items": result, "total": len(result)}


@app.get("/api/customers/{wid}")
def customer_detail(wid: str) -> dict[str, Any]:
    row = customer_by_wid.get(str(wid))
    if not row:
        raise HTTPException(status_code=404, detail="客户不存在")
    related = [coupon for coupon in coupons if str(coupon.get("wid")) == str(wid)]
    return {"customer": row, "summary": public_customer(row), "coupons": related}


@app.get("/api/templates")
def templates() -> dict[str, Any]:
    return {"items": coupon_templates}


@app.post("/api/coupons/issue")
def issue_coupon(req: IssueCouponRequest) -> dict[str, Any]:
    if req.quantity < 1 or req.quantity > 100:
        raise HTTPException(status_code=400, detail="发券数量必须在 1-100 之间")
    if req.valid_days < 1 or req.valid_days > 3650:
        raise HTTPException(status_code=400, detail="有效天数必须在 1-3650 之间")
    customer = customer_by_wid.get(str(req.wid))
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    template = next((item for item in coupon_templates if item["template_id"] == req.template_id), None)
    if not template:
        raise HTTPException(status_code=404, detail="券模板不存在")

    issued = []
    start = datetime.now()
    end = start + timedelta(days=req.valid_days)
    for _ in range(req.quantity):
        coupon = {
            "wid": str(req.wid),
            "template_id": template["template_id"],
            "template_name": template["name"],
            "type": template["type"],
            "status": "unused",
            "status_text": "未使用",
            "receive_time": now_text(),
            "used_time": None,
            "code": f"TX{start.strftime('%Y%m%d')}{secrets.token_hex(4).upper()}",
            "valid_period": f"{start:%Y-%m-%d} 至 {end:%Y-%m-%d}",
            "valid_start": start.isoformat(),
            "valid_end": end.isoformat(),
            "phone": customer.get("手机号"),
            "source": "manual",
            "remark": req.remark,
        }
        coupons.append(coupon)
        issued.append(coupon)

    operation_logs.insert(
        0,
        {
            "time": now_text(),
            "operator": req.operator,
            "action": "发券",
            "wid": str(req.wid),
            "target": template["name"],
            "quantity": req.quantity,
            "remark": req.remark,
        },
    )
    save_state()
    return {"issued": issued}


@app.post("/api/coupons/redeem")
def redeem_coupon(req: RedeemCouponRequest) -> dict[str, Any]:
    code = req.code.strip()
    coupon = next((item for item in coupons if str(item.get("code")) == code), None)
    if not coupon:
        raise HTTPException(status_code=404, detail="券码不存在")
    if coupon.get("status") != "unused":
        raise HTTPException(status_code=400, detail=f"该券当前状态不可核销: {coupon.get('status_text')}")

    coupon["status"] = "used"
    coupon["status_text"] = "已核销"
    coupon["used_time"] = now_text()
    operation_logs.insert(
        0,
        {
            "time": now_text(),
            "operator": req.operator,
            "action": "核销",
            "wid": str(coupon.get("wid")),
            "target": code,
            "quantity": 1,
            "remark": req.remark,
        },
    )
    save_state()
    return {"coupon": coupon}


@app.get("/api/logs")
def logs(limit: int = 100) -> dict[str, Any]:
    return {"items": operation_logs[:limit]}


HTML = r'''
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>积分商城后台</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; color: #1f2937; background: #f5f7fb; }
    header { height: 56px; background: #ffffff; border-bottom: 1px solid #dfe5ef; display: flex; align-items: center; justify-content: space-between; padding: 0 24px; position: sticky; top: 0; z-index: 2; }
    h1 { font-size: 18px; margin: 0; font-weight: 700; }
    .operator { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #5b6472; }
    input, select, textarea, button { font: inherit; }
    input, select, textarea { border: 1px solid #cfd8e6; border-radius: 6px; background: #fff; padding: 8px 10px; outline: none; }
    input:focus, select:focus, textarea:focus { border-color: #2563eb; box-shadow: 0 0 0 2px rgba(37,99,235,.12); }
    button { border: 0; border-radius: 6px; padding: 8px 12px; background: #2563eb; color: #fff; cursor: pointer; }
    button.secondary { background: #e8edf5; color: #1f2937; }
    button.danger { background: #c2410c; }
    main { display: grid; grid-template-columns: 260px 1fr; min-height: calc(100vh - 56px); }
    nav { border-right: 1px solid #dfe5ef; background: #fff; padding: 16px; }
    nav button { width: 100%; text-align: left; margin-bottom: 8px; background: transparent; color: #344054; }
    nav button.active { background: #eaf1ff; color: #1d4ed8; }
    .content { padding: 20px; }
    .stats { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 12px; margin-bottom: 16px; }
    .stat { background: #fff; border: 1px solid #dfe5ef; border-radius: 8px; padding: 14px; }
    .stat .label { color: #667085; font-size: 12px; }
    .stat .value { font-size: 24px; font-weight: 700; margin-top: 6px; }
    .panel { background: #fff; border: 1px solid #dfe5ef; border-radius: 8px; margin-bottom: 16px; overflow: hidden; }
    .panel-head { padding: 14px 16px; border-bottom: 1px solid #e6ebf2; display: flex; justify-content: space-between; align-items: center; gap: 12px; }
    .panel-title { font-weight: 700; }
    .panel-body { padding: 16px; }
    .toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 10px 12px; border-bottom: 1px solid #edf1f6; text-align: left; vertical-align: middle; }
    th { color: #667085; font-weight: 600; background: #fbfcfe; }
    tr:hover td { background: #f8fbff; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .kv { display: grid; grid-template-columns: 120px 1fr; gap: 8px 12px; font-size: 13px; }
    .key { color: #667085; }
    .tag { display: inline-flex; align-items: center; height: 24px; padding: 0 8px; border-radius: 999px; font-size: 12px; background: #eef2f7; color: #344054; }
    .tag.unused { background: #ecfdf3; color: #027a48; }
    .tag.used { background: #eff4ff; color: #175cd3; }
    .tag.expired, .tag.voided { background: #fef3f2; color: #b42318; }
    .hidden { display: none; }
    .message { min-height: 22px; color: #475467; font-size: 13px; }
    .error { color: #b42318; }
    .ok { color: #027a48; }
    @media (max-width: 900px) { main { grid-template-columns: 1fr; } nav { display: flex; overflow-x: auto; gap: 8px; } nav button { width: auto; white-space: nowrap; } .stats { grid-template-columns: repeat(2, 1fr); } .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <h1>积分商城后台</h1>
    <div class="operator">操作人 <input id="operator" value="员工" /></div>
  </header>
  <main>
    <nav>
      <button class="active" data-view="customers">客户管理</button>
      <button data-view="issue">发券</button>
      <button data-view="redeem">核销</button>
      <button data-view="templates">券模板</button>
      <button data-view="logs">操作记录</button>
    </nav>
    <section class="content">
      <div class="stats" id="stats"></div>

      <section id="view-customers" class="view">
        <div class="panel">
          <div class="panel-head">
            <div class="panel-title">客户查询</div>
            <div class="toolbar">
              <input id="search" placeholder="手机号 / wid / 昵称" />
              <button onclick="searchCustomers()">查询</button>
            </div>
          </div>
          <div class="panel-body">
            <table><thead><tr><th>wid</th><th>手机号</th><th>昵称</th><th>等级</th><th>可用积分</th><th>可用券</th><th>操作</th></tr></thead><tbody id="customerRows"></tbody></table>
          </div>
        </div>
        <div class="grid">
          <div class="panel"><div class="panel-head"><div class="panel-title">客户详情</div></div><div class="panel-body" id="customerDetail">请选择客户</div></div>
          <div class="panel"><div class="panel-head"><div class="panel-title">客户券</div></div><div class="panel-body"><table><thead><tr><th>券码</th><th>名称</th><th>状态</th><th>有效期</th></tr></thead><tbody id="customerCoupons"></tbody></table></div></div>
        </div>
      </section>

      <section id="view-issue" class="view hidden">
        <div class="panel">
          <div class="panel-head"><div class="panel-title">给客户发券</div></div>
          <div class="panel-body">
            <div class="toolbar">
              <input id="issueWid" placeholder="客户 wid" />
              <select id="issueTemplate"></select>
              <input id="issueQuantity" type="number" min="1" max="100" value="1" />
              <input id="issueDays" type="number" min="1" value="30" />
              <input id="issueRemark" placeholder="备注" />
              <button onclick="issueCoupon()">发券</button>
            </div>
            <p id="issueMessage" class="message"></p>
          </div>
        </div>
      </section>

      <section id="view-redeem" class="view hidden">
        <div class="panel">
          <div class="panel-head"><div class="panel-title">核销券</div></div>
          <div class="panel-body">
            <div class="toolbar">
              <input id="redeemCode" placeholder="输入券码" />
              <input id="redeemRemark" placeholder="备注" />
              <button class="danger" onclick="redeemCoupon()">确认核销</button>
            </div>
            <p id="redeemMessage" class="message"></p>
          </div>
        </div>
      </section>

      <section id="view-templates" class="view hidden">
        <div class="panel"><div class="panel-head"><div class="panel-title">券模板</div></div><div class="panel-body"><table><thead><tr><th>模板ID</th><th>名称</th><th>类型</th><th>规则</th></tr></thead><tbody id="templateRows"></tbody></table></div></div>
      </section>

      <section id="view-logs" class="view hidden">
        <div class="panel"><div class="panel-head"><div class="panel-title">操作记录</div><button class="secondary" onclick="loadLogs()">刷新</button></div><div class="panel-body"><table><thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>wid</th><th>对象</th><th>数量</th><th>备注</th></tr></thead><tbody id="logRows"></tbody></table></div></div>
      </section>
    </section>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    let selectedWid = '';

    async function api(path, options = {}) {
      const res = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '请求失败');
      return data;
    }

    function statusTag(status, text) { return `<span class="tag ${status}">${text || status}</span>`; }
    function safe(value) { return value === null || value === undefined || value === '' ? '-' : String(value); }

    async function loadSummary() {
      const data = await api('/api/summary');
      $('stats').innerHTML = [
        ['客户', data.customers], ['优惠券', data.coupons], ['未使用券', data.unused_coupons], ['已核销券', data.used_coupons], ['模板', data.templates]
      ].map(([label, value]) => `<div class="stat"><div class="label">${label}</div><div class="value">${value}</div></div>`).join('');
    }

    async function searchCustomers() {
      const data = await api('/api/customers?q=' + encodeURIComponent($('search').value));
      $('customerRows').innerHTML = data.items.map(row => `<tr><td>${safe(row.wid)}</td><td>${safe(row.phone)}</td><td>${safe(row.nickname)}</td><td>${safe(row.level)}</td><td>${safe(row.point)}</td><td>${safe(row.unused_coupon_count)} / ${safe(row.coupon_count)}</td><td><button class="secondary" onclick="selectCustomer('${row.wid}')">查看</button></td></tr>`).join('');
    }

    async function selectCustomer(wid) {
      selectedWid = wid;
      $('issueWid').value = wid;
      const data = await api('/api/customers/' + encodeURIComponent(wid));
      const c = data.customer;
      $('customerDetail').innerHTML = `<div class="kv">
        <div class="key">客户编号</div><div>${safe(c['客户编号 wid'])}</div>
        <div class="key">手机号</div><div>${safe(c['手机号'])}</div>
        <div class="key">昵称</div><div>${safe(c['昵称'])}</div>
        <div class="key">等级</div><div>${safe(c['等级名称'] || c['会员卡'])}</div>
        <div class="key">可用积分</div><div>${safe(c['可用积分'])}</div>
        <div class="key">累计积分</div><div>${safe(c['累计积分'])}</div>
        <div class="key">可用余额</div><div>${safe(c['可用余额'])}</div>
        <div class="key">归属门店</div><div>${safe(c['归属门店'])}</div>
      </div>`;
      $('customerCoupons').innerHTML = data.coupons.map(row => `<tr><td>${safe(row.code)}</td><td>${safe(row.template_name)}</td><td>${statusTag(row.status, row.status_text)}</td><td>${safe(row.valid_period)}</td></tr>`).join('');
    }

    async function loadTemplates() {
      const data = await api('/api/templates');
      $('issueTemplate').innerHTML = data.items.map(row => `<option value="${row.template_id}">${row.name}</option>`).join('');
      $('templateRows').innerHTML = data.items.map(row => `<tr><td>${safe(row.template_id)}</td><td>${safe(row.name)}</td><td>${safe(row.type)}</td><td>${safe(row.rule)}</td></tr>`).join('');
    }

    async function issueCoupon() {
      const msg = $('issueMessage');
      msg.className = 'message'; msg.textContent = '处理中...';
      try {
        const data = await api('/api/coupons/issue', {method: 'POST', body: JSON.stringify({wid: $('issueWid').value, template_id: $('issueTemplate').value, quantity: Number($('issueQuantity').value), valid_days: Number($('issueDays').value), operator: $('operator').value, remark: $('issueRemark').value})});
        msg.className = 'message ok'; msg.textContent = `发券成功：${data.issued.map(x => x.code).join('、')}`;
        await loadSummary(); if ($('issueWid').value) await selectCustomer($('issueWid').value);
      } catch (err) { msg.className = 'message error'; msg.textContent = err.message; }
    }

    async function redeemCoupon() {
      const msg = $('redeemMessage');
      msg.className = 'message'; msg.textContent = '处理中...';
      try {
        const data = await api('/api/coupons/redeem', {method: 'POST', body: JSON.stringify({code: $('redeemCode').value, operator: $('operator').value, remark: $('redeemRemark').value})});
        msg.className = 'message ok'; msg.textContent = `核销成功：${data.coupon.template_name}，客户 ${data.coupon.wid}`;
        await loadSummary(); if (selectedWid) await selectCustomer(selectedWid);
      } catch (err) { msg.className = 'message error'; msg.textContent = err.message; }
    }

    async function loadLogs() {
      const data = await api('/api/logs');
      $('logRows').innerHTML = data.items.map(row => `<tr><td>${safe(row.time)}</td><td>${safe(row.operator)}</td><td>${safe(row.action)}</td><td>${safe(row.wid)}</td><td>${safe(row.target)}</td><td>${safe(row.quantity)}</td><td>${safe(row.remark)}</td></tr>`).join('');
    }

    document.querySelectorAll('nav button').forEach(btn => btn.addEventListener('click', () => {
      document.querySelectorAll('nav button').forEach(x => x.classList.remove('active'));
      btn.classList.add('active');
      document.querySelectorAll('.view').forEach(x => x.classList.add('hidden'));
      $('view-' + btn.dataset.view).classList.remove('hidden');
      if (btn.dataset.view === 'logs') loadLogs();
    }));

    loadSummary(); loadTemplates(); searchCustomers();
  </script>
</body>
</html>
'''
