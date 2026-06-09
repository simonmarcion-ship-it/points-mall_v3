const $ = (id) => document.getElementById(id);
const ADMIN_BASE = window.location.pathname === '/admin' || window.location.pathname.startsWith('/admin/')
  ? '/admin'
  : '';
let selectedWid = '';
let customerPage = 1;
let customerTotal = 0;
let selectedCustomerCoupons = [];
let customerLookupTimer = null;
let issueLookupRows = [];
let issueTemplateRows = [];
let newCustomerLookupTimer = null;
let newCustomerCargeerRows = [];
let contextCouponIndex = null;
let currentAdminProfile = {};
let customerListScrollY = 0;
let redeemScannerStream = null;
let redeemScannerTimer = null;
let redeemBarcodeDetector = null;
let redeemLookupTimer = null;
let lastRedeemLookupCode = '';
let wechatScanConfigured = false;
let wechatScanConfigPromise = null;
let registerSmsTimer = null;
let lastRedeemStoreOptions = [];
let logPage = 1;
let logTotal = 0;

function scrollWindowTop() {
  requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: 'auto' }));
}

async function api(path, options = {}) {
  const apiPath = path.startsWith('/api/') ? ADMIN_BASE + path : path;
  const res = await fetch(apiPath, { headers: { 'Content-Type': 'application/json' }, ...options });
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
  $('currentRole').textContent = roleLabel(profile.role);
  $('currentStore').textContent = safe(profile.store_name);
  $('operator').value = displayName || username;
  renderIdentitySwitcher(profile.identities || []);
  updateIssueStoreScopeLabels();
  renderOperationStoreOptions();
  $('loginView').classList.add('hidden');
  $('appView').classList.remove('hidden');
  applyPermissions();
}

function renderIdentitySwitcher(identities) {
  const wrap = $('identitySwitcherWrap');
  const select = $('identitySwitcher');
  if (!wrap || !select) return;
  if (!identities || identities.length <= 1) {
    wrap.classList.add('hidden');
    select.innerHTML = '';
    return;
  }
  select.innerHTML = identities.map((identity) => {
    const label = `${identity.store_name || '-'} / ${roleLabel(identity.role)}`;
    return `<option value="${html(identity.user_id)}" ${identity.current ? 'selected' : ''}>${html(label)}</option>`;
  }).join('');
  wrap.classList.remove('hidden');
}

async function switchIdentity(userId) {
  if (!userId || userId === currentAdminProfile.user_id) return;
  const data = await api('/api/auth/switch-identity', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });
  showApp(data.username, data.profile || {});
  await bootstrapApp();
}

function permissions() {
  return currentAdminProfile.permissions || {};
}

function can(permission) {
  if (permission === 'can_admin_users' && ['admin', 'super_admin'].includes(currentAdminProfile.role)) return true;
  return Boolean(permissions()[permission]);
}

function roleLabel(role) {
  return {
    super_admin: '超级管理员',
    admin: '管理员',
    issuer: '发券人员',
    redeemer: '核销人员',
    staff: '发券人员',
  }[role] || role || '-';
}

function applyPermissions() {
  document.querySelectorAll('[data-permission]').forEach((el) => {
    el.classList.toggle('hidden', !can(el.dataset.permission));
  });
  const active = document.querySelector('.sidebar button.active:not(.hidden)');
  if (!active) {
    const first = document.querySelector('.sidebar button:not(.hidden)');
    if (first) first.click();
  }
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

function profileStores() {
  return currentAdminProfile.stores || [];
}

function renderOperationStoreOptions() {
  const stores = profileStores();
  if ($('issueOperationStore')) {
    $('issueOperationStore').innerHTML = stores.map((row) => `<option value="${html(row.id || '')}">${html(row.name || '')}</option>`).join('');
  }
}

function selectedOptionValues(select) {
  return Array.from(select?.selectedOptions || []).map((option) => option.value).filter(Boolean);
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
    alert(err.message);
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
}

function showLoginPanel() {
  const loginPanel = document.querySelector('#loginView .login-panel');
  if (loginPanel) loginPanel.classList.remove('hidden');
  if ($('registerPanel')) $('registerPanel').classList.add('hidden');
}

window.showRegisterPanel = showRegisterPanel;
window.showLoginPanel = showLoginPanel;

function startRegisterSmsCountdown(seconds = 60) {
  clearInterval(registerSmsTimer);
  const button = $('registerSmsButton');
  let remaining = seconds;
  button.disabled = true;
  button.textContent = `${remaining}s`;
  registerSmsTimer = setInterval(() => {
    remaining -= 1;
    if (remaining <= 0) {
      clearInterval(registerSmsTimer);
      registerSmsTimer = null;
      button.disabled = false;
      button.textContent = '获取验证码';
      return;
    }
    button.textContent = `${remaining}s`;
  }, 1000);
}

async function sendRegisterSmsCode() {
  const msg = $('registerMessage');
  msg.className = 'message';
  msg.textContent = '发送验证码中...';
  try {
    await api('/api/auth/register-sms/send', {
      method: 'POST',
      body: JSON.stringify({ phone: $('registerPhone').value }),
    });
    msg.className = 'message ok';
    msg.textContent = '验证码已发送，请查看短信';
    startRegisterSmsCountdown();
  } catch (err) {
    msg.className = 'message error';
    msg.textContent = err.message;
  }
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
        sms_code: $('registerSmsCode').value,
        password: $('registerPassword').value,
        password_confirm: $('registerPasswordConfirm').value,
      }),
    });
    msg.className = 'message ok';
    msg.textContent = '注册成功';
    $('loginUsername').value = data.username || $('registerPhone').value;
    $('loginPassword').value = '';
    showApp(data.username, data.profile || {});
    await bootstrapApp();
  } catch (err) {
    msg.className = 'message error';
    msg.textContent = err.message;
  }
}

window.registerAdmin = registerAdmin;
window.sendRegisterSmsCode = sendRegisterSmsCode;
window.selectIssueTemplate = selectIssueTemplate;
window.startEditCustomerDetail = startEditCustomerDetail;
window.cancelEditCustomerDetail = cancelEditCustomerDetail;
window.deleteCustomer = deleteCustomer;
window.deleteAdminUser = deleteAdminUser;
window.downloadLogs = downloadLogs;
window.loadLogs = loadLogs;
window.changeLogPage = changeLogPage;
window.resetLogFilters = resetLogFilters;
window.toggleTemplate = toggleTemplate;

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

