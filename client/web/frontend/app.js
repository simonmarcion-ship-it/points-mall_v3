const $ = (id) => document.getElementById(id);
let profileRefreshTimer = null;
let profileRefreshAttempts = 0;

function show(view) {
  ["loadingView", "bindView", "profileView", "couponDetailView"].forEach((id) => {
    const el = $(id);
    if (el) el.classList.add("hidden");
  });
  $(view).classList.remove("hidden");
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const contentType = res.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new Error("接口返回的不是 JSON，请重启客户端后端服务并强制刷新页面");
  }
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "请求失败");
  return data;
}

function safe(value) {
  return value === null || value === undefined || value === "" ? "-" : String(value);
}

function html(value) {
  return safe(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function statusText(status, fallback) {
  if (fallback) return fallback;
  return {
    unused: "未使用",
    used: "已使用",
    expired: "已过期",
    voided: "已作废",
  }[status] || status || "-";
}

function bindCouponClicks() {
  document.querySelectorAll("[data-coupon-code]").forEach((card) => {
    card.addEventListener("click", () => openCouponDetail(card.dataset.couponCode));
  });
}

function renderCoupons(items) {
  if (!items.length) {
    $("couponList").innerHTML = '<div class="empty">当前没有优惠券</div>';
    return;
  }

  $("couponList").innerHTML = items.map((item) => `
    <article class="coupon" data-coupon-code="${html(item.code)}">
      <div class="coupon-title">
        <span>${html(item.template_name)}</span>
        <span class="tag ${html(item.status)}">${html(statusText(item.status, item.status_text))}</span>
      </div>
      <div class="coupon-meta">
        <div>券码：${html(item.code)}</div>
        <div>有效期：${html(item.valid_period || [item.valid_start, item.valid_end].filter(Boolean).join(" 至 "))}</div>
      </div>
    </article>
  `).join("");
  bindCouponClicks();
}

function renderRules(text) {
  const rules = String(text || "")
    .split(/\n+/)
    .map((line) => line.replace(/^\s*\d+[、.．]\s*/, "").trim())
    .filter(Boolean);

  $("detailRules").innerHTML = (rules.length ? rules : ["暂无使用规则说明"])
    .map((line) => `<li>${html(line)}</li>`)
    .join("");
}

async function openCouponDetail(code) {
  if (!code || code === "-") return;
  try {
    const data = await api(`/api/client/coupons/${encodeURIComponent(code)}`);
    const coupon = data.coupon;
    $("detailStatus").textContent = statusText(coupon.status, coupon.status_text);
    $("detailDiscount").textContent = safe(coupon.discount_text || "无使用门槛");
    $("detailName").textContent = safe(coupon.template_name);
    $("detailPeriod").textContent = safe(coupon.valid_period || [coupon.valid_start, coupon.valid_end].filter(Boolean).join(" 至 "));
    $("detailCode").textContent = safe(coupon.code).replace(/(.{4})/g, "$1 ").trim();
    $("detailStoreScope").textContent = safe(coupon.scope_text || coupon.usable_store_names);
    $("detailProductScope").textContent = safe(coupon.validity_text || coupon.valid_period || [coupon.valid_start, coupon.valid_end].filter(Boolean).join(" 至 "));
    renderRules(coupon.rule_text);
    show("couponDetailView");
  } catch (error) {
    alert(error.message);
  }
}

function backToProfile() {
  show("profileView");
}

async function loadData(showLoading = true) {
  if (showLoading) show("loadingView");
  try {
    const profile = await api("/api/client/me");
    const coupons = await api("/api/client/coupons");
    const customer = profile.customer;

    $("nickname").textContent = safe(customer.nickname || customer.phone || "车主");
    $("memberLine").textContent = `${safe(customer.level_name || customer.member_card || "普通会员")} · ${safe(customer.store_name || "未绑定门店")}`;
    $("availablePoint").textContent = safe(customer.available_point || "0");
    $("totalPoint").textContent = safe(customer.total_point || "0");
    $("avatar").textContent = String(customer.nickname || customer.phone || "车").slice(0, 1);
    renderCoupons(coupons.items || []);
    if (showLoading || ($("couponDetailView").classList.contains("hidden") && $("profileView").classList.contains("hidden"))) {
      show("profileView");
    }
  } catch (error) {
    show("bindView");
  }
}

function startProfileRefreshPolling() {
  clearInterval(profileRefreshTimer);
  profileRefreshAttempts = 0;
  profileRefreshTimer = setInterval(async () => {
    profileRefreshAttempts += 1;
    try {
      await loadData(false);
    } catch (error) {
      console.warn("profile refresh failed", error);
    }
    if (profileRefreshAttempts >= 12) {
      clearInterval(profileRefreshTimer);
      profileRefreshTimer = null;
    }
  }, 3000);
}

async function bindPhone(event) {
  event.preventDefault();
  $("bindMessage").textContent = "";
  try {
    await api("/api/client/bind-phone", {
      method: "POST",
      body: JSON.stringify({
        phone: $("phoneInput").value,
        sms_code: $("codeInput").value,
      }),
    });
    await loadData();
    startProfileRefreshPolling();
  } catch (error) {
    $("bindMessage").textContent = error.message;
  }
}

async function logout() {
  try {
    await api("/api/client/logout", { method: "POST" });
  } catch (error) {
    console.warn("logout request failed", error);
  }
  $("phoneInput").value = "";
  $("codeInput").value = "";
  $("bindMessage").textContent = "";
  show("bindView");
}

loadData();
