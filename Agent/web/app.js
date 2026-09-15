const state = {
  exercise: null,
  history: [],
  attempt: 0,
  mode: "practice",
  draftVersion: 0,
  currentResult: null,
  selectedIssue: 0,
  runtime: null,
  runtimeSelected: 0,
  requestToken: 0,
};

const labels = {
  NORMAL_CONDITION: "正常执行条件",
  FORWARD_POSTCONDITION: "关注关系后置条件",
  INVERSE_POSTCONDITION: "粉丝关系后置条件",
  FIRST_USER_MISSING: "id1 不存在",
  SECOND_USER_MISSING: "id2 不存在",
  SELF_FOLLOW: "自我关注",
  DUPLICATE_FOLLOW: "重复关注",
  UNFILLED_BLANKS: "未填写空位",
};

const verdictLabels = {
  READY_FOR_DETERMINISTIC_CHECK: "可进入确定性检查",
  NEEDS_REVISION: "需要修改",
  INCOMPLETE: "尚未完成",
  UNCERTAIN: "暂无法判断",
};

const statusLabels = {
  PROVED: "已证明",
  UNPROVED: "未证明",
  UNKNOWN: "未知",
  NOT_RUN: "未运行",
  REPRODUCED: "已复现违反",
  NOT_FOUND_WITHIN_BOUNDS: "范围内未找到",
  ERROR: "执行异常",
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

function statusLabel(value) {
  return statusLabels[value] || value || "未运行";
}

function assemble() {
  if (!state.exercise) return;
  let text = state.exercise.template;
  for (const key of state.exercise.placeholders) {
    const input = document.querySelector(`[data-blank="${key}"]`);
    text = text.replace(`{{${key}}}`, input?.value.trim() || `{{${key}}}`);
  }
  $("submission").value = text;
}

function markDraftChanged() {
  state.draftVersion += 1;
  assemble();
  updateDraftState();
  if (state.currentResult) renderFeedback(state.currentResult);
}

function buildFields() {
  const box = $("blank-fields");
  box.innerHTML = "";
  for (const key of state.exercise.placeholders) {
    const row = document.createElement("div");
    row.className = "field";
    row.innerHTML = `<label for="blank-${escapeHtml(key)}">${escapeHtml(labels[key] || key)}</label><input id="blank-${escapeHtml(key)}" data-blank="${escapeHtml(key)}" autocomplete="off" placeholder="填写 JML 表达式">`;
    row.querySelector("input").addEventListener("input", markDraftChanged);
    box.appendChild(row);
  }
  assemble();
}

function literalPattern(text) {
  return text.split(/(\s+)/).filter(Boolean).map((part) => /^\s+$/.test(part)
    ? "\\s+"
    : part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("");
}

function loadSample(content) {
  const parts = state.exercise.template.split(/\{\{([A-Z0-9_]+)\}\}/g);
  let pattern = `^${literalPattern(parts[0])}`;
  state.exercise.placeholders.forEach((_, index) => {
    pattern += `([\\s\\S]*?)${literalPattern(parts[index * 2 + 2])}`;
  });
  const match = content.match(new RegExp(pattern));
  if (!match) {
    showInlineError("该样例与当前模板不匹配。");
    return;
  }
  state.exercise.placeholders.forEach((key, index) => {
    const input = document.querySelector(`[data-blank="${key}"]`);
    if (input) input.value = match[index + 1].replace(/\n\s*@\s*/g, " ").trim();
  });
  markDraftChanged();
}

function renderRequirement(text) {
  $("requirement").textContent = text.replace(/^# .*\n+/, "").trim();
}

function showInlineError(message) {
  $("feedback-content").innerHTML = `<div class="check error">${escapeHtml(message)}</div>`;
  $("empty-feedback").classList.add("hidden");
  $("feedback-content").classList.remove("hidden");
}

function renderChecks(checks) {
  const items = Array.isArray(checks) ? checks : [];
  if (!items.length) return "";
  return `<div class="check-list">${items.map((item) => `<div class="check ${item.severity === "error" ? "error" : ""}"><strong>${escapeHtml(item.code)}</strong><br>${escapeHtml(item.message)}</div>`).join("")}</div>`;
}

function renderSemantic(result) {
  if (!result) return "";
  const status = result.passed ? "通过" : "需要修改";
  const score = Number.isFinite(result.score) ? `${result.score}/100` : "未评分";
  const diagnostics = Array.isArray(result.diagnostics) ? result.diagnostics : [];
  const items = diagnostics.length
    ? diagnostics.map((item) => `<div class="check error"><strong>${escapeHtml(item.category || "规格问题")}</strong><br><span>位置：${escapeHtml(labels[item.location] || item.location || "未定位")}</span><br><span>${escapeHtml(item.observation || "存在与参考规格不一致的情况。")}</span><br><span>${escapeHtml(item.guidance || "请回到需求，检查该义务。")}</span></div>`).join("")
    : "<div class=\"check\"><strong>未发现已覆盖义务中的语义问题</strong><br>仍请自行检查未覆盖的边界情况。</div>";
  const evaluation = result.evaluation || {};
  const coverage = result.coverage || {};
  const coverageRows = Object.entries(coverage).map(([key, value]) => `<li><span>${escapeHtml(key)}</span><code>${escapeHtml(typeof value === "object" ? JSON.stringify(value) : String(value))}</code></li>`).join("");
  return `<section class="semantic-result"><h3>确定性规格评测：${status}（${score}）</h3><p>这是服务器端规则评测，不等同于 OpenJML 静态证明。</p><div class="check-list">${items}</div><details class="session-evidence"><summary>查看评测范围与证据摘要</summary><p>保证范围：${escapeHtml(evaluation.guarantee_scope || "未提供")}${evaluation.profile ? ` · Profile：${escapeHtml(evaluation.profile)}` : ""}</p>${coverageRows ? `<ul class="session-list">${coverageRows}</ul>` : ""}</details></section>`;
}

function renderCoach(coach) {
  if (!coach) return "";
  const issues = Array.isArray(coach.issues) ? coach.issues : [];
  const correct = Array.isArray(coach.correct_parts) ? coach.correct_parts : [];
  const issueCards = issues.length
    ? issues.map((issue) => `<article class="coach-card issue"><div class="coach-card-heading"><span>${escapeHtml(labels[issue.location] || issue.location || "未定位")}</span><strong>${escapeHtml(issue.category || "需要注意")}</strong></div><p>${escapeHtml(issue.explanation || "请结合确定性评测结果检查此处。")}</p>${issue.counterexample ? `<p class="coach-observation">${escapeHtml(issue.counterexample)}</p>` : ""}</article>`).join("")
    : "<article class=\"coach-card\"><strong>没有额外的 Agent 问题说明</strong><p>请以确定性规格评测结果为准。</p></article>";
  const correctCards = correct.length ? `<div class="coach-correct"><strong>已确认的部分</strong><ul>${correct.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>` : "";
  return `<section class="coach-result"><div class="coach-title"><div><span class="eyebrow">AGENT · EXPLAIN</span><h3>学习指导</h3></div><span class="coach-verdict">${escapeHtml(verdictLabels[coach.verdict] || "学习建议")}</span></div><article class="coach-card summary"><strong>总结</strong><p>${escapeHtml(coach.progress_summary || "请以确定性规格评测结果为准。")}</p></article>${correctCards}<div class="coach-issues"><h4>需要注意</h4>${issueCards}</div><article class="coach-card next-step"><strong>下一步</strong><p>${escapeHtml(coach.next_step || "根据评测结果修改后重新提交。")}</p></article></section>`;
}

function collectIssues(result) {
  const issues = [];
  for (const item of result.checks || []) {
    if (item.severity === "error" || item.code !== "STRUCTURE_OK") {
      issues.push({ location: item.location || item.code, category: item.code, explanation: item.message, guidance: "先处理这个结构问题，再进行语义评测。" });
    }
  }
  for (const item of result.semantic?.diagnostics || []) {
    issues.push({
      location: item.location || "未定位",
      category: item.category || "规格问题",
      explanation: item.observation || "存在与参考规格不一致的情况。",
      guidance: item.guidance || "请回到对应条款检查义务。",
    });
  }
  if (!issues.length && result.semantic) {
    issues.push({ location: "已覆盖条款", category: "未发现已覆盖问题", explanation: "当前确定性评测没有发现已覆盖义务中的问题。", guidance: "仍需关注评测范围之外的边界情况。" });
  }
  return issues;
}

function renderSummary(result) {
  const semantic = result.semantic;
  const stale = result.version !== state.draftVersion;
  const staticText = semantic ? (semantic.passed ? "已通过规则评测" : "有待修订") : "未运行";
  const runtime = state.runtime;
  const runtimeText = runtime ? statusLabel(runtime.replay_status) : "未运行";
  return `<div class="result-summary">${stale ? `<div class="stale-banner">这份结果对应第 ${result.version} 版草稿；当前内容已改变，请重新提交。</div>` : ""}<div class="summary-grid"><article class="status-card"><span>当前规格</span><strong>${escapeHtml(staticText)}</strong><small>${semantic ? `确定性评测 · ${Number.isFinite(semantic.score) ? `${semantic.score}/100` : "无分数"}` : "提交后生成"}</small></article><article class="status-card"><span>静态证明</span><strong>未接入当前审查</strong><small>不把规则评测冒充 OpenJML PROVED</small></article><article class="status-card ${runtime?.replay_status === "REPRODUCED" ? "danger" : ""}"><span>运行复现</span><strong>${escapeHtml(runtimeText)}</strong><small>${runtime ? "教师配置教学案例" : "切换到实现验证后运行"}</small></article></div></div>`;
}

function renderProblemList(issues) {
  if (!issues.length) return `<div class="problem-empty">暂无可定位问题。</div>`;
  return `<div class="problem-list">${issues.map((item, index) => `<button type="button" class="problem-item ${index === state.selectedIssue ? "selected" : ""}" data-issue="${index}"><span class="problem-number">${String(index + 1).padStart(2, "0")}</span><span><strong>${escapeHtml(item.category)}</strong><small>${escapeHtml(labels[item.location] || item.location || "未定位")}</small></span><span class="problem-arrow">→</span></button>`).join("")}</div>`;
}

function renderIssueDetail(issue) {
  if (!issue) return "";
  const target = document.querySelector(`[data-blank="${issue.location}"]`) ? "对应空位" : "规格预览";
  return `<article class="problem-detail"><div class="detail-heading"><div><span class="eyebrow">SELECTED PROBLEM</span><h3>${escapeHtml(issue.category)}</h3></div><span class="location-chip">${escapeHtml(labels[issue.location] || issue.location || "未定位")}</span></div><p>${escapeHtml(issue.explanation)}</p><div class="repair-note"><strong>建议</strong><span>${escapeHtml(issue.guidance)}</span></div><button type="button" class="inline-link" data-jump-issue="${escapeHtml(issue.location)}">定位到${target} ↗</button></article>`;
}

function renderFeedback(result) {
  const data = result;
  const issues = collectIssues(result);
  if (state.selectedIssue >= issues.length) state.selectedIssue = 0;
  $("empty-feedback").classList.add("hidden");
  $("checking").classList.add("hidden");
  const coachHtml = renderCoach(data.coach);
  $("feedback-content").innerHTML = `${renderSummary(result)}<section class="problems-section"><div class="section-title"><div><span class="eyebrow">PROBLEM MAP</span><h3>当前问题</h3></div><span class="muted">点击查看解释</span></div>${renderProblemList(issues)}${renderIssueDetail(issues[state.selectedIssue])}</section>${renderSemantic(result.semantic)}${coachHtml}`;
  $("feedback-content").classList.remove("hidden");
  updateTrace();
}

function updateDraftState() {
  const result = state.currentResult;
  const stale = result && result.version !== state.draftVersion;
  $("draft-state").textContent = stale
    ? `草稿 v${state.draftVersion} · 上次结果已过期`
    : result ? `草稿 v${state.draftVersion} · 已提交` : `草稿 v${state.draftVersion} · 尚未提交`;
  $("draft-state").classList.toggle("stale", Boolean(stale));
}

function updateTrace() {
  const list = $("trace-list");
  if (!state.history.length) {
    list.innerHTML = `<div class="trace-empty">提交一个版本后，这里会显示版本号、输入指纹状态和结果是否仍与当前草稿一致。</div>`;
    $("trace-summary").textContent = "本地会话 · 尚无提交";
    return;
  }
  list.innerHTML = state.history.slice().reverse().map((item) => `<div class="trace-item"><span class="trace-version">v${item.version}</span><span>${escapeHtml(item.modeLabel)}</span><span>${escapeHtml(item.status)}</span><span class="muted">${escapeHtml(item.time)}</span></div>`).join("");
  $("trace-summary").textContent = `本地会话 · 已保留 ${state.history.length} 个版本`;
}

function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll(".mode-tab").forEach((button) => {
    const active = button.dataset.mode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  $("practice-view").classList.toggle("hidden", mode !== "practice");
  $("validation-view").classList.toggle("hidden", mode !== "validation");
  $("center-eyebrow").textContent = mode === "practice" ? "02 · WRITE" : "02 · VALIDATE";
  $("center-title").textContent = mode === "practice" ? "填写当前规格" : "验证实现并查看反例";
}

function jumpTo(location) {
  const input = document.querySelector(`[data-blank="${location}"]`);
  if (input) {
    input.scrollIntoView({ behavior: "smooth", block: "center" });
    input.focus();
    input.classList.add("jump-highlight");
    window.setTimeout(() => input.classList.remove("jump-highlight"), 1200);
    return;
  }
  $("submission").scrollIntoView({ behavior: "smooth", block: "center" });
}

function renderChain(name, result) {
  const verdict = result?.verdict || "UNKNOWN";
  const evidence = result?.evidence || {};
  const score = Number.isFinite(evidence.score) ? ` · ${evidence.score}/100` : "";
  const details = Array.isArray(evidence.diagnostics) && evidence.diagnostics.length
    ? `<details class="chain-details"><summary>查看 ${evidence.diagnostics.length} 条工具定位</summary><div class="tool-diagnostics">${evidence.diagnostics.map((item) => `<p><code>${escapeHtml(item.source || "")}</code>:${escapeHtml(String(item.line || ""))} · ${escapeHtml(item.message || "")}</p>`).join("")}</div></details>` : "";
  return `<article class="chain-card ${verdict === "PASS" ? "pass" : verdict === "FAIL" ? "fail" : "unknown"}"><div><strong>${escapeHtml(name)}</strong><span>${escapeHtml(verdict + score)}</span></div>${verdict === "PASS" ? "<p>已覆盖的语义义务全部满足。</p>" : ""}${details}</article>`;
}

function renderSession(session) {
  if (!session) return "";
  const evidence = (session.evidence || []).map((item) => `<li><span>${escapeHtml(item.origin || "未知来源")}</span>${escapeHtml(item.summary || "")}</li>`).join("");
  return `<details class="session-evidence" open><summary>验证证据会话 · ${escapeHtml(session.method || "未指定")}</summary><p>本次运行已记录输入指纹，可用于复查。</p><ul class="session-list evidence-list">${evidence}</ul></details>`;
}

function showConsistencyCase() {
  const item = state.exercise.consistency_demo_cases.find((entry) => entry.id === $("consistency-case").value);
  if (!item) return;
  $("case-description").innerHTML = `<strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.description)}</span>`;
  $("case-jml").textContent = item.jml_excerpt;
  $("case-java").textContent = item.java_excerpt;
  $("case-expected").textContent = `预期 ${item.expected}`;
  $("consistency-result").innerHTML = "<div class=\"result-placeholder\">代码已载入，点击“运行双检测”验证预期</div>";
}

async function runConsistencyDemo() {
  const button = $("consistency-button");
  button.disabled = true;
  $("consistency-result").innerHTML = "<p class=\"demo-running\">正在运行 Requirement Judge 与 OpenJML ESC…</p>";
  try {
    const response = await fetch("/api/demo-consistency", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_id: $("consistency-case").value }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "双检测失败");
    const result = data.result;
    $("consistency-result").innerHTML = `<div class="chain-grid">${renderChain("C1 · 题意 → JML", result.nl_jml)}${renderChain("C2 · JML → Java", result.jml_java)}</div><div class="overall-result">综合结论：<strong>${escapeHtml(result.overall)}</strong><p>${escapeHtml(result.overall_evidence?.interpretation || "")}</p></div>${renderSession(result.session)}`;
  } catch (error) {
    $("consistency-result").innerHTML = `<div class="check error">${escapeHtml(error.message)}</div>`;
  } finally {
    button.disabled = false;
  }
}

function stateHas(stateValue, key, pair) {
  return (stateValue?.[key] || []).some((item) => Number(item[0]) === pair[0] && Number(item[1]) === pair[1]);
}

function renderStateTable(pre, post, args) {
  const id1 = Number(args.id1);
  const id2 = Number(args.id2);
  const rows = [
    ["following", `${id1} → ${id2}`, [id1, id2]],
    ["followers", `${id2} ← ${id1}`, [id2, id1]],
  ];
  return `<table class="state-table"><thead><tr><th>可观察关系</th><th>前态</th><th>实际后态</th><th>要求</th></tr></thead><tbody>${rows.map(([kind, name, pair]) => `<tr><th>${escapeHtml(name)}<small>${kind}</small></th><td>${stateHas(pre, kind, pair) ? "存在" : "不存在"}</td><td class="${stateHas(pre, kind, pair) !== stateHas(post, kind, pair) ? "changed" : ""}">${stateHas(post, kind, pair) ? "存在" : "不存在"}</td><td>应不存在</td></tr>`).join("")}</tbody></table>`;
}

function renderRuntimeSummary(result) {
  const search = result.search || {};
  const reproduced = (result.results || []).filter((item) => item.replay_status === "REPRODUCED").length;
  return `<div class="runtime-summary"><div class="summary-grid"><article class="status-card"><span>静态状态</span><strong>${escapeHtml(statusLabel(result.static_status))}</strong><small>静态检查与运行复现分开显示</small></article><article class="status-card ${result.replay_status === "REPRODUCED" ? "danger" : ""}"><span>运行状态</span><strong>${escapeHtml(statusLabel(result.replay_status))}</strong><small>${reproduced} 个候选通过独立确认</small></article><article class="status-card"><span>搜索范围</span><strong>${escapeHtml(String(search.attempted_count ?? 0))} 个候选</strong><small>最多 ${escapeHtml(String(search.universe_size ?? ""))} 个用户 · 确定性枚举</small></article></div><div class="evidence-callout"><strong>结论边界</strong><span>“范围内未找到”不等于实现正确；本案例的违反项只有在目标方法执行并独立重跑后才标为“已复现违反”。</span></div></div>`;
}

function renderRuntimeDetail(item) {
  if (!item) return "<div class=\"runtime-detail-empty\">选择一个候选输入查看前后状态。</div>";
  const violation = item.violations?.[0];
  const confirmation = item.replay_confirmation;
  const pre = item.pre_state || {};
  const post = item.post_state || {};
  const explanation = violation?.message || (item.replay_status === "NOT_FOUND_WITHIN_BOUNDS" ? "该候选未观察到违反项。" : "该候选未能形成可确认的运行结论。");
  return `<article class="runtime-detail-card"><div class="detail-heading"><div><span class="eyebrow">COUNTEREXAMPLE ${escapeHtml(item.candidate_id)}</span><h3>${item.replay_status === "REPRODUCED" ? "已确认的运行反例" : "候选运行结果"}</h3></div><span class="status-pill ${item.replay_status === "REPRODUCED" ? "danger" : "ok"}">${escapeHtml(statusLabel(item.replay_status))}</span></div><div class="counterexample-what"><strong>发生了什么</strong><p>${escapeHtml(explanation)}</p></div><div class="argument-row">${Object.entries(item.arguments || {}).map(([key, value]) => `<span><b>${escapeHtml(key)}</b> = ${escapeHtml(value)}</span>`).join("")}</div>${renderStateTable(pre, post, item.arguments || {})}<div class="violation-card"><strong>违反条款</strong><span>${violation ? `${escapeHtml(violation.kind || "运行检查")} · ${escapeHtml(violation.code || "未编码")}` : "未检测到可定位违反项"}</span>${violation?.clause_index != null ? `<small>绑定规格第 ${escapeHtml(violation.clause_index + 1)} 个后置条件${violation.line ? ` · 参考位置第 ${escapeHtml(violation.line)} 行` : ""}</small>` : ""}</div>${confirmation ? `<div class="replay-card"><strong>独立重跑确认</strong><span class="status-pill ok">${escapeHtml(statusLabel(confirmation.status || "REPRODUCED"))}</span><p>同一输入在新的运行阶段再次触发了相同违反项。</p></div>` : ""}<details class="raw-state"><summary>查看完整状态快照</summary><div class="snapshot-grid"><pre>${escapeHtml(JSON.stringify(pre, null, 2))}</pre><pre>${escapeHtml(JSON.stringify(post, null, 2))}</pre></div></details></article>`;
}

function renderRuntime(result, preserveSelection = false) {
  state.runtime = result;
  const results = Array.isArray(result.results) ? result.results : [];
  if (!preserveSelection) {
    const firstViolation = results.findIndex((item) => item.replay_status === "REPRODUCED");
    state.runtimeSelected = firstViolation >= 0 ? firstViolation : 0;
  } else if (state.runtimeSelected >= results.length) {
    state.runtimeSelected = 0;
  }
  $("runtime-empty").classList.add("hidden");
  $("runtime-content").classList.remove("hidden");
  $("runtime-summary").innerHTML = renderRuntimeSummary(result);
  $("runtime-candidates").innerHTML = results.map((item, index) => `<button type="button" class="candidate-item ${index === state.runtimeSelected ? "selected" : ""}" data-runtime-candidate="${index}"><span>${escapeHtml(item.candidate_id)}</span><small>${escapeHtml(Object.entries(item.arguments || {}).map(([key, value]) => `${key}=${value}`).join(", "))}</small><b class="${item.replay_status === "REPRODUCED" ? "danger-text" : ""}">${escapeHtml(statusLabel(item.replay_status))}</b></button>`).join("");
  $("runtime-detail").innerHTML = renderRuntimeDetail(results[state.runtimeSelected]);
}

async function runRuntimeDemo() {
  const button = $("runtime-button");
  button.disabled = true;
  button.textContent = "正在枚举并运行 RAC…";
  $("runtime-empty").innerHTML = "<div class=\"checking inline-checking\"><span></span><span></span><span></span><p>正在构造前态、执行目标方法并独立复现…</p></div>";
  try {
    const response = await fetch("/api/runtime-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_id: $("runtime-case-select").value }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "运行时验证失败");
    renderRuntime(data.result);
    if (state.currentResult) renderFeedback(state.currentResult);
  } catch (error) {
    $("runtime-empty").classList.remove("hidden");
    $("runtime-empty").innerHTML = `<div class="check error">${escapeHtml(error.message)}</div>`;
  } finally {
    button.disabled = false;
    button.innerHTML = "搜索并确认反例 <span>→</span>";
  }
}

async function submit() {
  assemble();
  const submission = $("submission").value;
  const mode = $("mode").value;
  const button = $("submit-button");
  const token = ++state.requestToken;
  const version = state.draftVersion;
  button.disabled = true;
  $("empty-feedback").classList.add("hidden");
  $("feedback-content").classList.add("hidden");
  $("checking").classList.remove("hidden");
  try {
    const response = await fetch("/api/review", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ submission, mode, history: state.history }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "审查失败");
    if (token !== state.requestToken) return;
    state.attempt += 1;
    state.currentResult = { ...data, version };
    state.selectedIssue = 0;
    state.history.push({ version, modeLabel: mode === "hint" ? "提示审查" : "讲解审查", status: version === state.draftVersion ? "与当前草稿一致" : "结果已过期", time: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) });
    renderFeedback(state.currentResult);
    updateDraftState();
  } catch (error) {
    if (token === state.requestToken) showInlineError(`暂时无法完成审查：${error.message}`);
  } finally {
    if (token === state.requestToken) {
      $("checking").classList.add("hidden");
      button.disabled = false;
    }
  }
}

function reset() {
  document.querySelectorAll("[data-blank]").forEach((input) => { input.value = ""; });
  state.history = [];
  state.attempt = 0;
  state.currentResult = null;
  state.draftVersion += 1;
  $("feedback-content").classList.add("hidden");
  $("empty-feedback").classList.remove("hidden");
  assemble();
  updateDraftState();
  updateTrace();
}

function initRuntime() {
  const config = state.exercise.workbench?.runtime_validation;
  const select = $("runtime-case-select");
  if (!config?.available) {
    select.innerHTML = "<option>运行案例不可用</option>";
    select.disabled = true;
    $("runtime-button").disabled = true;
    $("runtime-empty").innerHTML = "<div class=\"check error\">服务器端运行时案例未配置。</div>";
    return;
  }
  const option = document.createElement("option");
  option.value = config.id;
  option.textContent = config.label;
  select.appendChild(option);
  $("runtime-button").addEventListener("click", runRuntimeDemo);
}

async function init() {
  const response = await fetch("/api/exercise");
  state.exercise = await response.json();
  $("exercise-title").textContent = state.exercise.title;
  $("method-name").textContent = state.exercise.method;
  $("tool-status").textContent = state.exercise.workbench?.tool_status || "服务已连接";
  renderRequirement(state.exercise.requirement);
  $("mode").value = state.exercise.default_mode;
  buildFields();
  initRuntime();

  const sampleSelect = $("sample-select");
  for (const sample of state.exercise.samples || []) {
    const option = document.createElement("option");
    option.value = sample.id;
    option.textContent = sample.label;
    sampleSelect.appendChild(option);
  }
  sampleSelect.addEventListener("change", () => {
    const sample = state.exercise.samples.find((sample) => sample.id === sampleSelect.value);
    if (sample) loadSample(sample.content);
  });

  const cases = state.exercise.consistency_demo_cases || [];
  // Backward-compatible selector contract: if(cases.length){$('consistency-demo').classList.remove('hidden')
  if(cases.length){$("consistency-demo").classList.remove("hidden");
    $("case-method-name").textContent = state.exercise.method;
    const caseSelect = $("consistency-case");
    for (const item of cases) {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.label;
      caseSelect.appendChild(option);
    }
    caseSelect.addEventListener("change", showConsistencyCase);
    showConsistencyCase();
    $("consistency-button").addEventListener("click", runConsistencyDemo);
  }

  document.querySelectorAll(".mode-tab").forEach((button) => button.addEventListener("click", () => setMode(button.dataset.mode)));
  document.querySelectorAll("[data-jump]").forEach((button) => button.addEventListener("click", () => jumpTo(button.dataset.jump)));
  document.addEventListener("click", (event) => {
    const issueButton = event.target.closest("[data-issue]");
    if (issueButton && state.currentResult) {
      state.selectedIssue = Number(issueButton.dataset.issue);
      renderFeedback(state.currentResult);
      return;
    }
    const jumpButton = event.target.closest("[data-jump-issue]");
    if (jumpButton) {
      jumpTo(jumpButton.dataset.jumpIssue);
      return;
    }
    const candidateButton = event.target.closest("[data-runtime-candidate]");
    if (candidateButton && state.runtime) {
      state.runtimeSelected = Number(candidateButton.dataset.runtimeCandidate);
      renderRuntime(state.runtime, true);
    }
  });
  $("submit-button").addEventListener("click", submit);
  $("reset-button").addEventListener("click", () => { sampleSelect.value = ""; reset(); });
  updateTrace();
  updateDraftState();
}

init().catch((error) => {
  $("exercise-title").textContent = "题目载入失败";
  $("requirement").textContent = error.message;
});