function issueVinValidationMessage() {
  const vin = normalizeVin($('issueVin')?.value || '');
  if (!vin) return '请先输入 17 位车架号';
  if (!isValidVin(vin)) return '车架号格式不正确：应为 17 位 VIN，且不能包含 I、O、Q';
  return '';
}

function updateIssueVinValidation() {
  const input = $('issueVin');
  const hint = $('issueVinHint');
  if (!input || !hint) return true;
  const message = issueVinValidationMessage();
  const hasValue = Boolean(normalizeVin(input.value));
  const invalid = hasValue && Boolean(message);
  input.classList.toggle('input-error', invalid);
  hint.classList.toggle('error', invalid);
  hint.textContent = invalid ? message : '车架号应为 17 位 VIN，不能包含 I、O、Q';
  return !message;
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
    ['昨日发券', data.yesterday_issued_coupons ?? 0],
    ['昨日核销券', data.yesterday_redeemed_coupons ?? 0],
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
    deleted_status: can('can_admin_users') ? ($('customerDeletedStatus')?.value || 'active') : 'active',
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
    <tr class="clickable-row ${row.deleted_at ? 'muted-row' : ''}" onclick="selectCustomer('${row.wid}')">
      <td data-label="wid">${safe(row.wid)}</td>
      <td data-label="手机号">${safe(row.phone)}</td>
      <td data-label="昵称">${safe(row.nickname)}</td>
      <td data-label="姓名">${safe(row.real_name)}</td>
      <td data-label="车架号">${safe(row.vin)}</td>
      <td data-label="车牌号">${safe(row.plate_no)}</td>
      <td data-label="车型">${safe(row.car_series)}</td>
      <td data-label="归属门店">${safe(row.store_name)}</td>
      <td data-label="成为客户时间">${safe(row.became_customer_at)}</td>
      <td data-label="入会时间">${safe(row.joined_at)}</td>
      <td data-label="等级">${safe(row.level_name || row.member_card)}</td>
      <td data-label="可用积分">${safe(row.available_point)}</td>
      <td data-label="可用券">${safe(row.unused_coupon_count)} / ${safe(row.coupon_count)}</td>
      <td data-label="删除时间">${safe(row.deleted_at)}</td>
      <td data-label="删除原因">${safe(row.deleted_reason)}</td>
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
  if ($('customerDeletedStatus')) $('customerDeletedStatus').value = 'active';
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
  if (!c.deleted_at) {
    fillIssueCustomer(c);
  }
  selectedCustomerCoupons = data.coupons;
  renderCustomerDetail(c);
  $('couponDetail').textContent = '\u9009\u62e9\u4e00\u4e2a\u5238\u67e5\u770b\u8be6\u60c5';
  renderCustomerCoupons();
}

