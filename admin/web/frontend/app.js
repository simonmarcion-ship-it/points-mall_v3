const $ = (id) => document.getElementById(id);
let selectedWid = '';
let customerPage = 1;
let customerTotal = 0;
let selectedCustomerCoupons = [];
let customerLookupTimer = null;
let issueLookupRows = [];
let newCustomerLookupTimer = null;
let newCustomerCargeerRows = [];
let contextCouponIndex = null;
let currentAdminProfile = {};
let customerListScrollY = 0;

function scrollWindowTop() {
  requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: 'auto' }));
}

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  const contentType = res.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    const text = await res.text();
    throw new Error(text.startsWith('<') ? '服务返回了页面，请刷新后重新登录' : text || '请求失败');
  }
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || '请求失败');
  return data;
}

function showLogin() {
  $('loginView').classList.remove('hidden');
  $('appView').classList.add('hidden');
  showLoginPanel();
}

function showApp(username, profile = {}) {
  currentAdminProfile = profile || {};
  const displayName = profile.name || profile.display_name || username;
  $('currentUser').textContent = safe(displayName);
  $('currentStore').textContent = safe(profile.store_name);
  $('operator').value = displayName || username;
  updateIssueStoreScopeLabels();
  $('loginView').classList.add('hidden');
  $('appView').classList.remove('hidden');
}

function updateIssueStoreScopeLabels() {
  const currentOption = document.querySelector('#issueUsableStoreScope option[value="current"]');
  const customerOption = document.querySelector('#issueUsableStoreScope option[value="customer_store"]');
  if (currentOption) {
    currentOption.textContent = currentAdminProfile.store_name || '当前登录人员所属门店';
  }
  if (customerOption) {
    const customerStore = $('issueStore') ? $('issueStore').value.trim() : '';
    customerOption.textContent = customerStore ? `客户归属门店（${customerStore}）` : '客户归属门店';
  }
}

async function login(event) {
  event.preventDefault();
  const msg = $('loginMessage');
  msg.className = 'message';
  msg.textContent = '登录中...';
  try {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username: $('loginUsername').value, password: $('loginPassword').value }),
    });
    msg.textContent = '';
    showApp(data.username, data.profile || {});
    await bootstrapApp();
  } catch (err) {
    msg.className = 'message error';
    msg.textContent = err.message;
  }
}

async function logout() {
  await api('/api/auth/logout', { method: 'POST', body: '{}' });
  showLogin();
}

function safe(value) {
  return value === null || value === undefined || value === '' ? '-' : String(value);
}

function html(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function showRegisterPanel() {
  document.querySelector('#loginView .login-panel').classList.add('hidden');
  $('registerPanel').classList.remove('hidden');
  $('registerMessage').textContent = '';
  loadRegisterStores().catch((err) => {
    $('registerMessage').className = 'message error';
    $('registerMessage').textContent = err.message;
  });
}

function showLoginPanel() {
  const loginPanel = document.querySelector('#loginView .login-panel');
  if (loginPanel) loginPanel.classList.remove('hidden');
  if ($('registerPanel')) $('registerPanel').classList.add('hidden');
}

async function loadRegisterStores() {
  const data = await api('/api/auth/register-options');
  $('registerStore').innerHTML = (data.stores || [])
    .map((row) => `<option value="${html(row.id)}">${html(row.name)}</option>`)
    .join('');
}

async function registerAdmin(event) {
  event.preventDefault();
  const msg = $('registerMessage');
  msg.className = 'message';
  msg.textContent = '注册中...';
  try {
    const data = await api('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({
        phone: $('registerPhone').value,
        name: $('registerName').value,
        store_id: $('registerStore').value,
        password: $('registerPassword').value,
        invite_code: $('registerInviteCode').value,
      }),
    });
    msg.className = 'message ok';
    msg.textContent = '注册成功，请登录';
    $('loginUsername').value = data.username || $('registerPhone').value;
    $('loginPassword').value = '';
    showLoginPanel();
    $('loginMessage').className = 'message ok';
    $('loginMessage').textContent = '注册成功，请使用手机号和密码登录';
  } catch (err) {
    msg.className = 'message error';
    msg.textContent = err.message;
  }
}

