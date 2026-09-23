const $ = (id) => document.getElementById(id);

const state = {
  exercise: null,
  exercises: [],
  drafts: {},
  jmlMode: "template",
  jmlSource: "",
  java: null,
  history: [],
  result: null,
  issues: [],
  selectedIssue: 0,
  busy: false,
  reviewRequest: 0,
  lastSubmittedRevision: 0,
  draftRevision: 0,
  exerciseRequest: 0,
  loadedCaseId: null,
};

const FIELD_LABELS = {
  NORMAL_CONDITION: "正常行为前置条件",
  FORWARD_POSTCONDITION: "关注方后置条件",
  INVERSE_POSTCONDITION: "被关注方后置条件",
  FIRST_USER_MISSING: "第一个用户不存在",
  SECOND_USER_MISSING: "第二个用户不存在",
  SELF_FOLLOW: "自己关注自己",
  DUPLICATE_FOLLOW: "重复关注",
  PRE: "适用条件",
  POST_FORWARD: "关注方后置条件",
  POST_INVERSE: "粉丝方后置条件",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function shortText(value, limit = 240) {
  const text = String(value ?? "").trim();
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

function statusLabel(value) {
  const labels = {
    PASS: "通过",
    DATA_POINTS_MATCH: "数据点一致",
    DATA_POINTS_DIFFER: "存在数据点差异",
    SPEC_CHECK_ERROR: "规格检查出错",
    PROVED: "已证明",
    READY: "已识别",
    CHECKED: "已完成",
    AVAILABLE: "可用",
    FAIL: "未通过",
    SPECIFICATION_INCORRECT: "规格不正确",
    IMPLEMENTATION_INCORRECT: "实现不满足规格",
    SPECIFICATION_AND_IMPLEMENTATION_INCORRECT: "规格与实现均需修正",
    UNPROVED: "未证明",
    UNKNOWN: "未知",
    ERROR: "检查出错",
    TIMEOUT: "超时",
    INCOMPLETE: "未完成",
    INCOMPATIBLE: "不兼容",
    NOT_PROVIDED: "未添加",
    NOT_RUN: "未运行",
    UNSUPPORTED: "暂不支持",
    REPRODUCED: "已复现反例",
    CONFIRMED_VIOLATION: "已确认违反",
    FAILURE_OBSERVED_UNLOCATED: "发现失败但未定位",
    EXECUTION_ERROR: "执行错误",
    CHECK_ERROR: "检查配置错误",
    NOT_FOUND_WITHIN_BOUNDS: "范围内未找到反例",
    NO_VALID_CANDIDATES: "未执行有效测试",
    UNLOCATED_FAILURE: "发现失败但未完成定位",
    EVIDENCE_CONFLICT: "证据冲突待排查",
    COMPLETED_WITH_ERRORS: "完成但有运行错误",
  };
  return labels[String(value || "").toUpperCase()] || String(value || "未知");
}

function statusClass(value) {
  const text = String(value || "").toUpperCase();
  if (["PASS", "PROVED", "READY", "CHECKED", "DATA_POINTS_MATCH"].includes(text)) return "good";
  if (["FAIL", "UNPROVED", "ERROR", "TIMEOUT", "INCOMPLETE", "INCOMPATIBLE", "REPRODUCED", "CONFIRMED_VIOLATION", "EXECUTION_ERROR", "CHECK_ERROR", "FAILURE_OBSERVED_UNLOCATED", "UNLOCATED_FAILURE", "EVIDENCE_CONFLICT", "DATA_POINTS_DIFFER", "SPEC_CHECK_ERROR", "SPECIFICATION_INCORRECT", "IMPLEMENTATION_INCORRECT", "SPECIFICATION_AND_IMPLEMENTATION_INCORRECT"].includes(text)) return "bad";
  return "neutral";
}

function currentSubmission() {
  if (state.java?.contractSource === "embedded" && state.java.source.includes("/*@")) {
    return state.java.source;
  }
  if (state.jmlMode === "template") return assemble();
  return state.jmlSource || $("jml-paste").value || "";
}

function hasMeaningfulDraft() {
  if (state.java) return true;
  if (state.jmlMode !== "template") return Boolean(currentSubmission().trim());
  return [...document.querySelectorAll("[data-placeholder]")].some((field) => field.value.trim());
}

function assemble() {
  if (!state.exercise) return "";
  let output = state.exercise.template;
  document.querySelectorAll("[data-placeholder]").forEach((field) => {
    output = output.replaceAll(`{{${field.dataset.placeholder}}}`, field.value.trim() || `{{${field.dataset.placeholder}}}`);
  });
  return output;
}

function setDraftState(text, kind = "") {
  const node = $("draft-state");
  node.textContent = text;
  node.className = `draft-state ${kind}`;
}

function updatePreview() {
  state.draftRevision += 1;
  const source = currentSubmission();
  $("submission").value = source;
  const ready = source.trim() && !/\{\{[^}]+\}\}/.test(source);
  $("spec-status").textContent = ready ? "已填写" : "未完成";
  $("spec-status").className = `inline-status ${ready ? "good" : "neutral"}`;
  setDraftState(ready ? "已修改" : "草稿", ready ? "changed" : "");
}

function renderRequirement() {
  const raw = state.exercise.requirement || "";
  const lines = raw.split(/\r?\n/);
  $("requirement-short").textContent = shortText(lines.filter(Boolean).find((line) => !line.startsWith("#")) || raw, 180);
  $("requirement").innerHTML = lines.map((line) => {
    if (!line.trim()) return "<div class=\"requirement-gap\"></div>";
    if (line.startsWith("#")) return `<h4>${escapeHtml(line.replace(/^#+\s*/, ""))}</h4>`;
    if (/^[-*]\s/.test(line)) return `<p class=\"requirement-item\">${escapeHtml(line.replace(/^[-*]\s*/, ""))}</p>`;
    return `<p>${escapeHtml(line)}</p>`;
  }).join("");
}

function renderFields() {
  const placeholders = state.exercise.placeholders || [];
  $("blank-fields").innerHTML = placeholders.map((name, index) => `
    <label class="field-row">
      <span class="field-label"><span>${String(index + 1).padStart(2, "0")}</span>${escapeHtml(FIELD_LABELS[name] || name)}</span>
      <textarea data-placeholder="${escapeHtml(name)}" rows="2" spellcheck="false" placeholder="填写 ${escapeHtml(name)}…"></textarea>
    </label>
  `).join("");
  document.querySelectorAll("[data-placeholder]").forEach((field) => field.addEventListener("input", updatePreview));
  updatePreview();
}

function renderSamples() {
  const select = $("sample-select");
  select.innerHTML = '<option value="">加载示例…</option>';
  (state.exercise.samples || []).forEach((sample) => {
    const option = document.createElement("option");
    option.value = sample.id;
    option.textContent = sample.label;
    select.appendChild(option);
  });
  select.onchange = () => {
    const sample = state.exercise.samples.find((item) => item.id === select.value);
    if (!sample) return;
    if (hasMeaningfulDraft() && !window.confirm("加载示例会替换当前规格草稿，继续吗？")) {
      select.value = "";
      return;
    }
    setJmlMode("paste");
    $("jml-paste").value = sample.content;
    state.jmlSource = sample.content;
    $("jml-import-status").textContent = `已加载：${sample.label}`;
    updatePreview();
  };
}

function saveExerciseDraft() {
  if (!state.exercise) return;
  const fields = {};
  document.querySelectorAll("[data-placeholder]").forEach((field) => { fields[field.dataset.placeholder] = field.value; });
  state.drafts[state.exercise.id] = {
    jmlMode: state.jmlMode,
    jmlSource: currentSubmission(),
    java: state.java ? { ...state.java } : null,
    fields,
    history: state.history,
    loadedCaseId: state.loadedCaseId,
  };
}

function restoreExerciseDraft() {
  const draft = state.drafts[state.exercise.id];
  state.jmlMode = "template";
  state.jmlSource = "";
  state.java = null;
  state.loadedCaseId = draft?.loadedCaseId || null;
  state.history = draft?.history || [];
  $("jml-paste").value = "";
  $("java-paste").value = "";
  renderFields();
  if (draft) {
    Object.entries(draft.fields || {}).forEach(([name, value]) => {
      const field = document.querySelector(`[data-placeholder="${CSS.escape(name)}"]`);
      if (field) field.value = value;
    });
    setJmlMode(draft.jmlMode || "template");
    state.jmlSource = draft.jmlSource || "";
    if (state.jmlMode !== "template") $("jml-paste").value = state.jmlSource;
    state.java = draft.java;
    if (state.java) $("java-paste").value = state.java.source || "";
  } else {
    setJmlMode("template");
  }
  renderJavaMeta(state.java?.preflight || null);
  if (state.loadedCaseId && (state.exercise.upload_cases || []).some((item) => item.id === state.loadedCaseId)) {
    $("upload-case-select").value = state.loadedCaseId;
  }
  updatePreview();
  updateSubmitButton();
}

async function loadExercise(exerciseId, { preserve = true } = {}) {
  if (preserve) saveExerciseDraft();
  const requestId = ++state.exerciseRequest;
  state.reviewRequest += 1;
  const response = await fetch(`/api/exercise?id=${encodeURIComponent(exerciseId)}`);
  const exercise = await readJsonResponse(response, "题目加载失败");
  if (requestId !== state.exerciseRequest) return;
  state.exercise = exercise;
  state.result = null;
  state.issues = [];
  state.selectedIssue = 0;
  $("exercise-select").value = exercise.id;
  $("exercise-title").textContent = exercise.title;
  $("exercise-method").textContent = `目标方法：${exercise.method} · 材料版本 ${exercise.material_version}`;
  renderRequirement();
  renderSamples();
  renderUploadCases();
  restoreExerciseDraft();
  renderHistory();
  $("empty-feedback").classList.remove("hidden");
  $("feedback-content").classList.add("hidden");
  $("submit-message").textContent = exercise.workbench?.runtime_status === "AVAILABLE"
    ? "本题支持静态验证与运行诊断。"
    : "本题当前支持规格评测与静态验证；运行反例尚未开放。";
}

function renderUploadCases() {
  const cases = state.exercise.upload_cases || [];
  const loader = $("upload-case-loader");
  const select = $("upload-case-select");
  loader.classList.toggle("hidden", !cases.length);
  select.innerHTML = cases.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`).join("");
  if (state.loadedCaseId && cases.some((item) => item.id === state.loadedCaseId)) select.value = state.loadedCaseId;
}

function loadUploadCase() {
  const item = (state.exercise.upload_cases || []).find((entry) => entry.id === $("upload-case-select").value);
  if (!item) return;
  if (hasMeaningfulDraft() && !window.confirm("载入成套案例会替换当前 JML 与 Java 草稿，继续吗？")) return;
  state.reviewRequest += 1;
  state.result = null;
  state.issues = [];
  state.loadedCaseId = item.id;
  setJmlMode("paste");
  state.jmlSource = item.jml?.content || "";
  $("jml-paste").value = state.jmlSource;
  setJavaSource(item.java?.content || "", item.java?.filename || "Java.java");
  $("jml-import-status").textContent = `已载入成套案例：${item.label}`;
  $("submit-message").textContent = item.intentional_defect
    ? `演示缺陷：${item.intentional_defect}`
    : "已载入正确基准案例。";
  $("empty-feedback").classList.remove("hidden");
  $("feedback-content").classList.add("hidden");
  updatePreview();
  updateSubmitButton();
}

function setJmlMode(mode) {
  if (!state.exercise) return;
  if (state.jmlMode === "template" && mode !== "template") state.jmlSource = assemble();
  state.jmlMode = mode;
  document.querySelectorAll("[data-jml-mode]").forEach((tab) => tab.classList.toggle("active", tab.dataset.jmlMode === mode));
  $("jml-template-pane").classList.toggle("hidden", mode !== "template");
  $("jml-paste-pane").classList.toggle("hidden", mode !== "paste");
  $("jml-file-pane").classList.toggle("hidden", mode !== "file");
  if (mode === "paste" && !$('jml-paste').value) $("jml-paste").value = state.jmlSource;
  updatePreview();
}

function renderJavaMeta(preflight = null) {
  const status = $("implementation-status");
  const meta = $("java-meta");
  if (!state.java) {
    status.textContent = "未添加";
    status.className = "inline-status";
    meta.textContent = "未添加 Java 实现。";
    $("scope-implementation").textContent = "· 未添加实现";
    $("remove-java").classList.add("hidden");
    $("java-contract-choice").classList.add("hidden");
    return;
  }
  const result = preflight || state.java.preflight;
  const code = result?.status || "READY";
  status.textContent = statusLabel(code);
  status.className = `inline-status ${statusClass(code)}`;
  const facts = [state.java.filename];
  if (result?.class_name) facts.push(`class ${result.class_name}`);
  if (result?.method) facts.push(result.method);
  meta.innerHTML = `<strong>${escapeHtml(facts.join(" · "))}</strong><br><span>${escapeHtml(result?.message || "等待检查")}</span>`;
  $("scope-implementation").textContent = "· 将检查实现";
  $("remove-java").classList.remove("hidden");
  $("java-contract-choice").classList.toggle("hidden", !result?.embedded_jml);
}

async function preflightJava() {
  if (!state.java) return;
  const response = await fetch("/api/preflight", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      exercise_id: state.exercise.id,
      submission: currentSubmission(),
      source_mode: state.jmlMode,
      java_source: state.java.source,
      java_filename: state.java.filename,
    }),
  });
  const data = await response.json();
  state.java.preflight = data.java;
  renderJavaMeta(data.java);
}

function readFile(file, callback) {
  const reader = new FileReader();
  reader.onload = () => callback(String(reader.result || ""), file.name);
  reader.onerror = () => $("submit-message").textContent = "文件读取失败，请改用粘贴方式。";
  reader.readAsText(file, "utf-8");
}

function setJavaSource(source, filename) {
  state.java = { source, filename, contractSource: "page", preflight: null };
  $("java-paste").value = source;
  renderJavaMeta();
  preflightJava().catch(() => {
    renderJavaMeta({ status: "ERROR", message: "无法完成 Java 预检。" });
  });
}

function removeJava() {
  state.java = null;
  $("java-file").value = "";
  $("java-paste").value = "";
  $("java-paste").classList.add("hidden");
  renderJavaMeta();
  updateSubmitButton();
}

function downloadTemplate() {
  const template = state.exercise?.implementation_template;
  if (!template) {
    $("submit-message").textContent = "当前练习没有提供实现模板。";
    return;
  }
  const blob = new Blob([template.content], { type: "text/plain;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = template.filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

function updateSubmitButton() {
  $("submit-button").textContent = state.java ? "开始检查" : "检查规格";
}

function setChecking(busy, status = "准备检查材料…") {
  state.busy = busy;
  $("submit-button").disabled = busy;
  $("checking-panel").classList.toggle("hidden", !busy);
  $("checking-status").textContent = status;
  if (!busy) return;
  document.querySelectorAll("[data-stage]").forEach((node) => node.classList.remove("active", "done"));
  $("checking-panel").querySelector('[data-stage="material"]').classList.add("active");
}

function updateCheckingStage(stage, status) {
  $("checking-status").textContent = status;
  const nodes = [...document.querySelectorAll("[data-stage]")];
  const index = nodes.findIndex((node) => node.dataset.stage === stage);
  nodes.forEach((node, nodeIndex) => {
    node.classList.toggle("done", nodeIndex < index);
    node.classList.toggle("active", nodeIndex === index);
  });
}

function resultStatus(data) {
  if (!data) return "NOT_RUN";
  if (data.passed === true) return "PASS";
  if (data.passed === false) return data.score === 0 ? "FAIL" : "UNPROVED";
  return data.status || data.verdict || "UNKNOWN";
}

function issue(location, category, explanation, extra = {}) {
  return { location, category, explanation, ...extra };
}

function collectIssues(data) {
  const list = [];
  (data.checks || []).forEach((item) => {
    if (!["STRUCTURE_OK", "SPEC_READY", "MATERIAL_READY"].includes(item.code)) {
      list.push(issue(item.location || "提交规格", item.category || "提交材料", item.observation || item.guidance || "请检查提交内容。", { source: "spec" }));
    }
  });
  (data.semantic?.diagnostics || []).forEach((item) => {
    list.push(issue(item.location || "规格", item.category || item.code || "规格问题", item.observation || item.message || item.guidance || "语义检查未通过。", { source: "semantic", technical: item }));
  });
  const implementation = data.implementation;
  (implementation?.static_result?.diagnostics || implementation?.static?.diagnostics || implementation?.consistency?.jml_java?.diagnostics || []).forEach((item) => {
    list.push(issue(item.location || "Java 实现", item.category || item.code || "实现问题", item.observation || item.message || item.guidance || "实现未满足当前规格。", { source: "implementation", technical: item }));
  });
  if (implementation && ["INCOMPATIBLE", "ERROR", "TIMEOUT"].includes(implementation.status)) {
    list.push(issue("Java 实现", statusLabel(implementation.status), implementation.message || implementation.preflight?.message || "实现检查没有完成。", { source: "implementation" }));
  }
  const runtime = implementation?.runtime;
  const runtimeResult = runtime?.result;
  const reproduced = confirmedCounterexamples(runtimeResult || runtime);
  const errors = Array.isArray(runtime?.errors)
    ? runtime.errors
    : Array.isArray(runtimeResult?.errors) ? runtimeResult.errors : [];
  const unlocated = Array.isArray(runtime?.unconfirmed_observations)
    ? runtime.unconfirmed_observations
    : Array.isArray(runtimeResult?.unconfirmed_observations) ? runtimeResult.unconfirmed_observations : [];
  if (runtime && runtime.status === "UNSUPPORTED") {
    list.push(issue("运行诊断", "暂不支持", runtime.message || "当前运行适配器暂不支持这份实现。", { source: "runtime" }));
  } else if (runtime) {
    if (reproduced.length) {
      list.push(issue("运行诊断", "已复现反例", "同一输入在独立重跑中违反了同一条绑定规格义务。", { source: "runtime", counterexamples: reproduced, counterexampleTitle: "已确认运行反例" }));
    }
    if (unlocated.length) {
      list.push(issue("运行诊断", "发现失败但未完成定位", "观察到了 JML 运行失败，但还不能归属到一条稳定规格义务；它不会被列为已确认反例。", { source: "runtime", counterexamples: unlocated, counterexampleTitle: "未确认运行观察" }));
    }
    if (errors.length || runtime.status === "ERROR" || runtime.replay_status === "ERROR" || runtime.replay_status === "TIMEOUT") {
      list.push(issue("运行诊断", errors.length ? "执行错误" : statusLabel(runtime.replay_status), runtime.message || "部分或全部候选执行失败；错误不会被解释为没有发现反例。", { source: "runtime", technical: errors.length ? errors : runtime }));
    }
    if (!reproduced.length && !unlocated.length && !errors.length && runtime.replay_status === "NO_VALID_CANDIDATES") {
      list.push(issue("运行诊断", "未执行有效测试", "没有满足前置条件的候选输入，本次没有执行目标方法。", { source: "runtime" }));
    }
    if (runtime.conclusion === "EVIDENCE_CONFLICT") {
      list.push(issue("运行诊断", "证据冲突待排查", "静态验证与运行证据不一致，请核对绑定、工具配置和执行适配器。", { source: "runtime" }));
    }
  }
  return list;
}

function renderStatusCard(title, value, detail) {
  const label = statusLabel(value);
  return `<div class="status-card"><div class="status-card-title">${escapeHtml(title)}</div><div class="status-value ${statusClass(value)}">${escapeHtml(label)}</div><div class="status-detail">${escapeHtml(detail || "")}</div></div>`;
}

function renderCounterexample(counterexamples, title = "已确认运行反例") {
  if (!counterexamples?.length) return "";
  return `<div class="counterexample-box"><div class="counterexample-title">${escapeHtml(title)}</div>${counterexamples.slice(0, 3).map((item, index) => {
    const violation = item?.violations?.[0];
    const args = Object.entries(item?.arguments || {}).map(([key, value]) => `${key}=${value}`).join(", ");
    const pre = item?.pre_state ? JSON.stringify(item.pre_state) : "执行中止，未取得前态快照";
    const post = item?.post_state ? JSON.stringify(item.post_state) : "执行中止，未取得后态快照";
    return `<div class="counterexample-item"><strong>案例 ${index + 1} · ${escapeHtml(item?.candidate_id || "未命名")}</strong><p><b>输入：</b>${escapeHtml(args || "未记录")}</p><div class="state-pair"><div><span>调用前</span><code>${escapeHtml(pre)}</code></div><div><span>实际后</span><code>${escapeHtml(post)}</code></div></div><p><b>违反：</b>${escapeHtml(violation?.message || (item?.rac_failure ? "OpenJML RAC 报告了可定位的运行违反。" : "绑定规格义务未满足。"))}</p><p class="evidence-note">证据：${escapeHtml((item?.evidence_origin || []).join("、") || "运行检查")} · ${escapeHtml(statusLabel(item?.confirmation_status || "REPLAY_CONFIRMED"))}</p><details class="technical-detail"><summary>查看技术详情</summary><pre>${escapeHtml(JSON.stringify(item, null, 2))}</pre></details></div>`;
  }).join("")}</div>`;
}

function confirmedCounterexamples(result) {
  return Array.isArray(result?.confirmed_counterexamples) ? result.confirmed_counterexamples : [];
}

function runtimeSummary(runtime) {
  const search = runtime?.search || runtime?.result?.search || {};
  if (!runtime) return "未提交 Java，实现检查未运行";
  if (runtime.status !== "CHECKED" && runtime.message) return runtime.message;
  return [
    `候选 ${search.generated_count ?? 0}`,
    `执行 ${search.executed_count ?? 0}`,
    `确认反例 ${search.confirmed_count ?? 0}`,
    `错误 ${search.error_count ?? 0}`,
  ].join(" · ");
}

function demoChainClass(verdict) {
  const value = String(verdict || "UNKNOWN").toUpperCase();
  return value === "PASS" ? "pass" : value === "FAIL" ? "fail" : "unknown";
}

function demoChainLabel(key) {
  return key === "nl_jml" ? "需求 → JML" : "JML → Java";
}

function renderDemoDiagnostics(chain, chainKey) {
  const diagnostics = Array.isArray(chain?.diagnostics) ? chain.diagnostics : [];
  if (!diagnostics.length) {
    const message = String(chain?.verdict || "UNKNOWN").toUpperCase() === "PASS"
      ? "这条检查链没有发现需要修改的问题。"
      : "当前没有可展示的具体诊断。";
    return `<div class="diagnostic-empty">${escapeHtml(message)}</div>`;
  }
  return `<div class="diagnostic-list">${diagnostics.map((item, index) => {
    const lines = Array.isArray(item.lines) && item.lines.length ? `第 ${item.lines.join("、")} 行` : "未提供源码行";
    return `<article class="diagnostic-card"><div class="diagnostic-top"><span class="diagnostic-index">${String(index + 1).padStart(2, "0")}</span><span class="diagnostic-code">${escapeHtml(item.code || "DIAGNOSTIC")}</span><span class="diagnostic-line">${escapeHtml(lines)}</span></div><div class="diagnostic-location">${escapeHtml(item.location || demoChainLabel(chainKey))}</div><h4>${escapeHtml(item.category || "检查诊断")}</h4><p>${escapeHtml(item.observation || item.message || "检查发现需要关注的差异。")}</p>${item.guidance ? `<div class="diagnostic-guidance"><strong>建议</strong>${escapeHtml(item.guidance)}</div>` : ""}</article>`;
  }).join("")}</div>`;
}

function renderConsistencyResult(data, result) {
  const chains = ["nl_jml", "jml_java"].map((key) => ({
    key,
    value: result?.[key] || { verdict: "UNKNOWN", diagnostics: [] },
  }));
  const overall = String(result?.overall || "UNKNOWN").toUpperCase();
  const interpretation = result?.overall_evidence?.interpretation || "请分别查看两条检查链的结论。";
  const chainCards = chains.map(({ key, value }) => `
    <section class="consistency-chain ${demoChainClass(value.verdict)}">
      <div class="consistency-chain-heading"><div><span class="chain-kicker">${escapeHtml(demoChainLabel(key))}</span><h4>${escapeHtml(key === "nl_jml" ? "规格一致性" : "Java 静态验证")}</h4></div><span class="chain-verdict">${escapeHtml(statusLabel(value.verdict))}</span></div>
      <p class="chain-summary">${escapeHtml(value.verdict === "PASS" ? "这条链已完成，当前没有发现差异。" : value.verdict === "FAIL" ? "这条链发现了需要修正的内容。" : "这条链尚未完成，不能据此判断通过或失败。")}</p>
      ${renderDemoDiagnostics(value, key)}
    </section>`).join("");
  return `<div class="consistency-result"><div class="demo-summary ${demoChainClass(overall)}"><div><span class="chain-kicker">本案例结论</span><strong>${escapeHtml(statusLabel(overall))}</strong></div><p>${escapeHtml(interpretation)}</p></div><div class="consistency-chain-grid">${chainCards}</div><details class="technical-detail"><summary>查看技术详情</summary><pre>${escapeHtml(JSON.stringify(result, null, 2))}</pre></details></div>`;
}

async function readJsonResponse(response, fallbackMessage) {
  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    throw new Error(`${fallbackMessage}（返回内容无法解析）`);
  }
  if (!response.ok) throw new Error(data?.error || `${fallbackMessage}（HTTP ${response.status}）`);
  if (!data || typeof data !== "object") throw new Error(`${fallbackMessage}（返回结构无效）`);
  return data;
}

function renderCoach(coach) {
  if (!coach) return "";
  const issues = (coach.issues || []).map((item) => `<li><strong>${escapeHtml(item.category || item.location)}</strong>：${escapeHtml(item.explanation)}</li>`).join("");
  return `<section class="coach-card"><div class="coach-heading"><h3>学习解释</h3><span class="status-pill neutral">${escapeHtml(statusLabel(coach.verdict))}</span></div><p>${escapeHtml(coach.progress_summary || "")}</p>${issues ? `<ul>${issues}</ul>` : ""}<p class="next-step"><strong>下一步：</strong>${escapeHtml(coach.next_step || "")}</p></section>`;
}

function renderIssueList(issues) {
  if (!issues.length) return `<div class="all-clear"><strong>暂未发现需要修改的问题。</strong><span>这不等于实现或规格已经被完整证明，请查看三项检查状态。</span></div>`;
  return `<div class="issue-layout"><div class="issue-list">${issues.map((item, index) => `<button class="issue-item ${index === state.selectedIssue ? "selected" : ""}" data-issue-index="${index}" type="button"><span class="issue-number">${String(index + 1).padStart(2, "0")}</span><span><strong>${escapeHtml(item.category)}</strong><small>${escapeHtml(item.location)}</small></span></button>`).join("")}</div><div id="issue-detail" class="issue-detail"></div></div>`;
}

function renderSelectedIssue() {
  const target = $("issue-detail");
  const item = state.issues[state.selectedIssue];
  if (!target || !item) return;
  target.innerHTML = `<div class="detail-label">${escapeHtml(item.location)}</div><h3>${escapeHtml(item.category)}</h3><p>${escapeHtml(item.explanation)}</p>${renderCounterexample(item.counterexamples, item.counterexampleTitle)}${item.technical ? `<details class="technical-detail"><summary>查看技术细节</summary><pre>${escapeHtml(JSON.stringify(item.technical, null, 2))}</pre></details>` : ""}`;
}

function renderFeedback(data) {
  state.result = data;
  state.issues = collectIssues(data);
  state.selectedIssue = 0;
  const specStatus = data.semantic?.conclusion || resultStatus(data.semantic);
  const implementation = data.implementation;
  const implementationStatus = implementation ? implementation.static_status || implementation.status : "NOT_PROVIDED";
  const runtime = implementation?.runtime;
  const runtimeStatus = runtime ? (runtime.conclusion || runtime.replay_status || runtime.status) : "NOT_PROVIDED";
  const staticDetail = implementation
    ? `${implementation.preflight?.class_name || "Java"} · ${implementation.static_result?.diagnostics?.length || implementation.static?.diagnostics?.length || 0} 条诊断`
    : "未上传 Java";
  const snapshot = data.submission_snapshot || {};
  const draftChanged = state.draftRevision > state.lastSubmittedRevision;
  $("empty-feedback").classList.add("hidden");
  $("feedback-content").classList.remove("hidden");
  $("feedback-content").innerHTML = `
    <div class="result-summary">
      ${renderStatusCard("规格检查", specStatus, data.semantic?.passed ? "语义检查通过" : "根据诊断继续修改")}
      ${renderStatusCard("静态验证", implementation ? implementationStatus : "NOT_PROVIDED", staticDetail)}
      ${renderStatusCard("运行诊断", runtimeStatus, runtimeSummary(runtime))}
    </div>
    <div class="result-meta"><span>${snapshot.case_label ? `${snapshot.case_exact_match ? "配套案例" : "基于案例（材料已修改）"}：${escapeHtml(snapshot.case_label)} · ` : "自定义提交 · "}提交快照 ${escapeHtml(String(snapshot.submission_id || "").slice(0, 12) || "未生成")} · ${escapeHtml(data.source_mode === "java_embedded" ? "代码内规格" : "当前提交规格")}</span><span>${draftChanged ? "当前草稿已修改，结果仍对应本次快照" : "结果对应本次不可变快照"}</span></div>
    ${implementation?.runtime?.search ? `<div class="runtime-stats"><span>生成 ${implementation.runtime.search.generated_count ?? 0}</span><span>跳过 ${implementation.runtime.search.skipped_count ?? 0}</span><span>执行 ${implementation.runtime.search.executed_count ?? 0}</span><span>未观察违反 ${implementation.runtime.search.no_observed_violation_count ?? 0}</span><span>确认反例 ${implementation.runtime.search.confirmed_count ?? 0}</span><span>错误 ${implementation.runtime.search.error_count ?? 0}</span></div>` : ""}
    <section class="result-section"><div class="result-section-heading"><h3>需要关注的问题</h3><span>${state.issues.length} 项</span></div>${renderIssueList(state.issues)}</section>
    ${renderCoach(data.coach)}
  `;
  document.querySelectorAll("[data-issue-index]").forEach((button) => button.addEventListener("click", () => {
    state.selectedIssue = Number(button.dataset.issueIndex);
    document.querySelectorAll("[data-issue-index]").forEach((node) => node.classList.toggle("selected", node === button));
    renderSelectedIssue();
  }));
  renderSelectedIssue();
  $("results-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function submitReview() {
  if (state.busy) return;
  const submission = currentSubmission();
  if (!submission.trim()) {
    $("submit-message").textContent = "请先填写或导入 JML 规格。";
    return;
  }
  const requestId = ++state.reviewRequest;
  const submittedRevision = state.draftRevision;
  setChecking(true, "检查提交材料…");
  updateCheckingStage("spec", state.java ? "检查规格并准备实现检查…" : "检查规格…");
  try {
    const response = await fetch("/api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        exercise_id: state.exercise.id,
        case_id: state.loadedCaseId,
        submission,
        source_mode: state.java?.contractSource === "embedded" ? "java_embedded" : state.jmlMode,
        java_source: state.java?.source || "",
        java_filename: state.java?.filename || "",
        mode: "review",
        history: state.history.slice(-6),
      }),
    });
    updateCheckingStage(state.java ? "implementation" : "complete", state.java ? "整理实现证据…" : "整理规格结果…");
    const data = await readJsonResponse(response, "提交检查失败");
    if (requestId !== state.reviewRequest || data.exercise_id !== state.exercise.id || (data.submission_snapshot?.case_id || null) !== state.loadedCaseId) return;
    state.lastSubmittedRevision = submittedRevision;
    if (state.java?.preflight?.runtime_supported) updateCheckingStage("runtime", "整理运行诊断与反例…");
    updateCheckingStage("complete", "检查完成");
    state.history.unshift({ time: new Date().toLocaleString("zh-CN", { hour12: false }), java: Boolean(state.java), caseLabel: data.submission_snapshot?.case_label || "自定义提交", status: resultStatus(data.semantic) });
    state.history = state.history.slice(0, 6);
    renderHistory();
    renderFeedback(data);
    setDraftState("已提交", "submitted");
    setTimeout(() => setChecking(false), 250);
  } catch (error) {
    setChecking(false);
    $("submit-message").textContent = error.message || "检查请求失败，请确认服务仍在运行后重试。";
  }
}

function renderHistory() {
  if (!state.history.length) {
    $("history-list").innerHTML = '<p class="muted">还没有提交记录。</p>';
    return;
  }
  $("history-list").innerHTML = state.history.map((item, index) => `<div class="history-item"><span>#${state.history.length - index}</span><span>${escapeHtml(item.time)}</span><span>${escapeHtml(item.caseLabel || "自定义提交")} · ${item.java ? "规格 + Java" : "仅规格"}</span><strong>${escapeHtml(statusLabel(item.status))}</strong></div>`).join("");
}

function renderTeachingCases() {
  const legacyCases = state.exercise.consistency_demo_cases || [];
  const configuredGroups = state.exercise.consistency_demo_groups || [];
  const groups = configuredGroups.length
    ? configuredGroups
    : legacyCases.length
      ? [{
        id: "default",
        label: "默认案例组",
        method: state.exercise.method,
        nl_description: "从下方选择一个预设规格与 Java 组合运行。",
        cases: legacyCases,
      }]
      : [];
  // Backward-compatible selector contract: if(cases.length){$('consistency-demo').classList.remove('hidden')
  if (groups.length) $("consistency-demo").classList.remove("hidden");
  const groupSelect = $("consistency-group-select");
  const caseSelect = $("consistency-case-select");
  groupSelect.innerHTML = groups.map((group) => `<option value="${escapeHtml(group.id)}">${escapeHtml(group.label)}</option>`).join("");

  const updateCaseOptions = () => {
    const group = groups.find((entry) => entry.id === groupSelect.value) || groups[0];
    const cases = group?.cases || [];
    caseSelect.innerHTML = cases.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`).join("");
    $("consistency-group-description").innerHTML = group
      ? `<span>自然语言方法描述</span><strong>${escapeHtml(group.method || state.exercise.method || "")}</strong><p>${escapeHtml(group.nl_description || "")}</p>`
      : "";
    updateCaseDescription();
  };
  const updateCaseDescription = () => {
    const group = groups.find((entry) => entry.id === groupSelect.value) || groups[0];
    const item = (group?.cases || []).find((entry) => entry.id === caseSelect.value);
    $("consistency-case-description").textContent = item?.description || "";
    $("consistency-case-preview").innerHTML = item
      ? `<div><span>JML 组合</span><pre>${escapeHtml(item.jml_excerpt || "未提供 JML 摘要")}</pre></div><div><span>Java 组合</span><pre>${escapeHtml(item.java_excerpt || "未提供 Java 摘要")}</pre></div>`
      : "";
    state.demoRequests.consistency += 1;
    $("consistency-demo-result").textContent = "";
  };
  groupSelect.onchange = updateCaseOptions;
  caseSelect.onchange = updateCaseDescription;
  updateCaseOptions();
}

async function runConsistencyDemo() {
  const caseId = $("consistency-case-select").value;
  const groupId = $("consistency-group-select").value;
  const requestId = ++state.demoRequests.consistency;
  const button = $("run-consistency-demo");
  button.disabled = true;
  $("consistency-demo-result").textContent = `正在运行案例组中的组合：${caseId}…`;
  try {
    const response = await fetch("/api/demo-consistency", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ exercise_id: state.exercise.id, group_id: groupId, case_id: caseId }) });
    const data = await readJsonResponse(response, "一致性演示失败");
    if (requestId !== state.demoRequests.consistency || $("consistency-case-select").value !== caseId || $("consistency-group-select").value !== groupId) return;
    if (!data.result || typeof data.result !== "object") throw new Error("一致性演示没有返回结果");
    const result = data.result;
    const label = data.case?.label || caseId;
    const groupLabel = data.group?.label || groupId;
    const groupDescription = data.group?.nl_description || "";
    $("consistency-demo-result").innerHTML = `<div class="demo-result-status ${statusClass(result.overall)}">${escapeHtml(label)}</div><div class="demo-case-context"><span>案例组</span><strong>${escapeHtml(groupLabel)}</strong>${groupDescription ? `<p>${escapeHtml(groupDescription)}</p>` : ""}</div><p class="demo-warning">这是独立示意案例，不代表当前提交的规格已贯穿两条检查链。</p>${renderConsistencyResult(data, result)}`;
  } catch (error) {
    if (requestId === state.demoRequests.consistency) $("consistency-demo-result").innerHTML = `<div class="demo-error">${escapeHtml(error.message || "一致性演示失败")}</div>`;
  } finally {
    button.disabled = false;
  }
}

async function runRuntimeDemo() {
  const requestId = ++state.demoRequests.runtime;
  const button = $("run-runtime-demo");
  button.disabled = true;
  $("runtime-demo-result").textContent = "正在搜索预设反例…";
  try {
    const response = await fetch("/api/runtime-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ exercise_id: state.exercise.id, case_id: "unfollow-missing-inverse" }) });
    const data = await readJsonResponse(response, "运行时反例演示失败");
    if (requestId !== state.demoRequests.runtime) return;
    if (!data.result || typeof data.result !== "object") throw new Error("运行时演示没有返回结果");
    const result = data.result;
    const examples = confirmedCounterexamples(result);
    const errors = Array.isArray(result.errors) ? result.errors : [];
    const unlocated = Array.isArray(result.unconfirmed_observations) ? result.unconfirmed_observations : [];
    const status = result.conclusion || result.replay_status || result.status || "UNKNOWN";
    const message = examples.length
      ? "已确认预设缺陷的运行证据。"
      : status === "UNLOCATED_FAILURE" || unlocated.length
        ? "观察到运行失败，但尚未完成条款定位；暂不列为确认反例。"
        : status === "ERROR" || errors.length
        ? "运行过程发生错误，不能据此判断没有反例。"
        : status === "NO_VALID_CANDIDATES"
          ? "没有满足前置条件的候选输入，本次未执行目标方法。"
        : "当前有限范围内未找到已确认反例。";
    $("runtime-demo-result").innerHTML = `<div class="demo-result-status ${statusClass(status)}">${escapeHtml(statusLabel(status))}</div><p>${escapeHtml(message)}</p>${renderCounterexample(examples)}${errors.length ? `<details class="technical-detail"><summary>查看运行错误</summary><pre>${escapeHtml(JSON.stringify(errors, null, 2))}</pre></details>` : ""}${unlocated.length ? `<details class="technical-detail"><summary>查看未定位观察</summary><pre>${escapeHtml(JSON.stringify(unlocated, null, 2))}</pre></details>` : ""}`;
  } catch (error) {
    if (requestId === state.demoRequests.runtime) $("runtime-demo-result").innerHTML = `<div class="demo-error">${escapeHtml(error.message || "运行时反例演示失败")}</div>`;
  } finally {
    if (requestId === state.demoRequests.runtime) button.disabled = false;
  }
}

function bindEvents() {
  $("exercise-select").addEventListener("change", (event) => loadExercise(event.target.value));
  document.querySelectorAll("[data-jml-mode]").forEach((tab) => tab.addEventListener("click", () => setJmlMode(tab.dataset.jmlMode)));
  $("jml-paste").addEventListener("input", () => { state.jmlSource = $("jml-paste").value; updatePreview(); if (state.java) preflightJava(); });
  $("jml-file").addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (currentSubmission().trim() && !window.confirm("导入文件会替换当前规格草稿，继续吗？")) return;
    readFile(file, (content, filename) => {
      state.jmlSource = content;
      $("jml-file-status").textContent = `已导入：${filename}`;
      setJmlMode("file");
      updatePreview();
      if (state.java) preflightJava();
    });
  });
  $("java-file").addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    if (file) readFile(file, setJavaSource);
  });
  $("java-paste-toggle").addEventListener("click", () => {
    $("java-paste").classList.toggle("hidden");
    if (!$("java-paste").classList.contains("hidden")) $("java-paste").focus();
  });
  $("java-paste").addEventListener("input", () => {
    if (!state.java) state.java = { source: "", filename: "pasted.java", contractSource: "page" };
    state.java.source = $("java-paste").value;
    renderJavaMeta();
    preflightJava();
  });
  $("java-contract-source").addEventListener("change", (event) => {
    if (state.java) state.java.contractSource = event.target.value;
    updatePreview();
    updateSubmitButton();
  });
  $("remove-java").addEventListener("click", removeJava);
  $("download-java-template").addEventListener("click", downloadTemplate);
  $("submit-button").addEventListener("click", submitReview);
  $("back-to-submit").addEventListener("click", () => $("submit-panel").scrollIntoView({ behavior: "smooth" }));
  $("load-upload-case").addEventListener("click", loadUploadCase);
  document.querySelectorAll("[data-scroll]").forEach((button) => button.addEventListener("click", () => $(button.dataset.scroll)?.scrollIntoView({ behavior: "smooth", block: "start" })));
}

async function init() {
  try {
    const response = await fetch("/api/exercises");
    const catalog = await readJsonResponse(response, "题目列表加载失败");
    state.exercises = catalog.exercises || [];
    $("exercise-select").innerHTML = state.exercises.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.method)} · ${escapeHtml(item.title)}</option>`).join("");
    bindEvents();
    await loadExercise(catalog.default_id || state.exercises[0]?.id, { preserve: false });
    const environment = state.exercise.workbench?.environment_preflight || {};
    $("tool-status").textContent = state.exercise.workbench?.tool_status || "正在进行工具自检";
    $("tool-status").title = [
      `OpenJML：${environment.paths?.openjml || "未配置"}`,
      `版本：${environment.openjml?.version || "未知"}`,
      `Java：${environment.java?.version || "未知"}`,
      `ESC：${statusLabel(environment.esc?.status || "UNKNOWN")}`,
      `RAC：${statusLabel(environment.rac?.status || "UNKNOWN")}`,
    ].join("\n");
  } catch (error) {
    $("exercise-title").textContent = "练习加载失败";
    $("submit-message").textContent = "无法读取练习配置，请确认服务已启动。";
  }
}

init();