function renderCustomerDetail(c) {
  const deletedInfo = c.deleted_at
    ? `<div class="key">删除时间</div><div>${safe(c.deleted_at)}</div>
        <div class="key">删除人</div><div>${safe(c.deleted_by)}</div>
        <div class="key">删除原因</div><div>${safe(c.deleted_reason)}</div>`
    : '';
  if (can('can_create_customer') && !c.deleted_at) {
    const storeOptions = Array.from($('newCustomerStore').options)
      .filter((option) => option.value)
      .map((option) => `<option value="${html(option.value)}" ${option.value === c.store_name ? 'selected' : ''}>${html(option.textContent)}</option>`)
      .join('');
    $('customerDetail').innerHTML = `
      <div class="customer-detail-actions">
        <button type="button" class="secondary" id="editCustomerButton" onclick="startEditCustomerDetail()">编辑</button>
        ${can('can_admin_users') ? '<button type="button" class="danger" id="deleteCustomerButton" onclick="deleteCustomer()">删除客户</button>' : ''}
      </div>
      <div id="customerReadonlyDetail" class="kv">
        <div class="key">客户编号</div><div>${safe(c.wid)}</div>
        <div class="key">手机号</div><div>${safe(c.phone)}</div>
        <div class="key">昵称</div><div>${safe(c.nickname)}</div>
        <div class="key">客户归属门店</div><div>${safe(c.store_name)}</div>
        <div class="key">等级</div><div>${safe(c.level_name || c.member_card)}</div>
        <div class="key">性别</div><div>${formatGender(c.gender)}</div>
        <div class="key">生日</div><div>${formatDateTime(c.birthday)}</div>
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
        ${deletedInfo}
      </div>
      <div id="customerEditDetail" class="hidden">
        <div class="form-grid">
          <label>客户编号<input id="editCustomerWid" value="${html(c.wid)}" readonly /></label>
          <label>手机号<input id="editCustomerPhone" value="${html(c.phone)}" inputmode="tel" /></label>
          <label>昵称<input id="editCustomerNickname" value="${html(c.nickname)}" /></label>
          <label>客户归属门店<select id="editCustomerStore">${storeOptions}</select></label>
          <label>等级<input id="editCustomerLevel" value="${html(c.level_name || c.member_card)}" /></label>
          <label>性别<input id="editCustomerGender" value="${html(c.gender)}" /></label>
          <label>生日<input id="editCustomerBirthday" type="date" value="${html((c.birthday || '').slice(0, 10))}" /></label>
          <label>姓名<input id="editCustomerRealName" value="${html(c.real_name)}" /></label>
          <label>车型车系<input id="editCustomerCarSeries" value="${html(c.car_series)}" /></label>
          <label>车架号<input id="editCustomerVin" value="${html(c.vin)}" /></label>
          <label>购买门店<input id="editCustomerPurchaseStore" value="${html(c.purchase_store_name)}" /></label>
          <label>车牌号<input id="editCustomerPlateNo" value="${html(c.plate_no)}" /></label>
        </div>
        <div class="actions inline-actions">
          <button type="button" onclick="saveCustomerDetail()">保存</button>
          <button type="button" class="secondary" onclick="cancelEditCustomerDetail()">取消</button>
        </div>
        <p id="editCustomerMessage" class="message"></p>
      </div>
    `;
    return;
  }

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
    ${deletedInfo}
  </div>`;
}

function startEditCustomerDetail() {
  $('customerReadonlyDetail').classList.add('hidden');
  $('customerEditDetail').classList.remove('hidden');
  $('editCustomerButton').classList.add('hidden');
}

function cancelEditCustomerDetail() {
  $('customerEditDetail').classList.add('hidden');
  $('customerReadonlyDetail').classList.remove('hidden');
  $('editCustomerButton').classList.remove('hidden');
}

async function saveCustomerDetail() {
  const msg = $('editCustomerMessage');
  msg.className = 'message';
  msg.textContent = '保存中...';
  try {
    const data = await api('/api/customers/' + encodeURIComponent(selectedWid), {
      method: 'PATCH',
      body: JSON.stringify({
        phone: $('editCustomerPhone').value,
        nickname: $('editCustomerNickname').value,
        store_name: $('editCustomerStore').value,
        level_name: $('editCustomerLevel').value,
        gender: $('editCustomerGender').value,
        birthday: $('editCustomerBirthday').value,
        real_name: $('editCustomerRealName').value,
        car_series: $('editCustomerCarSeries').value,
        vin: normalizeVin($('editCustomerVin').value),
        purchase_store_name: $('editCustomerPurchaseStore').value,
        plate_no: $('editCustomerPlateNo').value,
      }),
    });
    msg.className = 'message ok';
    msg.textContent = '客户资料已保存';
    renderCustomerDetail(data.customer);
    if (data.customer?.vin) {
      fillIssueCustomer(data.customer);
    }
    await searchCustomers(false);
  } catch (err) {
    msg.className = 'message error';
    msg.textContent = err.message;
  }
}

async function deleteCustomer() {
  if (!selectedWid) return;
  const reason = window.prompt('删除后该客户将不再出现在正常客户列表，也不能再用于发券或查重。该操作不可恢复，历史券和操作记录仍会保留。\n\n请输入删除原因：');
  if (reason === null) return;
  const cleanReason = reason.trim();
  if (!cleanReason) {
    window.alert('请输入删除原因');
    return;
  }
  if (!window.confirm(`确定删除客户 ${selectedWid} 吗？\n\n该操作不可恢复。`)) return;
  await api('/api/customers/' + encodeURIComponent(selectedWid), {
    method: 'DELETE',
    body: JSON.stringify({ reason: cleanReason }),
  });
  selectedWid = '';
  selectedCustomerCoupons = [];
  $('customerDetailPanel').classList.add('hidden');
  $('customerListPanel').classList.remove('hidden');
  await searchCustomers(false);
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
      <td data-label="券码">${safe(row.code)}</td>
      <td data-label="名称">${safe(row.template_name)}</td>
      <td data-label="状态">${statusTag(normalizeCouponStatus(row), normalizeCouponStatus(row) === 'expired' ? '已过期' : (row.status_text || row.status))}</td>
      <td data-label="领取时间">${safe(row.receive_time)}</td>
      <td data-label="使用时间">${safe(row.used_time)}</td>
      <td data-label="有效期">${safe(row.valid_period)}</td>
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
  applyPermissions();
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
    $('couponStatusFilter').value = '';
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
  if ($('issueVin')) $('issueVin').value = safe(customer.vin) === '-' ? '' : customer.vin;
  $('issueNickname').value = safe(customer.real_name || customer.nickname) === '-' ? '' : (customer.real_name || customer.nickname || '');
  $('issueStore').value = safe(customer.store_name) === '-' ? '' : customer.store_name;
  $('issueLevel').value = safe(customer.level_name || customer.member_card) === '-' ? '' : (customer.level_name || customer.member_card || '');
  $('issueCustomerResults').classList.add('hidden');
  $('issueCustomerResults').innerHTML = '';
  updateIssueVinValidation();
  updateIssueStoreScopeLabels();
}

function clearIssueCustomerFields() {
  selectedWid = '';
  issueLookupRows = [];
  $('issueWid').value = '';
  $('issuePhone').value = '';
  $('issueNickname').value = '';
  $('issueStore').value = '';
  $('issueLevel').value = '';
  updateIssueVinValidation();
  updateIssueStoreScopeLabels();
}

async function lookupIssueCustomer() {
  const q = normalizeVin($('issueVin').value);
  const box = $('issueCustomerResults');
  clearIssueCustomerFields();
  updateIssueVinValidation();
  if (!q) {
    box.classList.add('hidden');
    box.innerHTML = '';
    return;
  }

  box.classList.remove('hidden');
  box.innerHTML = '<div class="lookup-empty"><span class="spinner"></span> 搜索中...</div>';
  const data = await api('/api/customer-lookup?mode=vin&q=' + encodeURIComponent(q));
  if (!data.items.length) {
    box.innerHTML = '<div class="lookup-empty">没有找到匹配客户</div>';
    return;
  }

  issueLookupRows = data.items;
  box.innerHTML = data.items.map((row, index) => `
    <button type="button" class="lookup-item lookup-item-vehicle" onclick="selectIssueLookupCustomer(${index})">
      <strong>${safe(row.phone)}</strong>
      <span>${safe(row.real_name || row.nickname)}</span>
      <span>${safe(row.vin)}</span>
      <span>${safe(row.plate_no)}</span>
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
  updateIssueVinValidation();
  const box = $('issueCustomerResults');
  const q = normalizeVin($('issueVin').value);
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
  const canManageTemplates = can('can_manage_templates');
  const data = await api(can('can_manage_templates') ? '/api/templates?include_disabled=true' : '/api/templates');
  const allRows = data.items || [];
  issueTemplateRows = allRows.filter((row) => Number(row.enabled) === 1);
  $('issueTemplate').innerHTML = '<option value=""></option>' + issueTemplateRows.map((row) => `<option value="${row.id}">${safe(row.name)}</option>`).join('');
  $('issueTemplate').value = '';
  renderIssueTemplateOptions();
  syncIssueTemplateDisplay();
  $('templateRows').innerHTML = allRows.map((row) => `
    <tr class="${Number(row.enabled) === 1 ? '' : 'muted-row'}">
      <td data-label="模板ID">${safe(row.id)}</td>
      <td data-label="状态">${Number(row.enabled) === 1 ? statusTag('unused', '启用') : statusTag('voided', '停用')}</td>
      <td data-label="名称">${canManageTemplates ? `<input id="templateName-${safe(row.id)}" value="${html(row.name)}" />` : html(row.name)}</td>
      <td data-label="类型">${canManageTemplates ? `<input id="templateType-${safe(row.id)}" value="${html(row.coupon_type)}" />` : html(row.coupon_type)}</td>
      <td data-label="使用规则">${canManageTemplates ? `<textarea id="templateRule-${safe(row.id)}" rows="4">${html(row.rule_text)}</textarea>` : `<div class="preline">${html(row.rule_text || '暂无使用规则')}</div>`}</td>
      <td data-label="操作">${canManageTemplates ? `<div class="row-actions"><button class="secondary" onclick="updateTemplate('${safe(row.id)}')">保存</button><button class="${Number(row.enabled) === 1 ? 'danger' : 'secondary'}" onclick="toggleTemplate('${safe(row.id)}', ${Number(row.enabled) === 1 ? 'false' : 'true'})">${Number(row.enabled) === 1 ? '停用' : '启用'}</button></div>` : '<span class="subtle">只读</span>'}</td>
    </tr>
  `).join('');
}
function issueTemplateOptionText(row) {
  return [row.name, row.coupon_type, row.id].filter(Boolean).join(' / ');
}