function formatDateTime(value) {
  const text = safe(value);
  if (text === '-') return '-';
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return text;
  const yyyy = parsed.getFullYear();
  const mm = String(parsed.getMonth() + 1).padStart(2, '0');
  const dd = String(parsed.getDate()).padStart(2, '0');
  const hh = String(parsed.getHours()).padStart(2, '0');
  const mi = String(parsed.getMinutes()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
}

function formatGender(value) {
  const text = safe(value);
  return { '0': '未知', '1': '男', '2': '女' }[text] || text;
}

function formatCustomerStatus(value) {
  const text = safe(value);
  return { '1': '正常' }[text] || text;
}

function formatBool(value) {
  const text = safe(value);
  return { True: '是', False: '否', true: '是', false: '否' }[text] || text;
}

function formatVin(value) {
  const text = safe(value);
  if (text === '-') return '-';
  const normalized = normalizeVin(text);
  return isValidVin(normalized) ? text : `${text}（疑似非车架号）`;
}

function normalizeVin(value) {
  return String(value || '').replace(/\s+/g, '').toUpperCase();
}

function isValidVin(value) {
  return /^[A-HJ-NPR-Z0-9]{17}$/.test(value);
}

function statusTag(status, text) {
  return `<span class="tag ${status}">${safe(text || status)}</span>`;
}

function normalizeCouponStatus(row) {
  const status = String(row.status || '').toLowerCase();
  const text = String(row.status_text || '');
  const validEnd = row.valid_end ? new Date(row.valid_end) : null;
  if (status === 'used' || text.includes('已使用') || text.includes('已核销') || text === '使用') return 'used';
  if (status === 'expired' || text.includes('过期')) return 'expired';
  if (status === 'voided' || text.includes('作废') || text.includes('失效')) return 'voided';
  if (validEnd && !Number.isNaN(validEnd.getTime()) && validEnd < new Date()) return 'expired';
  if (status === 'unused' || text.includes('未使用') || text.includes('可用')) return 'unused';
  return status || 'unknown';
}

async function loadSummary() {
  const data = await api('/api/summary');
  $('stats').innerHTML = [
    ['客户', data.customers],
    ['优惠券', data.coupons],
    ['未使用券', data.unused_coupons],
    ['已核销券', data.used_coupons],
    ['模板', data.templates],
  ].map(([label, value]) => `<div class="stat"><div class="label">${label}</div><div class="value">${value}</div></div>`).join('');
}

function customerQueryParams() {
  const pageSize = Number($('pageSize').value || 50);
  const params = new URLSearchParams({
    q: $('search').value,
    store: $('storeFilter').value,
    became_from: $('becameFrom').value,
    became_to: $('becameTo').value,
    joined_from: $('joinedFrom').value,
    joined_to: $('joinedTo').value,
    limit: String(pageSize),
    offset: String((customerPage - 1) * pageSize),
  });
  return { params, pageSize };
}

async function searchCustomers(resetPage = true) {
  if (resetPage) customerPage = 1;
  const { params, pageSize } = customerQueryParams();
  const data = await api('/api/customers?' + params.toString());
  customerTotal = data.total;
  $('customerRows').innerHTML = data.items.map((row) => `
    <tr class="clickable-row" onclick="selectCustomer('${row.wid}')">
      <td>${safe(row.wid)}</td>
      <td>${safe(row.phone)}</td>
      <td>${safe(row.nickname)}</td>
      <td>${safe(row.store_name)}</td>
      <td>${safe(row.became_customer_at)}</td>
      <td>${safe(row.joined_at)}</td>
      <td>${safe(row.level_name || row.member_card)}</td>
      <td>${safe(row.available_point)}</td>
      <td>${safe(row.unused_coupon_count)} / ${safe(row.coupon_count)}</td>
    </tr>
  `).join('');
  const totalPages = Math.max(1, Math.ceil(customerTotal / pageSize));
  $('pageInfo').textContent = `第 ${customerPage} / ${totalPages} 页，共 ${customerTotal} 个客户`;
  $('prevPage').disabled = customerPage <= 1;
  $('nextPage').disabled = customerPage >= totalPages;
}

async function changeCustomerPage(step) {
  const pageSize = Number($('pageSize').value || 50);
  const totalPages = Math.max(1, Math.ceil(customerTotal / pageSize));
  customerPage = Math.min(Math.max(1, customerPage + step), totalPages);
  await searchCustomers(false);
}

async function resetCustomerFilters() {
  ['search', 'becameFrom', 'becameTo', 'joinedFrom', 'joinedTo'].forEach((id) => {
    $(id).value = '';
  });
  $('storeFilter').value = '';
  customerPage = 1;
  await searchCustomers();
}

async function selectCustomer(wid) {
  selectedWid = wid;
  const openingFromList = !$('customerListPanel').classList.contains('hidden');
  if (openingFromList) {
    customerListScrollY = window.scrollY || document.documentElement.scrollTop || 0;
  }
  $('issueWid').value = wid;
  $('couponStatusFilter').value = '';
  $('customerListPanel').classList.add('hidden');
  $('customerDetailPanel').classList.remove('hidden');
  if (openingFromList) scrollWindowTop();
  const data = await api('/api/customers/' + encodeURIComponent(wid));
  const c = data.customer;
  fillIssueCustomer(c);
  selectedCustomerCoupons = data.coupons;
  $('customerDetail').innerHTML = `<div class="kv">
    <div class="key">&#23458;&#25143;&#32534;&#21495;</div><div>${safe(c.wid)}</div>
    <div class="key">&#25163;&#26426;&#21495;</div><div>${safe(c.phone)}</div>
    <div class="key">&#26165;&#31216;</div><div>${safe(c.nickname)}</div>
    <div class="key">&#24615;&#21035;</div><div>${formatGender(c.gender)}</div>
    <div class="key">&#29983;&#26085;</div><div>${formatDateTime(c.birthday)}</div>
    <div class="key">&#31561;&#32423;</div><div>${safe(c.level_name || c.member_card)}</div>
    <div class="key">&#23458;&#25143;&#24402;&#23646;&#38376;&#24215;</div><div>${safe(c.store_name)}</div>
    <div class="key">姓名</div><div>${safe(c.real_name)}</div>
    <div class="key">车型车系</div><div>${safe(c.car_series)}</div>
    <div class="key">车架号</div><div>${formatVin(c.vin)}</div>
    <div class="key">购买门店</div><div>${safe(c.purchase_store_name)}</div>
    <div class="key">车牌号</div><div>${safe(c.plate_no)}</div>
    <div class="key">车辆信息状态</div><div>${formatBool(c.vehicle_query_success)} ${safe(c.vehicle_errcode) !== '-' ? `(${safe(c.vehicle_errcode)} ${safe(c.vehicle_errmsg)})` : ''}</div>
    <div class="key">&#25104;&#20026;&#23458;&#25143;&#26102;&#38388;</div><div>${formatDateTime(c.became_customer_at)}</div>
    <div class="key">&#20837;&#20250;&#26102;&#38388;</div><div>${formatDateTime(c.joined_at)}</div>
    <div class="key">&#23458;&#25143;&#29366;&#24577;</div><div>${formatCustomerStatus(c.customer_status)}</div>
    <div class="key">&#40657;&#21517;&#21333;</div><div>${formatBool(c.black_user)}</div>
  </div>`;
  $('couponDetail').textContent = '\u9009\u62e9\u4e00\u4e2a\u5238\u67e5\u770b\u8be6\u60c5';
  renderCustomerCoupons();
}

function renderCustomerCoupons() {
  const status = $('couponStatusFilter').value;
  const rows = status
    ? selectedCustomerCoupons.filter((row) => normalizeCouponStatus(row) === status)
    : selectedCustomerCoupons;
  $('couponFilterInfo').textContent = `显示 ${rows.length} / ${selectedCustomerCoupons.length} 张券`;
  $('customerCoupons').innerHTML = rows.map((row) => {
    const originalIndex = selectedCustomerCoupons.indexOf(row);
    return `
    <tr class="clickable-row" title="右键打开操作菜单" onclick="showCouponDetail(${originalIndex})" oncontextmenu="openCouponContextMenu(event, ${originalIndex})">
      <td>${safe(row.code)}</td>
      <td>${safe(row.template_name)}</td>
      <td>${statusTag(normalizeCouponStatus(row), normalizeCouponStatus(row) === 'expired' ? '已过期' : (row.status_text || row.status))}</td>
      <td>${safe(row.receive_time)}</td>
      <td>${safe(row.used_time)}</td>
      <td>${safe(row.valid_period)}</td>
    </tr>
  `;
  }).join('');
}


function rawJsonValue(coupon, key) {
  if (!coupon.raw_json) return '';
  try {
    const normalized = String(coupon.raw_json)
      .replace(/'/g, '"')
      .replace(/\bNone\b/g, 'null')
      .replace(/\bFalse\b/g, 'false')
      .replace(/\bTrue\b/g, 'true');
    const raw = JSON.parse(normalized);
    return raw[key] || '';
  } catch (err) {
    return '';
  }
}

function showCouponDetail(index) {
  const coupon = selectedCustomerCoupons[index];
  if (!coupon) return;
  const status = normalizeCouponStatus(coupon);
  const ruleText = rawJsonValue(coupon, '\u4f7f\u7528\u89c4\u5219') || coupon.rule_text || '';
  const usableStore = coupon.usable_store_names || rawJsonValue(coupon, '\u4f7f\u7528\u95e8\u5e97') || '';
  const discountText = rawJsonValue(coupon, '\u4f18\u60e0\u8bf4\u660e') || coupon.remark || '';
  $('couponDetail').innerHTML = `
    <div class="kv coupon-detail-grid">
      <div class="key">\u5238\u7801</div><div>${safe(coupon.code)}</div>
      <div class="key">\u540d\u79f0</div><div>${safe(coupon.template_name)}</div>
      <div class="key">\u72b6\u6001</div><div>${statusTag(status, status === 'expired' ? '\u5df2\u8fc7\u671f' : (coupon.status_text || coupon.status))}</div>
      <div class="key">\u5238\u7c7b\u578b</div><div>${safe(coupon.coupon_type)}</div>
      <div class="key">\u4f18\u60e0\u8bf4\u660e</div><div>${safe(discountText)}</div>
      <div class="key">\u9886\u53d6\u65f6\u95f4</div><div>${safe(coupon.receive_time)}</div>
      <div class="key">\u4f7f\u7528\u65f6\u95f4</div><div>${safe(coupon.used_time)}</div>
      <div class="key">\u6709\u6548\u671f</div><div>${safe(coupon.valid_period)}</div>
      <div class="key">\u4f7f\u7528\u95e8\u5e97</div><div>${safe(usableStore)}</div>
      <div class="key">\u4f7f\u7528\u89c4\u5219</div><div class="preline">${safe(ruleText)}</div>
      <div class="key">\u53d1\u653e\u95e8\u5e97</div><div>${safe(coupon.issued_store_name)}</div>
      <div class="key">\u53d1\u653e\u4eba\u5458</div><div>${safe(coupon.issued_by_name)}</div>
      <div class="key">\u53d1\u653e\u65f6\u95f4</div><div>${safe(coupon.issued_at)}</div>
      <div class="key">\u6838\u9500\u95e8\u5e97</div><div>${safe(coupon.redeemed_store_name)}</div>
      <div class="key">\u6838\u9500\u4eba\u5458</div><div>${safe(coupon.redeemed_by_name)}</div>
      <div class="key">\u6838\u9500\u65f6\u95f4</div><div>${safe(coupon.redeemed_at)}</div>
      <div class="key">作废人员</div><div>${safe(coupon.voided_by_name)}</div>
      <div class="key">作废时间</div><div>${safe(coupon.voided_at)}</div>
      <div class="key">作废原因</div><div>${safe(coupon.void_reason)}</div>
      <div class="key">\u6765\u6e90</div><div>${safe(coupon.source)}</div>
      <div class="key">\u5907\u6ce8</div><div>${safe(coupon.remark)}</div>
    </div>
  `;
}

function openCouponContextMenu(event, index) {
  event.preventDefault();
  contextCouponIndex = index;
  const menu = $('couponContextMenu');
  menu.style.left = `${event.clientX}px`;
  menu.style.top = `${event.clientY}px`;
  menu.classList.remove('hidden');
}

function closeCouponContextMenu() {
  $('couponContextMenu').classList.add('hidden');
  contextCouponIndex = null;
}

async function confirmContextCouponRedeem() {
  const index = contextCouponIndex;
  closeCouponContextMenu();
  const coupon = selectedCustomerCoupons[index];
  if (!coupon) return;

  const normalizedStatus = normalizeCouponStatus(coupon);
  if (normalizedStatus !== 'unused') {
    alert(`该券当前不可核销：${safe(coupon.status_text || normalizedStatus)}`);
    return;
  }

  const ok = confirm(`确认核销这张券？\n\n券码：${safe(coupon.code)}\n名称：${safe(coupon.template_name)}`);
  if (!ok) return;

  try {
    const data = await api('/api/coupons/redeem', {
      method: 'POST',
      body: JSON.stringify({
        code: coupon.code,
        operator: $('operator').value,
        remark: '客户详情右键核销',
      }),
    });
    selectedCustomerCoupons[index] = data.coupon;
    renderCustomerCoupons();
    await loadSummary();
    if (selectedWid) await selectCustomer(selectedWid);
  } catch (err) {
    alert(err.message);
  }
}

async function confirmContextCouponVoid() {
  const index = contextCouponIndex;
  closeCouponContextMenu();
  const coupon = selectedCustomerCoupons[index];
  if (!coupon) return;

  const normalizedStatus = normalizeCouponStatus(coupon);
  if (normalizedStatus !== 'unused') {
    alert(`该券当前不可作废：${safe(coupon.status_text || normalizedStatus)}`);
    return;
  }

  const reason = prompt(`确认作废这张券？\n\n券码：${safe(coupon.code)}\n名称：${safe(coupon.template_name)}\n\n请输入作废原因：`, '发券错误');
  if (reason === null) return;
  if (!reason.trim()) {
    alert('请输入作废原因');
    return;
  }

  try {
    const data = await api('/api/coupons/void', {
      method: 'POST',
      body: JSON.stringify({
        code: coupon.code,
        operator: $('operator').value,
        remark: reason.trim(),
      }),
    });
    selectedCustomerCoupons[index] = data.coupon;
    renderCustomerCoupons();
    await loadSummary();
    if (selectedWid) await selectCustomer(selectedWid);
  } catch (err) {
    alert(err.message);
  }
}

function backToCustomerList() {
  $('customerDetailPanel').classList.add('hidden');
  $('customerListPanel').classList.remove('hidden');
  requestAnimationFrame(() => window.scrollTo({ top: customerListScrollY, left: 0, behavior: 'auto' }));
}

function fillIssueCustomer(customer) {
  selectedWid = customer.wid || '';
  $('issueWid').value = safe(customer.wid) === '-' ? '' : customer.wid;
  $('issuePhone').value = safe(customer.phone) === '-' ? '' : customer.phone;
  $('issueNickname').value = safe(customer.nickname) === '-' ? '' : customer.nickname;
  $('issueStore').value = safe(customer.store_name) === '-' ? '' : customer.store_name;
  $('issueLevel').value = safe(customer.level_name || customer.member_card) === '-' ? '' : (customer.level_name || customer.member_card || '');
  $('issueCustomerResults').classList.add('hidden');
  $('issueCustomerResults').innerHTML = '';
  updateIssueStoreScopeLabels();
}

function clearIssueCustomerFields() {
  selectedWid = '';
  issueLookupRows = [];
  $('issueWid').value = '';
  $('issueNickname').value = '';
  $('issueStore').value = '';
  $('issueLevel').value = '';
  updateIssueStoreScopeLabels();
}

async function lookupIssueCustomer() {
  const q = $('issuePhone').value.trim();
  const box = $('issueCustomerResults');
  clearIssueCustomerFields();
  if (!q) {
    box.classList.add('hidden');
    box.innerHTML = '';
    return;
  }

  box.classList.remove('hidden');
  box.innerHTML = '<div class="lookup-empty"><span class="spinner"></span> 搜索中...</div>';
  const data = await api('/api/customer-lookup?q=' + encodeURIComponent(q));
  if (!data.items.length) {
    box.innerHTML = '<div class="lookup-empty">没有找到匹配客户</div>';
    return;
  }

  issueLookupRows = data.items;
  box.innerHTML = data.items.map((row, index) => `
    <button type="button" class="lookup-item" onclick="selectIssueLookupCustomer(${index})">
      <strong>${safe(row.phone)}</strong>
      <span>${safe(row.nickname)}</span>
      <span>${safe(row.store_name)}</span>
      <span>${safe(row.level_name || row.member_card)}</span>
    </button>
  `).join('');
}

function selectIssueLookupCustomer(index) {
  const row = issueLookupRows[index];
  if (row) fillIssueCustomer(row);
}

function scheduleIssueCustomerLookup() {
  clearTimeout(customerLookupTimer);
  clearIssueCustomerFields();
  const box = $('issueCustomerResults');
  const q = $('issuePhone').value.trim();
  if (!q) {
    box.classList.add('hidden');
    box.innerHTML = '';
    return;
  }
  box.classList.remove('hidden');
  box.innerHTML = '<div class="lookup-empty"><span class="spinner"></span> 搜索中...</div>';
  customerLookupTimer = setTimeout(() => {
    lookupIssueCustomer().catch((err) => {
      const box = $('issueCustomerResults');
      box.classList.remove('hidden');
      box.innerHTML = `<div class="lookup-empty">${safe(err.message)}</div>`;
    });
  }, 300);
}

function clearNewCustomerCargeerResults() {
  newCustomerCargeerRows = [];
  const box = $('newCustomerCargeerResults');
  if (!box) return;
  box.classList.add('hidden');
  box.innerHTML = '';
}

function renderNewCustomerCargeerRows(items, status) {
  const box = $('newCustomerCargeerResults');
  newCustomerCargeerRows = items || [];
  box.classList.remove('hidden');

  if (status === 'disabled') {
    box.innerHTML = '<div class="lookup-empty">Cargeer 查询未启用</div>';
    return;
  }
  if (status === 'missing_config') {
    box.innerHTML = '<div class="lookup-empty">Cargeer 配置不完整，暂时不能自动查询</div>';
    return;
  }
  if (status && status.startsWith('error:')) {
    box.innerHTML = `<div class="lookup-empty">Cargeer 查询失败：${safe(status.replace(/^error:\s*/, ''))}</div>`;
    return;
  }
  if (!newCustomerCargeerRows.length) {
    box.innerHTML = '<div class="lookup-empty">Cargeer 没有找到该手机号的车辆信息</div>';
    return;
  }

  box.innerHTML = newCustomerCargeerRows.map((row, index) => `
    <button type="button" class="lookup-item lookup-item-vehicle" onclick="selectNewCustomerCargeerRow(${index})">
      <strong>${safe(row.phone)}</strong>
      <span>${safe(row.real_name || row.nickname)}</span>
      <span>${safe(row.plate_no)}</span>
      <span>${safe(row.car_series)}</span>
      <span>${safe(row.vin)}</span>
      <span>${safe(row.store_name)}</span>
    </button>
  `).join('');
}

async function lookupNewCustomerCargeer() {
  const phone = $('newCustomerPhone').value.trim();
  const box = $('newCustomerCargeerResults');
  if (!phone) {
    clearNewCustomerCargeerResults();
    return;
  }
  if (phone.length < 5) {
    clearNewCustomerCargeerResults();
    return;
  }

  box.classList.remove('hidden');
  box.innerHTML = '<div class="lookup-empty"><span class="spinner"></span> 正在查询 Cargeer...</div>';
  const data = await api('/api/cargeer/customer-lookup?phone=' + encodeURIComponent(phone));
  renderNewCustomerCargeerRows(data.items || [], data.status || 'ok');
}

function scheduleNewCustomerCargeerLookup() {
  clearTimeout(newCustomerLookupTimer);
  const phone = $('newCustomerPhone').value.trim();
  if (!phone) {
    clearNewCustomerCargeerResults();
    return;
  }
  const box = $('newCustomerCargeerResults');
  box.classList.remove('hidden');
  box.innerHTML = '<div class="lookup-empty"><span class="spinner"></span> 正在查询 Cargeer...</div>';
  newCustomerLookupTimer = setTimeout(() => {
    lookupNewCustomerCargeer().catch((err) => {
      const box = $('newCustomerCargeerResults');
      box.classList.remove('hidden');
      box.innerHTML = `<div class="lookup-empty">${safe(err.message)}</div>`;
    });
  }, 500);
}

function applyNewCustomerStore(storeName) {
  const select = $('newCustomerStore');
  const matchedName = (storeName || '').trim();
  if (!select || !matchedName) {
    if (select) select.value = '';
    return false;
  }

  const exists = Array.from(select.options).some((option) => option.value === matchedName);
  if (!exists) {
    select.value = '';
    return false;
  }

  select.value = matchedName;
  return true;
}

function selectNewCustomerCargeerRow(index) {
  const row = newCustomerCargeerRows[index];
  if (!row) return;
  $('newCustomerPhone').value = row.phone || $('newCustomerPhone').value;
  $('newCustomerNickname').value = row.nickname || row.real_name || '';
  $('newCustomerRealName').value = row.real_name || '';
  $('newCustomerLevel').value = row.level_name || row.member_card || '';
  $('newCustomerCarSeries').value = row.car_series || '';
  $('newCustomerVin').value = normalizeVin(row.vin || '');
  $('newCustomerPurchaseStore').value = row.purchase_store_name || row.store_name || '';
  $('newCustomerPlateNo').value = row.plate_no || '';
  const storeMatched = applyNewCustomerStore(row.matched_store_name || row.store_name || '');
  const msg = $('newCustomerMessage');
  msg.className = 'message ok';
  msg.textContent = '已填入 Cargeer 客户车辆信息，请确认后新增客户';
  msg.className = storeMatched ? 'message ok' : 'message error';
  msg.textContent = storeMatched
    ? '已填入 Cargeer 客户车辆信息，请确认后新增客户'
    : `已填入 Cargeer 信息，但门店「${row.store_name || '-'}」不在门店总表中，请先在左侧维护门店`;
  $('newCustomerCargeerResults').classList.add('hidden');
}

async function loadTemplates() {
  const data = await api('/api/templates');
  $('issueTemplate').innerHTML = data.items.map((row) => `<option value="${row.id}">${safe(row.name)}</option>`).join('');
  $('templateRows').innerHTML = data.items.map((row) => `
    <tr>
      <td>${safe(row.id)}</td>
      <td>${safe(row.name)}</td>
      <td>${safe(row.coupon_type)}</td>
      <td>${safe(row.rule_text)}</td>
    </tr>
  `).join('');
}

async function loadStores() {
  const data = await api('/api/stores');
  const options = data.items.map((row) => (
    `<option value="${safe(row.name)}">${safe(row.name)}</option>`
  )).join('');
  $('storeFilter').innerHTML = `<option value="">????</option>${options}`;
  $('newCustomerStore').innerHTML = `<option value="">?????</option>${options}`;
  renderIssueStorePicker(data.items.map((row) => ({
    name: row.name,
    count: row.customer_count,
  })));
  await loadStoreMaintenance();
}

function renderStoreRows(items) {
  $('storeRows').innerHTML = (items || []).map((row) => `
    <tr>
      <td>${safe(row.name)}</td>
      <td>${safe(row.customer_count || 0)}</td>
      <td>${row.enabled ? '<span class="tag unused">启用</span>' : '<span class="tag voided">停用</span>'}</td>
      <td><button class="secondary" onclick="toggleStore('${safe(row.id)}', ${row.enabled ? 'false' : 'true'})">${row.enabled ? '停用' : '启用'}</button></td>
    </tr>
  `).join('');
}

async function loadStoreMaintenance() {
  if (!$('storeRows')) return;
  const data = await api('/api/stores/all');
  renderStoreRows(data.items || []);
}

async function loadAdminUsers() {
  if (!$('adminUserRows')) return;
  const data = await api('/api/admin-users');
  $('adminUserRows').innerHTML = (data.items || []).map((row) => `
    <tr>
      <td>${html(row.display_name || row.username)}</td>
      <td>${html(row.phone || row.username)}</td>
      <td>${html(row.store_name)}</td>
      <td>${html(row.role || 'staff')}</td>
      <td>${row.enabled ? '<span class="tag unused">启用</span>' : '<span class="tag voided">停用</span>'}</td>
      <td>${html(row.created_at)}</td>
      <td>${html(row.last_login_at)}</td>
    </tr>
  `).join('');
}

async function createStore() {
  const msg = $('storeMessage');
  msg.className = 'message';
  msg.textContent = '处理中...';
  try {
    const name = $('newStoreName').value.trim();
    const data = await api('/api/stores', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
    msg.className = 'message ok';
    msg.textContent = data.created ? '门店已新增' : '门店已存在，已启用';
    $('newStoreName').value = '';
    await loadStores();
  } catch (err) {
    msg.className = 'message error';
    msg.textContent = err.message;
  }
}

async function toggleStore(storeId, enabled) {
  const msg = $('storeMessage');
  msg.className = 'message';
  msg.textContent = '处理中...';
  try {
    await api('/api/stores/' + encodeURIComponent(storeId), {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    });
    msg.className = 'message ok';
    msg.textContent = enabled ? '门店已启用' : '门店已停用';
    await loadStores();
  } catch (err) {
    msg.className = 'message error';
    msg.textContent = err.message;
  }
}

let issueStoreOptions = [];
let issueSelectedStores = [];

function issueStoreByName(name) {
  return issueStoreOptions.find((item) => item.name === name) || { name, count: '' };
}

function issueCustomerStoreName() {
  return $('issueStore') ? $('issueStore').value.trim() : '';
}

function currentIssueScopeSelectedNames() {
  const scope = $('issueUsableStoreScope') ? $('issueUsableStoreScope').value : 'all';
  if (scope === 'all') return issueStoreOptions.map((item) => item.name);
  if (scope === 'current') return currentAdminProfile.store_name ? [currentAdminProfile.store_name] : [];
  if (scope === 'customer_store') return issueCustomerStoreName() ? [issueCustomerStoreName()] : [];
  return issueSelectedStores;
}

function renderIssueStorePicker(items = issueStoreOptions) {
  issueStoreOptions = items;
  const scope = $('issueUsableStoreScope') ? $('issueUsableStoreScope').value : 'all';
  const selectedNames = currentIssueScopeSelectedNames();
  const selectedSet = new Set(selectedNames);
  const canEditAvailable = scope === 'selected';
  const canEditSelected = scope === 'selected' || scope === 'all';
  const available = issueStoreOptions.filter((item) => !selectedSet.has(item.name));
  const selected = selectedNames.map(issueStoreByName);

  $('issueAvailableStores').classList.toggle('disabled', !canEditAvailable);
  $('issueSelectedStores').classList.toggle('disabled', !canEditSelected);
  $('issueAvailableStores').innerHTML = available.map((item) => (
    `<button type="button" class="store-option" ${canEditAvailable ? '' : 'disabled'} onclick="moveIssueStore('${safe(item.name)}', true)">${safe(item.name)} (${safe(item.count)})</button>`
  )).join('');
  $('issueSelectedStores').innerHTML = selected.map((item) => (
    `<button type="button" class="store-option" ${canEditSelected ? '' : 'disabled'} onclick="moveIssueStore('${safe(item.name)}', false)">${safe(item.name)}${item.count !== '' ? ` (${safe(item.count)})` : ''}</button>`
  )).join('');
}

function moveIssueStore(name, selected) {
  const scope = $('issueUsableStoreScope').value;
  if (scope === 'all' && !selected) {
    issueSelectedStores = issueStoreOptions.map((item) => item.name).filter((item) => item !== name);
    $('issueUsableStoreScope').value = 'selected';
    updateIssueStoreScopeLabels();
    renderIssueStorePicker();
    return;
  }
  if (scope !== 'selected') return;
  if (selected) {
    if (!issueSelectedStores.includes(name)) issueSelectedStores.push(name);
  } else {
    issueSelectedStores = issueSelectedStores.filter((item) => item !== name);
  }
  renderIssueStorePicker();
}

function syncIssueStoreScope() {
  if ($('issueUsableStoreScope').value === 'selected') {
    issueSelectedStores = currentIssueScopeSelectedNames();
  } else {
    issueSelectedStores = [];
  }
  renderIssueStorePicker();
}

function selectedIssueUsableStoreNames() {
  return issueSelectedStores;
}

async function createCustomer() {
  const msg = $('newCustomerMessage');
  msg.className = 'message';
  msg.textContent = '处理中...';
  try {
    const vin = normalizeVin($('newCustomerVin').value);
    if (vin && !isValidVin(vin)) {
      throw new Error('车架号格式不正确：应为 17 位 VIN，且不能包含 I、O、Q');
    }
    const data = await api('/api/customers', {
      method: 'POST',
      body: JSON.stringify({
        phone: $('newCustomerPhone').value,
        nickname: $('newCustomerNickname').value,
        store_name: $('newCustomerStore').value,
        level_name: $('newCustomerLevel').value,
        gender: $('newCustomerGender').value,
        birthday: $('newCustomerBirthday').value,
        real_name: $('newCustomerRealName').value,
        car_series: $('newCustomerCarSeries').value,
        vin,
        purchase_store_name: $('newCustomerPurchaseStore').value,
        plate_no: $('newCustomerPlateNo').value,
        remark: $('newCustomerRemark').value,
      }),
    });
    msg.className = 'message ok';
    msg.textContent = data.created ? `新增成功：${data.customer.wid}` : `客户已存在：${data.customer.wid}`;
    fillIssueCustomer(data.customer);
    await loadStores();
    await loadSummary();
    await searchCustomers();
  } catch (err) {
    msg.className = 'message error';
    msg.textContent = err.message;
  }
}

async function createTemplate() {
  const msg = $('newTemplateMessage');
  msg.className = 'message';
  msg.textContent = '处理中...';
  try {
    const data = await api('/api/templates', {
      method: 'POST',
      body: JSON.stringify({
        name: $('newTemplateName').value,
        coupon_type: $('newTemplateType').value,
        rule_text: $('newTemplateRule').value,
      }),
    });
    msg.className = 'message ok';
    msg.textContent = `新增成功：${data.template.name}`;
    await loadTemplates();
    $('issueTemplate').value = data.template.id;
    $('newTemplateName').value = '';
    $('newTemplateType').value = '';
    $('newTemplateRule').value = '';
    await loadSummary();
  } catch (err) {
    msg.className = 'message error';
    msg.textContent = err.message;
  }
}

async function issueCoupon() {
  const msg = $('issueMessage');
  msg.className = 'message';
  msg.textContent = '处理中...';
  try {
    if (!$('issueWid').value) {
      throw new Error('请先输入手机号并选择客户');
    }
    if ($('issueUsableStoreScope').value === 'selected' && selectedIssueUsableStoreNames().length === 0) {
      throw new Error('选择指定门店时，请至少选择一个可用门店');
    }
    const data = await api('/api/coupons/issue', {
      method: 'POST',
      body: JSON.stringify({
        wid: $('issueWid').value,
        template_id: $('issueTemplate').value,
        quantity: Number($('issueQuantity').value),
        valid_days: Number($('issueDays').value),
        operator: $('operator').value,
        remark: $('issueRemark').value,
        usable_store_scope: $('issueUsableStoreScope').value,
        usable_store_names: selectedIssueUsableStoreNames(),
      }),
    });
    msg.className = 'message ok';
    msg.textContent = `发券成功：${data.issued.map((item) => item.code).join('、')}`;
    await loadSummary();
    if ($('issueWid').value) await selectCustomer($('issueWid').value);
  } catch (err) {
    msg.className = 'message error';
    msg.textContent = err.message;
  }
}

async function redeemCoupon() {
  const msg = $('redeemMessage');
  msg.className = 'message';
  msg.textContent = '处理中...';
  try {
    const data = await api('/api/coupons/redeem', {
      method: 'POST',
      body: JSON.stringify({ code: $('redeemCode').value, operator: $('operator').value, remark: $('redeemRemark').value }),
    });
    msg.className = 'message ok';
    msg.textContent = `核销成功：${data.coupon.template_name}，客户 ${data.coupon.customer_wid}`;
    await loadSummary();
    if (selectedWid) await selectCustomer(selectedWid);
  } catch (err) {
    msg.className = 'message error';
    msg.textContent = err.message;
  }
}

async function loadLogs() {
  const data = await api('/api/logs');
  $('logRows').innerHTML = data.items.map((row) => `
    <tr>
      <td>${safe(row.created_at)}</td>
      <td>${safe(row.operator)}</td>
      <td>${safe(row.action)}</td>
      <td>${safe(row.customer_wid)}</td>
      <td>${safe(row.target)}</td>
      <td>${safe(row.quantity)}</td>
      <td>${safe(row.remark)}</td>
    </tr>
  `).join('');
}

document.querySelectorAll('.sidebar button').forEach((btn) => btn.addEventListener('click', () => {
  document.querySelectorAll('.sidebar button').forEach((item) => item.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.view').forEach((item) => item.classList.add('hidden'));
  $('view-' + btn.dataset.view).classList.remove('hidden');
  if (btn.dataset.view === 'stores') loadStoreMaintenance();
  if (btn.dataset.view === 'admin-users') loadAdminUsers();
  if (btn.dataset.view === 'logs') loadLogs();
}));

document.addEventListener('click', (event) => {
  if (!$('couponContextMenu').contains(event.target)) closeCouponContextMenu();
});

async function bootstrapApp() {
  await loadSummary();
  await loadStores();
  await loadTemplates();
  await searchCustomers();
}

async function init() {
  $('search').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') searchCustomers();
  });
  ['storeFilter', 'becameFrom', 'becameTo', 'joinedFrom', 'joinedTo', 'pageSize'].forEach((id) => {
    $(id).addEventListener('change', () => searchCustomers());
  });
  $('issuePhone').addEventListener('input', scheduleIssueCustomerLookup);
  $('issuePhone').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      lookupIssueCustomer();
    }
  });
  $('newCustomerPhone').addEventListener('input', scheduleNewCustomerCargeerLookup);
  $('newCustomerPhone').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      lookupNewCustomerCargeer();
    }
  });
  try {
    const data = await api('/api/auth/me');
    showApp(data.username, data.profile || {});
    await bootstrapApp();
  } catch (err) {
    showLogin();
  }
}

init();