function renderIssueTemplateOptions(filterText = '') {
  const box = $('issueTemplateOptions');
  if (!box) return;
  const keyword = filterText.trim().toLowerCase();
  const rows = issueTemplateRows.filter((row) => {
    if (!keyword) return true;
    return [row.name, row.coupon_type, row.rule_text, row.id].some((value) => (
      String(value || '').toLowerCase().includes(keyword)
    ));
  }).slice(0, 20);
  if (!rows.length) {
    box.classList.remove('hidden');
    box.innerHTML = '<div class="lookup-empty">没有匹配的券模板</div>';
    return;
  }
  box.classList.remove('hidden');
  box.innerHTML = rows.map((row) => (
    `<button type="button" class="template-option" onclick="selectIssueTemplate('${safe(row.id)}')">
      <span class="template-option-title">${html(issueTemplateOptionText(row))}</span>
      <span class="template-option-rule">${html(row.rule_text || '暂无使用规则')}</span>
    </button>`
  )).join('');
}

function closeIssueTemplateOptions() {
  const box = $('issueTemplateOptions');
  if (box) box.classList.add('hidden');
}

function selectIssueTemplate(templateId) {
  const select = $('issueTemplate');
  if (!select) return;
  select.value = templateId;
  syncIssueTemplateDisplay();
  closeIssueTemplateOptions();
}

function selectedIssueTemplate() {
  const selectedId = $('issueTemplate') ? $('issueTemplate').value : '';
  if (!selectedId) return null;
  return issueTemplateRows.find((row) => String(row.id) === String(selectedId)) || null;
}

function matchIssueTemplateInput(value) {
  const text = value.trim().toLowerCase();
  if (!text) return null;
  return issueTemplateRows.find((row) => (
    issueTemplateOptionText(row).toLowerCase() === text
    || String(row.name || '').toLowerCase() === text
    || String(row.id || '').toLowerCase() === text
  )) || null;
}

function syncIssueTemplateFromSearch() {
  const input = $('issueTemplateSearch');
  const select = $('issueTemplate');
  if (!input || !select) return;
  renderIssueTemplateOptions(input.value);
  select.value = '';
  const rule = $('issueTemplateRule');
  if (rule) rule.textContent = '请从下拉列表选择券模板后查看使用规则';
}

function syncIssueTemplateDisplay() {
  const input = $('issueTemplateSearch');
  const rule = $('issueTemplateRule');
  const template = selectedIssueTemplate();
  if (input && template && input.value !== issueTemplateOptionText(template)) {
    input.value = issueTemplateOptionText(template);
  }
  if (!rule) return;
  if (template) {
    rule.textContent = template.rule_text || '该模板暂无使用规则';
    return;
  }
  rule.textContent = '请选择券模板后查看使用规则';
}

async function updateTemplate(templateId) {
  await api('/api/templates/' + encodeURIComponent(templateId), {
    method: 'PATCH',
    body: JSON.stringify({
      name: $('templateName-' + templateId).value,
      coupon_type: $('templateType-' + templateId).value,
      rule_text: $('templateRule-' + templateId).value,
    }),
  });
  await loadTemplates();
}

async function toggleTemplate(templateId, enabled) {
  const action = enabled ? '启用' : '停用';
  if (!confirm('确认' + action + '这个券模板？')) return;
  await api('/api/templates/' + encodeURIComponent(templateId), {
    method: 'PATCH',
    body: JSON.stringify({ enabled }),
  });
  await loadTemplates();
}

async function loadStores() {
  const data = await api('/api/stores');
  const options = data.items.map((row) => (
    `<option value="${safe(row.name)}">${safe(row.name)}</option>`
  )).join('');
  const storeIdOptions = data.items.map((row) => (
    `<option value="${html(row.id)}">${html(row.name)}</option>`
  )).join('');
  $('storeFilter').innerHTML = `<option value="">????</option>${options}`;
  $('newCustomerStore').innerHTML = `<option value="">?????</option>${options}`;
  if ($('newAdminStore')) $('newAdminStore').innerHTML = storeIdOptions;
  renderOperationStoreOptions();
  renderIssueStorePicker(data.items.map((row) => ({
    name: row.name,
    count: row.customer_count,
  })));
  if (can('can_manage_stores')) await loadStoreMaintenance();
}

function renderStoreRows(items) {
  $('storeRows').innerHTML = (items || []).map((row) => `
    <tr>
      <td data-label="门店">${safe(row.name)}</td>
      <td data-label="客户数">${safe(row.customer_count || 0)}</td>
      <td data-label="状态">${row.enabled ? '<span class="tag unused">启用</span>' : '<span class="tag voided">停用</span>'}</td>
      <td data-label="操作"><button class="secondary" onclick="toggleStore('${safe(row.id)}', ${row.enabled ? 'false' : 'true'})">${row.enabled ? '停用' : '启用'}</button></td>
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
  const nameCollator = new Intl.Collator('zh-Hans-u-co-pinyin', { numeric: true, sensitivity: 'base' });
  const allItems = data.items || [];
  const selectedStore = renderAdminUserStoreFilter(allItems, $('adminUserStoreFilter')?.value || '');
  const items = allItems.filter((row) => {
    if (!selectedStore) return true;
    const storeIds = row.store_ids || [];
    const storeNames = row.store_names || [];
    return storeIds.includes(selectedStore) || storeNames.includes(selectedStore) || row.store_id === selectedStore || row.store_name === selectedStore;
  }).sort((a, b) => {
    const nameA = a.display_name || a.username || a.phone || '';
    const nameB = b.display_name || b.username || b.phone || '';
    return nameCollator.compare(nameA, nameB);
  });
  $('adminUserRows').innerHTML = items.map((row) => {
    const deleted = Boolean(row.deleted_at);
    const statusHtml = deleted
      ? '<span class="tag voided">已被删除</span>'
      : (row.enabled ? '<span class="tag unused">启用</span>' : '<span class="tag voided">停用</span>');
    const registerHtml = deleted
      ? '<span class="tag voided">已删除</span>'
      : (row.registered_at ? '<span class="tag used">已注册</span>' : '<span class="tag expired">待注册</span>');
    const canPromoteAdmin = currentAdminProfile.role === 'super_admin' || can('can_promote_admin');
    const protectedRole = row.role === 'super_admin' || (!canPromoteAdmin && row.role === 'admin');
    const storeNames = row.store_name || (row.store_names?.length ? row.store_names.join('、') : '');
    const storeEditHtml = html(storeNames);
    const roleHtml = protectedRole || deleted
      ? `<span class="tag used">${roleLabel(row.role)}</span>`
      : `
        <select onchange="updateAdminUserRole('${safe(row.id)}', this.value)">
          <option value="issuer" ${row.role === 'issuer' || row.role === 'staff' ? 'selected' : ''}>发券人员</option>
          <option value="redeemer" ${row.role === 'redeemer' ? 'selected' : ''}>核销人员</option>
          ${canPromoteAdmin ? `<option value="admin" ${row.role === 'admin' ? 'selected' : ''}>管理员</option>` : ''}
        </select>`;
    const canEditRenewal = !deleted && (row.role === 'issuer' || row.role === 'staff' || (row.role === 'admin' && canPromoteAdmin));
    const renewalHtml = row.role === 'redeemer'
      ? '<span class="tag">不适用</span>'
      : row.role === 'super_admin'
      ? '<span class="tag used">是</span>'
      : !canEditRenewal
      ? (row.can_issue_renewal ? '<span class="tag used">是</span>' : '<span class="tag">否</span>')
      : `
        <select onchange="updateAdminUserRenewal('${safe(row.id)}', this.value === '1')">
          <option value="0" ${row.can_issue_renewal ? '' : 'selected'}>否</option>
          <option value="1" ${row.can_issue_renewal ? 'selected' : ''}>是</option>
        </select>`;
    const actionHtml = protectedRole
      ? '<span class="subtle">受保护账号</span>'
      : deleted
      ? '<span class="subtle">可用同手机号重新新增</span>'
      : `<button class="secondary" onclick="toggleAdminUser('${safe(row.id)}', ${row.enabled ? 'false' : 'true'}, '${html(row.display_name || row.phone || row.username)}')">${row.enabled ? '停用' : '启用'}</button>
         <button class="danger" onclick="deleteAdminUser('${safe(row.id)}', '${html(row.display_name || row.phone || row.username)}')">删除</button>`;
    return `
    <tr class="${deleted ? 'muted-row' : ''}">
      <td data-label="姓名">${html(row.display_name || row.username)}</td>
      <td data-label="手机号">${html(row.phone || row.username)}</td>
      <td data-label="所属门店">${storeEditHtml}</td>
      <td data-label="权限">${roleHtml}</td>
      <td data-label="续保券">${renewalHtml}</td>
      <td data-label="状态">${statusHtml}</td>
      <td data-label="注册状态">${registerHtml}</td>
      <td data-label="注册时间">${html(row.created_at)}</td>
      <td data-label="最近登录">${html(row.last_login_at)}</td>
      <td data-label="操作" class="row-actions">${actionHtml}</td>
    </tr>
  `;
  }).join('');
}

function renderAdminUserStoreFilter(items, selectedStore = '') {
  const select = $('adminUserStoreFilter');
  if (!select) return '';
  const stores = new Map();
  (items || []).forEach((row) => {
    const ids = row.store_ids?.length ? row.store_ids : [row.store_id || ''];
    const names = row.store_names?.length ? row.store_names : [row.store_name || ''];
    names.forEach((name, index) => {
      const cleanName = (name || '').trim();
      const id = (ids[index] || cleanName).trim();
      if (cleanName && id) stores.set(id, cleanName);
    });
  });
  const options = [...stores.entries()]
    .sort((a, b) => new Intl.Collator('zh-Hans-u-co-pinyin', { numeric: true, sensitivity: 'base' }).compare(a[1], b[1]))
    .map(([id, name]) => `<option value="${html(id)}" ${id === selectedStore ? 'selected' : ''}>${html(name)}</option>`)
    .join('');
  select.innerHTML = `<option value="">全部门店</option>${options}`;
  select.value = stores.has(selectedStore) ? selectedStore : '';
  return select.value;
}

async function createAdminUser() {
  const msg = $('newAdminMessage');
  msg.className = 'message';
  msg.textContent = '保存中...';
  try {
    await api('/api/admin-users', {
      method: 'POST',
      body: JSON.stringify({
        phone: $('newAdminPhone').value,
        name: $('newAdminName').value,
        store_id: $('newAdminStore').value,
        role: $('newAdminRole').value,
        can_issue_renewal: $('newAdminRole').value === 'issuer' && $('newAdminRenewal').value === '1',
      }),
    });
    msg.className = 'message ok';
    msg.textContent = '客服人员已添加，对方可用手机号获取验证码完成注册';
    $('newAdminPhone').value = '';
    $('newAdminName').value = '';
    $('newAdminRenewal').value = '0';
    await loadAdminUsers();
  } catch (err) {
    msg.className = 'message error';
    msg.textContent = err.message;
  }
}

function syncNewAdminRenewalControl() {
  const role = $('newAdminRole')?.value || '';
  const renewal = $('newAdminRenewal');
  if (!renewal) return;
  const disabled = role !== 'issuer';
  if (disabled) renewal.value = '0';
  renewal.disabled = disabled;
}

async function updateAdminUserRole(userId, role) {
  await api('/api/admin-users/' + encodeURIComponent(userId), {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  });
  await loadAdminUsers();
}

async function updateAdminUserRenewal(userId, canIssueRenewal) {
  await api('/api/admin-users/' + encodeURIComponent(userId), {
    method: 'PATCH',
    body: JSON.stringify({ can_issue_renewal: canIssueRenewal }),
  });
  await loadAdminUsers();
}

async function toggleAdminUser(userId, enabled, name = '') {
  const action = enabled ? '启用' : '停用';
  if (!window.confirm(`确定${action}客服人员「${name || userId}」吗？`)) {
    return;
  }
  await api('/api/admin-users/' + encodeURIComponent(userId), {
    method: 'PATCH',
    body: JSON.stringify({ enabled }),
  });
  await loadAdminUsers();
}

async function deleteAdminUser(userId, name) {
  if (!window.confirm(`确定删除客服人员「${name || userId}」吗？\n\n删除后该人员将失去账号，不能登录；以后可以用同一手机号重新新增。`)) {
    return;
  }
  await api('/api/admin-users/' + encodeURIComponent(userId), {
    method: 'DELETE',
  });
  await loadAdminUsers();
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
  if (scope === 'current') {
    const selected = $('issueOperationStore')?.selectedOptions?.[0]?.textContent || currentAdminProfile.store_name;
    return selected ? [selected] : [];
  }
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

function syncIssueValidityType() {
  const unlimited = $('issueValidityType') && $('issueValidityType').value === 'unlimited';
  if ($('issueDays')) {
    $('issueDays').disabled = unlimited;
  }
}

window.syncIssueValidityType = syncIssueValidityType;

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
    syncIssueTemplateDisplay();
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
  msg.textContent = '';
  try {
    const vinMessage = issueVinValidationMessage();
    updateIssueVinValidation();
    if (vinMessage) {
      throw new Error(vinMessage);
    }
    if (!$('issueWid').value) {
      throw new Error('请先输入车架号并选择客户');
    }
    const template = selectedIssueTemplate();
    if (!template) {
      throw new Error('请先从下拉列表选择券模板');
    }
    if ($('issueUsableStoreScope').value === 'selected' && selectedIssueUsableStoreNames().length === 0) {
      throw new Error('选择指定门店时，请至少选择一个可用门店');
    }
    if (profileStores().length > 1 && !$('issueOperationStore').value) {
      throw new Error('请选择本次发券门店');
    }
    if (!confirmIssueCouponDetail()) {
      msg.textContent = '已取消发券';
      return;
    }
    msg.textContent = '处理中...';
    const data = await api('/api/coupons/issue', {
      method: 'POST',
      body: JSON.stringify({
        wid: $('issueWid').value,
        template_id: template.id,
        quantity: Number($('issueQuantity').value),
        validity_type: $('issueValidityType').value,
        valid_days: Number($('issueDays').value),
        operator: $('operator').value,
        remark: $('issueRemark').value,
        usable_store_scope: $('issueUsableStoreScope').value,
        usable_store_names: selectedIssueUsableStoreNames(),
        operation_store_id: $('issueOperationStore') ? $('issueOperationStore').value : '',
      }),
    });
    msg.className = 'message ok';
    msg.textContent = `发券成功：${data.issued.map((item) => item.code).join('、')}`;
    await loadSummary();
    if ($('issueWid').value) await selectCustomer($('issueWid').value);
  } catch (err) {
    msg.className = 'message error';
    msg.textContent = err.message;
    alert(err.message);
  }
}

function confirmIssueCouponDetail() {
  const template = selectedIssueTemplate();
  const templateText = template ? issueTemplateOptionText(template) : '-';
  const templateRule = template ? (template.rule_text || '该模板暂无使用规则') : '-';
  const quantity = Number($('issueQuantity').value || 0);
  const validity = $('issueValidityType').value === 'unlimited'
    ? '永久有效（2099年1月1日）'
    : `${Number($('issueDays').value || 0)} 天`;
  const scopeText = $('issueUsableStoreScope').selectedOptions[0]?.textContent || '-';
  const stores = currentIssueScopeSelectedNames();
  const storeText = stores.length ? stores.join('、') : scopeText;
  const operationStore = $('issueOperationStore')?.selectedOptions?.[0]?.textContent || '-';
  const customer = [
    $('issueNickname').value || '-',
    $('issuePhone').value || '-',
  ].join(' / ');
  const lines = [
    '请确认是否给该客户发券：',
    '',
    `客户：${customer}`,
    `客户归属门店：${$('issueStore').value || '-'}`,
    `本次发券门店：${operationStore}`,
    `券模板：${templateText}`,
    `使用规则：${templateRule}`,
    `数量：${quantity}`,
    `有效期：${validity}`,
    `使用门店范围：${scopeText}`,
    `可使用门店：${storeText}`,
    `备注：${$('issueRemark').value || '-'}`,
    '',
    '确认后将立即生成券码。',
  ];
  return window.confirm(lines.join('\n'));
}

async function redeemCoupon() {
  const msg = $('redeemMessage');
  const coupon = await previewRedeemCoupon();
  if (!coupon) return;
  const status = normalizeCouponStatus(coupon);
  if (status !== 'unused') {
    msg.className = 'message error';
    msg.textContent = `该券当前不可核销：${coupon.status_text || coupon.status || status}`;
    return;
  }
  if (lastRedeemStoreOptions.length > 1 && !$('redeemStore').value) {
    msg.className = 'message error';
    msg.textContent = '请选择本次核销门店';
    return;
  }
  if (!confirmRedeemCouponDetail(coupon)) {
    msg.className = 'message';
    msg.textContent = '已取消核销';
    return;
  }
  msg.className = 'message';
  msg.textContent = '处理中...';
  try {
    const data = await api('/api/coupons/redeem', {
      method: 'POST',
      body: JSON.stringify({
        code: $('redeemCode').value,
        operator: $('operator').value,
        remark: $('redeemRemark').value,
        redeem_store_id: $('redeemStore') ? $('redeemStore').value : '',
      }),
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

function confirmRedeemCouponDetail(coupon) {
  const customerName = coupon.customer_real_name || coupon.customer_nickname || '-';
  const lines = [
    '请再次确认是否核销这张券：',
    '',
    `券码：${coupon.code || '-'}`,
    `券名称：${coupon.template_name || '-'}`,
    `客户：${customerName} / ${coupon.customer_phone || '-'}`,
    `客户WID：${coupon.customer_wid || '-'}`,
    `客户门店：${coupon.customer_store_name || '-'}`,
    `有效期：${coupon.valid_period || '-'}`,
    `使用门店：${coupon.usable_store_names || '-'}`,
    '',
    '确认后将立即核销，不能重复使用。',
  ];
  return window.confirm(lines.join('\n'));
}

function couponCodeFromScan(value) {
  const text = String(value || '').trim();
  if (!text) return '';
  try {
    const url = new URL(text);
    return (url.searchParams.get('code') || url.pathname.split('/').filter(Boolean).pop() || text).trim();
  } catch (err) {
    return text;
  }
}

function renderRedeemPreview(coupon) {
  const status = normalizeCouponStatus(coupon);
  const customerName = coupon.customer_real_name || coupon.customer_nickname || '-';
  const redeemStoreText = $('redeemStore')?.selectedOptions?.[0]?.textContent || (lastRedeemStoreOptions[0]?.name || '-');
  $('redeemPreview').classList.remove('hidden');
  $('redeemPreview').innerHTML = `
    <div class="kv coupon-detail-grid">
      <div class="key">券码</div><div>${safe(coupon.code)}</div>
      <div class="key">券名称</div><div>${safe(coupon.template_name)}</div>
      <div class="key">状态</div><div>${statusTag(status, status === 'expired' ? '已过期' : (coupon.status_text || coupon.status))}</div>
      <div class="key">客户</div><div>${safe(customerName)} / ${safe(coupon.customer_phone)}</div>
      <div class="key">客户门店</div><div>${safe(coupon.customer_store_name)}</div>
      <div class="key">有效期</div><div>${safe(coupon.valid_period)}</div>
      <div class="key">使用门店</div><div>${safe(coupon.usable_store_names)}</div>
      <div class="key">本次核销门店</div><div>${safe(redeemStoreText)}</div>
    </div>
  `;
}

async function previewRedeemCoupon(codeValue = '') {
  const msg = $('redeemMessage');
  const code = couponCodeFromScan(codeValue || $('redeemCode').value);
  $('redeemCode').value = code;
  $('redeemPreview').classList.add('hidden');
  $('redeemPreview').innerHTML = '';
  if (!code) {
    msg.className = 'message error';
    msg.textContent = '请输入或扫码获取券码';
    return null;
  }

  lastRedeemLookupCode = code;
  msg.className = 'message';
  msg.textContent = '正在查询券码...';
  try {
    const data = await api('/api/coupons/' + encodeURIComponent(code) + '/preview');
    lastRedeemStoreOptions = data.redeem_store_options || [];
    if ($('redeemStore')) {
      $('redeemStore').innerHTML = lastRedeemStoreOptions.map((row) => `<option value="${html(row.id || '')}">${html(row.name || '')}</option>`).join('');
      $('redeemStoreLabel').classList.toggle('hidden', lastRedeemStoreOptions.length <= 1);
    }
    renderRedeemPreview(data.coupon);
    msg.className = data.redeemable ? 'message ok' : 'message error';
    msg.textContent = data.redeemable ? '券码可核销，请确认信息后点击确认核销' : data.message;
    return data.coupon;
  } catch (err) {
    msg.className = 'message error';
    msg.textContent = err.message;
    return null;
  }
}

function scheduleRedeemCouponPreview() {
  if (redeemLookupTimer) clearTimeout(redeemLookupTimer);
  const code = couponCodeFromScan($('redeemCode').value);
  if (!code) {
    lastRedeemLookupCode = '';
    lastRedeemStoreOptions = [];
    if ($('redeemStoreLabel')) $('redeemStoreLabel').classList.add('hidden');
    $('redeemPreview').classList.add('hidden');
    $('redeemPreview').innerHTML = '';
    $('redeemMessage').className = 'message';
    $('redeemMessage').textContent = '';
    return;
  }
  redeemLookupTimer = setTimeout(() => {
    if (code !== lastRedeemLookupCode) previewRedeemCoupon(code);
  }, 600);
}

function stopCouponScanner() {
  if (redeemScannerTimer) {
    clearTimeout(redeemScannerTimer);
    redeemScannerTimer = null;
  }
  if (redeemScannerStream) {
    redeemScannerStream.getTracks().forEach((track) => track.stop());
    redeemScannerStream = null;
  }
  const panel = $('redeemScanner');
  if (panel) panel.classList.add('hidden');
}

function isWechatBrowser() {
  return /MicroMessenger/i.test(navigator.userAgent || '');
}

function currentWechatSignUrl() {
  return window.location.href.split('#')[0];
}

async function ensureWechatScanConfigured() {
  if (wechatScanConfigured) return true;
  if (wechatScanConfigPromise) return wechatScanConfigPromise;
  wechatScanConfigPromise = (async () => {
    if (!window.wx) throw new Error('微信 JS-SDK 未加载，请刷新页面后重试');
    const config = await api('/api/wechat/js-sdk-config?url=' + encodeURIComponent(currentWechatSignUrl()));
    await new Promise((resolve, reject) => {
      window.wx.config({
        debug: false,
        appId: config.appId,
        timestamp: config.timestamp,
        nonceStr: config.nonceStr,
        signature: config.signature,
        jsApiList: ['scanQRCode'],
      });
      window.wx.ready(resolve);
      window.wx.error((err) => reject(new Error(err.errMsg || '微信扫码初始化失败')));
    });
    wechatScanConfigured = true;
    return true;
  })();
  try {
    return await wechatScanConfigPromise;
  } finally {
    if (!wechatScanConfigured) wechatScanConfigPromise = null;
  }
}

async function startWechatCouponScanner() {
  const msg = $('redeemMessage');
  msg.className = 'message';
  msg.textContent = '正在启动微信扫码...';
  try {
    await ensureWechatScanConfigured();
    window.wx.scanQRCode({
      needResult: 1,
      scanType: ['qrCode'],
      success: async (res) => {
        const value = res.resultStr || '';
        await previewRedeemCoupon(value);
      },
      fail: (err) => {
        msg.className = 'message error';
        msg.textContent = `微信扫码失败：${err.errMsg || '请重试'}`;
      },
      cancel: () => {
        msg.className = 'message';
        msg.textContent = '已取消扫码';
      },
    });
  } catch (err) {
    msg.className = 'message error';
    msg.textContent = err.message;
  }
}

async function scanCouponFrame() {
  if (!redeemBarcodeDetector || !redeemScannerStream) return;
  const video = $('redeemScannerVideo');
  try {
    const codes = await redeemBarcodeDetector.detect(video);
    if (codes && codes.length) {
      const value = codes[0].rawValue || '';
      stopCouponScanner();
      await previewRedeemCoupon(value);
      return;
    }
  } catch (err) {
    $('redeemScannerStatus').textContent = `扫码失败：${err.message}`;
  }
  redeemScannerTimer = setTimeout(scanCouponFrame, 350);
}

async function startCouponScanner() {
  const msg = $('redeemMessage');
  msg.className = 'message';
  msg.textContent = '';
  if (isWechatBrowser()) {
    await startWechatCouponScanner();
    return;
  }
  if (!('BarcodeDetector' in window)) {
    msg.className = 'message error';
    msg.textContent = '当前浏览器不支持网页扫码，请使用微信打开或手动输入券码';
    return;
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    msg.className = 'message error';
    msg.textContent = '当前页面无法调用摄像头，请确认使用支持摄像头的浏览器或改用手动输入';
    return;
  }

  stopCouponScanner();
  $('redeemScanner').classList.remove('hidden');
  $('redeemScannerStatus').textContent = '正在启动摄像头...';
  try {
    redeemBarcodeDetector = new BarcodeDetector({ formats: ['qr_code'] });
    redeemScannerStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' } },
      audio: false,
    });
    const video = $('redeemScannerVideo');
    video.srcObject = redeemScannerStream;
    await video.play();
    $('redeemScannerStatus').textContent = '请对准客户手机上的券码二维码';
    await scanCouponFrame();
  } catch (err) {
    stopCouponScanner();
    msg.className = 'message error';
    msg.textContent = `无法启动扫码：${err.message}`;
  }
}

function logQueryParams() {
  const pageSize = Number($('logPageSize')?.value || 50);
  const params = new URLSearchParams({
    page: String(logPage),
    page_size: String(pageSize),
  });
  const from = $('logFilterFrom')?.value || '';
  const to = $('logFilterTo')?.value || '';
  if (from) params.set('from_date', from);
  if (to) params.set('to_date', to);
  return { params, pageSize };
}

async function loadLogs(resetPage = false) {
  if (resetPage) logPage = 1;
  const { params, pageSize } = logQueryParams();
  const data = await api('/api/logs?' + params.toString());
  logTotal = data.total || 0;
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
  const totalPages = Math.max(1, Math.ceil(logTotal / pageSize));
  if ($('logPageInfo')) $('logPageInfo').textContent = `第 ${logPage} / ${totalPages} 页，共 ${logTotal} 条记录`;
  if ($('logPrevPage')) $('logPrevPage').disabled = logPage <= 1;
  if ($('logNextPage')) $('logNextPage').disabled = logPage >= totalPages;
}

async function changeLogPage(step) {
  const pageSize = Number($('logPageSize')?.value || 50);
  const totalPages = Math.max(1, Math.ceil(logTotal / pageSize));
  logPage = Math.min(Math.max(1, logPage + step), totalPages);
  await loadLogs(false);
}

async function resetLogFilters() {
  if ($('logFilterFrom')) $('logFilterFrom').value = '';
  if ($('logFilterTo')) $('logFilterTo').value = '';
  logPage = 1;
  await loadLogs(false);
}

function setDefaultLogExportDates() {
  const today = new Date();
  const yyyy = today.getFullYear();
  const mm = String(today.getMonth() + 1).padStart(2, '0');
  const dd = String(today.getDate()).padStart(2, '0');
  const text = `${yyyy}-${mm}-${dd}`;
  if ($('logExportFrom') && !$('logExportFrom').value) $('logExportFrom').value = text;
  if ($('logExportTo') && !$('logExportTo').value) $('logExportTo').value = text;
}

function downloadLogs() {
  const from = $('logExportFrom')?.value || '';
  const to = $('logExportTo')?.value || '';
  if (!from || !to) {
    alert('请选择开始日期和结束日期');
    return;
  }
  const params = new URLSearchParams({ from_date: from, to_date: to });
  window.location.href = ADMIN_BASE + '/api/logs/export?' + params.toString();
}

document.querySelectorAll('.sidebar button').forEach((btn) => btn.addEventListener('click', () => {
  if (btn.classList.contains('hidden')) return;
  document.querySelectorAll('.sidebar button').forEach((item) => item.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.view').forEach((item) => item.classList.add('hidden'));
  $('view-' + btn.dataset.view).classList.remove('hidden');
  if (btn.dataset.view === 'stores') loadStoreMaintenance();
  if (btn.dataset.view === 'admin-users') loadAdminUsers();
  if (btn.dataset.view === 'logs') {
    setDefaultLogExportDates();
    loadLogs(false);
  }
}));

document.addEventListener('click', (event) => {
  if (!$('couponContextMenu').contains(event.target)) closeCouponContextMenu();
  const templateBox = $('issueTemplateOptions');
  const templateInput = $('issueTemplateSearch');
  if (templateBox && templateInput && !templateBox.contains(event.target) && event.target !== templateInput) {
    closeIssueTemplateOptions();
  }
});

async function bootstrapApp() {
  applyPermissions();
  await loadSummary();
  await loadStores();
  await loadTemplates();
  await searchCustomers();
}

async function init() {
  $('search').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') searchCustomers();
  });
  ['storeFilter', 'customerDeletedStatus', 'becameFrom', 'becameTo', 'joinedFrom', 'joinedTo', 'pageSize'].forEach((id) => {
    if (!$(id)) return;
    $(id).addEventListener('change', () => searchCustomers());
  });
  $('issueVin').addEventListener('input', scheduleIssueCustomerLookup);
  $('issueVin').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      lookupIssueCustomer();
    }
  });
  $('issueTemplateSearch').addEventListener('focus', () => {
    renderIssueTemplateOptions($('issueTemplateSearch').value);
  });
  $('issueTemplateSearch').addEventListener('input', syncIssueTemplateFromSearch);
  $('issueTemplateSearch').addEventListener('change', syncIssueTemplateFromSearch);
  $('issueTemplateSearch').addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeIssueTemplateOptions();
  });
  $('newCustomerPhone').addEventListener('input', scheduleNewCustomerCargeerLookup);
  $('newCustomerPhone').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      lookupNewCustomerCargeer();
    }
  });
  $('redeemCode').addEventListener('input', scheduleRedeemCouponPreview);
  $('redeemCode').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      if (redeemLookupTimer) clearTimeout(redeemLookupTimer);
      previewRedeemCoupon();
    }
  });
  syncIssueValidityType();
  try {
    const data = await api('/api/auth/me');
    showApp(data.username, data.profile || {});
    await bootstrapApp();
  } catch (err) {
    showLogin();
  }
}

init();
