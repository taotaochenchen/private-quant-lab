const modelInput = document.querySelector("#model");
const maxStepsInput = document.querySelector("#maxSteps");
const maxTokensInput = document.querySelector("#maxTokens");
const thinkingModeInput = document.querySelector("#thinkingMode");
const llmObservationInput = document.querySelector("#llmObservation");
const executionFeedbackInput = document.querySelector("#executionFeedback");
const executionItemsEl = document.querySelector("#executionItems");
const holdingsFile = document.querySelector("#holdingsFile");
const holdingsResultEl = document.querySelector("#holdingsResult");
const previousReportFile = document.querySelector("#previousReportFile");
const previousTradeDate = document.querySelector("#previousTradeDate");
const baselineLabel = document.querySelector("#baselineLabel");
const downloadReportButton = document.querySelector("#downloadReportButton");
const clearBaselineButton = document.querySelector("#clearBaselineButton");
let previousReport = null;
const agentPromptsEl = document.querySelector("#agentPrompts");
const resetPromptButton = document.querySelector("#resetPromptButton");
const runButton = document.querySelector("#runButton");
const statusEl = document.querySelector("#status");
const traceEl = document.querySelector("#trace");
const finalEl = document.querySelector("#final");
const traceCountEl = document.querySelector("#traceCount");
const workflowProgressEl = document.querySelector("#workflowProgress");
const currentNodeLabelEl = document.querySelector("#currentNodeLabel");
const toolsEl = document.querySelector("#tools");
const logsEl = document.querySelector("#logs");
const runIdEl = document.querySelector("#runId");
const refreshLogsButton = document.querySelector("#refreshLogsButton");
const clearLogsButton = document.querySelector("#clearLogsButton");
const researchShell = document.querySelector("#researchShell");
const devPanelButton = document.querySelector("#devPanelButton");
const stageEyebrowEl = document.querySelector("#stageEyebrow");
const stageTitleEl = document.querySelector("#stageTitle");
const automationStatusEl = document.querySelector("#automationStatus");
const automationSummaryEl = document.querySelector("#automationSummary");
const orderInstructionCountEl = document.querySelector("#orderInstructionCount");
const acceptedExecutionCountEl = document.querySelector("#acceptedExecutionCount");
const riskEventCountEl = document.querySelector("#riskEventCount");
const intradayAlertCountEl = document.querySelector("#intradayAlertCount");
const orderCountEl = document.querySelector("#orderCount");
const executionCountEl = document.querySelector("#executionCount");
const positionCountEl = document.querySelector("#positionCount");
const riskCountEl = document.querySelector("#riskCount");
const intradayCountEl = document.querySelector("#intradayCount");
const reviewStatusEl = document.querySelector("#reviewStatus");
const orderListEl = document.querySelector("#orderList");
const executionListEl = document.querySelector("#executionList");
const positionListEl = document.querySelector("#positionList");
const riskListEl = document.querySelector("#riskList");
const intradayListEl = document.querySelector("#intradayList");
const reviewDetailEl = document.querySelector("#reviewDetail");
const emergencyStopButton = document.querySelector("#emergencyStopButton");
const directionBadge = document.querySelector("#directionBadge");
const modeBadge = document.querySelector("#modeBadge");
const riskBadge = document.querySelector("#riskBadge");
const headlineEl = document.querySelector("#headline");
const reportDateEl = document.querySelector("#reportDate");
const decisionCopyEl = document.querySelector("#decisionCopy");
const sentimentValueEl = document.querySelector("#sentimentValue");
const capitalValueEl = document.querySelector("#capitalValue");
const volatilityValueEl = document.querySelector("#volatilityValue");
const sentimentMeterEl = document.querySelector("#sentimentMeter");
const capitalMeterEl = document.querySelector("#capitalMeter");
const volatilityMeterEl = document.querySelector("#volatilityMeter");
const industryListEl = document.querySelector("#industryList");
const industryCountEl = document.querySelector("#industryCount");
const stockBodyEl = document.querySelector("#stockBody");
const stockCountEl = document.querySelector("#stockCount");
const selectedStockEl = document.querySelector("#selectedStock");
const selectedScoreEl = document.querySelector("#selectedScore");
const selectedReasonEl = document.querySelector("#selectedReason");
const factorGridEl = document.querySelector("#factorGrid");
const tradePlanDetailEl = document.querySelector("#tradePlanDetail");
const evidenceListEl = document.querySelector("#evidenceList");
const evidenceCountEl = document.querySelector("#evidenceCount");

const autoTradingSampleTask = "生成今日盘前研究建议，结合上一交易日建议与人工执行反馈重新评估，不生成或执行模拟订单。";
let currentRunId = "";
let traceItems = [];
let defaultAutoTradingTask = autoTradingSampleTask;
let activeReport = null;
let activeAutoTradeRun = null;
let activeIndustryName = "";
let activeStockSymbol = "";
let agentPromptDefaults = [];
let agentPromptEditors = {};

async function loadTools() {
  const response = await fetch("/api/tools");
  const data = await response.json();
  defaultAutoTradingTask = data.default_pre_market_task || autoTradingSampleTask;
  agentPromptDefaults = data.pre_market_agent_prompts || [];
  renderAgentPromptEditors(agentPromptDefaults);
  renderWorkflowProgress();
  toolsEl.innerHTML = "";
  for (const tool of data.tool_schemas || []) {
    toolsEl.appendChild(renderToolSchema(tool));
  }
  autoLoadLatestSnapshot();
}

function setStatus(text, state) {
  statusEl.textContent = text;
  statusEl.className = `status ${state || ""}`.trim();
}

function setEmptyResults() {
  traceItems = [];
  traceEl.className = "trace empty";
  traceEl.textContent = "等待运行";
  finalEl.className = "final empty";
  finalEl.textContent = "暂无结果";
  traceCountEl.textContent = "0 steps";
  currentNodeLabelEl.textContent = "等待启动";
  logsEl.className = "logs empty";
  logsEl.textContent = "暂无日志";
  runIdEl.textContent = "No run";
  renderAutomation(null);
  renderWorkbench(null);
  renderWorkflowProgress();
}

function resetRunView() {
  traceItems = [];
  traceEl.className = "trace";
  traceEl.innerHTML = "";
  finalEl.className = "final empty";
  finalEl.textContent = "运行中...";
  traceCountEl.textContent = "0 steps";
  currentNodeLabelEl.textContent = "工作流启动中";
  renderWorkflowProgress();
  renderWorkbench(null);
  headlineEl.textContent = "今日建议分析中";
  decisionCopyEl.textContent = "正在核验市场证据与历史建议。";
}

function appendTrace(item) {
  traceItems.push(item);
  traceCountEl.textContent = `${traceItems.length} steps`;

  const node = document.createElement("section");
  node.className = `trace-item ${item.type || "event"}`;

  const title = document.createElement("div");
  title.className = "trace-title";
  const left = document.createElement("strong");
  left.textContent = traceTitle(item);
  const right = document.createElement("span");
  right.textContent = item.step ? `Step ${item.step}` : `#${traceItems.length}`;
  title.append(left, right);

  const body = renderTraceBody(item);

  node.append(title, body);
  traceEl.appendChild(node);
  traceEl.scrollTop = traceEl.scrollHeight;
}

function renderTraceBody(item) {
  if (item.type === "assistant") {
    const wrap = document.createElement("div");
    wrap.className = "structured-body";
    if (item.content) {
      wrap.appendChild(renderTextBlock(item.content));
    }
    if (item.reasoning_content) {
      wrap.appendChild(renderReasoningBlock(item.reasoning_content));
    }
    for (const call of item.tool_calls || []) {
      wrap.appendChild(renderToolCall(call));
    }
    if (!item.content && !(item.tool_calls || []).length) {
      wrap.appendChild(renderMutedBlock("空 assistant response"));
    }
    return wrap;
  }
  if (item.type === "tool_started") {
    const wrap = document.createElement("div");
    wrap.className = "structured-body";
    wrap.appendChild(renderKvList({
      tool: item.name,
      call_id: item.id || "",
    }));
    wrap.appendChild(renderJsonDetails("arguments", item.arguments || {}, true));
    return wrap;
  }
  if (item.type === "tool") {
    const wrap = document.createElement("div");
    wrap.className = "structured-body";
    wrap.appendChild(renderResultSummary(item.output || {}));
    wrap.appendChild(renderJsonDetails("tool result JSON", item.output || {}, true));
    return wrap;
  }
  return renderTextBlock(item.content || item.message || "");
}

function traceTitle(item) {
  const prefix = item.node_title || item.node || "";
  if (item.type === "assistant") return prefix ? `${prefix} · Assistant` : "Assistant";
  if (item.type === "tool") return prefix ? `${prefix} · Observation · ${item.name}` : `Observation · ${item.name}`;
  if (item.type === "tool_started") return prefix ? `${prefix} · Tool Call · ${item.name}` : `Tool Call · ${item.name}`;
  if (item.type === "workflow_node") return prefix || "Workflow Node";
  return "Event";
}

function renderExecutionItems(report) {
  executionItemsEl.replaceChildren();
  const plans = Array.isArray(report && report.trade_plan) ? report.trade_plan : [];
  if (!plans.length) {
    executionItemsEl.className = "execution-items muted";
    executionItemsEl.textContent = "载入 T-1 基线后可逐笔记录执行情况";
    return;
  }
  executionItemsEl.className = "execution-items";
  const heading = document.createElement("div");
  heading.className = "muted";
  heading.textContent = "逐笔执行反馈（默认未反馈）";
  executionItemsEl.appendChild(heading);
  const labels = {unknown: "未反馈", executed: "已执行", partial: "部分执行", skipped: "未执行"};
  for (const plan of plans) {
    const row = document.createElement("div");
    row.className = "execution-item";
    const label = document.createElement("span");
    label.textContent = `${plan.symbol || "?"} ${plan.name || ""} · ${plan.side || "?"} ${plan.first_position || plan.max_position || ""}`;
    const select = document.createElement("select");
    select.dataset.symbol = plan.symbol || "";
    for (const [value, text] of Object.entries(labels)) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      select.appendChild(option);
    }
    row.appendChild(label);
    row.appendChild(select);
    executionItemsEl.appendChild(row);
  }
}

function collectExecutionItems() {
  const items = [];
  executionItemsEl.querySelectorAll("select").forEach((select) => {
    const symbol = select.dataset.symbol;
    const status = select.value;
    if (symbol && status !== "unknown") {
      items.push({symbol, execution_status: status});
    }
  });
  return items.length ? items : null;
}

async function runAgent() {
  setStatus("Running", "running");
  runButton.disabled = true;
  previousReportFile.disabled = true;
  clearBaselineButton.disabled = true;
  resetRunView();

  try {
    const payload = {
      model: modelInput.value,
      max_steps: Number(maxStepsInput.value || 8),
      max_tokens: Number(maxTokensInput.value || 3000),
      thinking_mode: thinkingModeInput.checked,
      llm_observation: llmObservationInput.checked,
      task_context: defaultAutoTradingTask,
      agent_system_prompts: collectAgentPrompts(),
      previous_report: previousReport,
      previous_trade_date: previousTradeDate.value || null,
      execution_feedback: executionFeedbackInput.value,
      execution_items: collectExecutionItems(),
    };

    const endpoint = "/api/pre_market_stream";
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    if (!response.ok || !response.body) {
      throw new Error(`HTTP ${response.status}`);
    }
    await readEventStream(response.body);
  } catch (error) {
    finalEl.className = "final";
    finalEl.textContent = `运行失败：${error.message}`;
    setStatus("Error", "error");
  } finally {
    runButton.disabled = false;
    previousReportFile.disabled = false;
    clearBaselineButton.disabled = false;
    if (currentRunId) {
      await loadLogs(currentRunId);
    }
  }
}

function collectAgentPrompts() {
  const prompts = {};
  for (const [name, textarea] of Object.entries(agentPromptEditors)) {
    prompts[name] = textarea.value;
  }
  return prompts;
}

async function readEventStream(stream) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const {value, done} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {stream: true});
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      handleSseChunk(chunk);
    }
  }
  if (buffer.trim()) {
    handleSseChunk(buffer);
  }
}

function handleSseChunk(chunk) {
  const lines = chunk.split("\n");
  let eventName = "message";
  let dataText = "";
  for (const line of lines) {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataText += line.slice(5).trim();
    }
  }
  if (!dataText) return;
  const data = JSON.parse(dataText);
  handleRunEvent(eventName, data);
}

function handleRunEvent(eventName, data) {
  if (data.run_id) {
    currentRunId = data.run_id;
    runIdEl.textContent = `Run ${currentRunId.slice(0, 8)}`;
  }
  if (eventName === "assistant") {
    currentNodeLabelEl.textContent = `${data.node_title || data.node || "Agent"} · model response`;
    appendTrace({
      type: "assistant",
      step: data.step,
      content: data.content || "",
      reasoning_content: data.reasoning_content || "",
      tool_calls: data.tool_calls || [],
      node: data.node || "",
      node_title: data.node_title || "",
    });
  } else if (eventName === "tool_started") {
    currentNodeLabelEl.textContent = `${data.node_title || data.node || "Agent"} · calling ${data.name || "tool"}`;
    appendTrace({
      type: "tool_started",
      step: data.step,
      name: data.name,
      arguments: data.arguments,
      node: data.node || "",
      node_title: data.node_title || "",
    });
  } else if (eventName === "tool_finished") {
    currentNodeLabelEl.textContent = `${data.node_title || data.node || "Agent"} · ${data.name || "tool"} done`;
    appendTrace({
      type: "tool",
      step: data.step,
      name: data.name,
      output: data.output,
      node: data.node || "",
      node_title: data.node_title || "",
    });
  } else if (eventName === "workflow_node_started") {
    currentNodeLabelEl.textContent = `${data.title || data.node || "Agent"} · started`;
    updateWorkflowProgress(data.node, "running");
    appendTrace({
      type: "workflow_node",
      content: `${data.title || data.node || "Agent"} 启动`,
      node: data.node || "",
      node_title: data.title || "",
    });
  } else if (eventName === "workflow_node_finished") {
    currentNodeLabelEl.textContent = `${data.title || data.node || "Agent"} · finished`;
    updateWorkflowProgress(data.node, "done");
    appendTrace({
      type: "workflow_node",
      content: `${data.title || data.node || "Agent"} 完成`,
      node: data.node || "",
      node_title: data.title || "",
    });
  } else if (eventName === "final") {
    finalEl.className = "final";
    renderFinal(data.final || "");
  } else if (eventName === "pre_market_report") {
    if (data.report) {
      renderWorkbench(data.report);
    }
  } else if (eventName === "auto_trade_status") {
    renderAutomation({status: data.status || "running", summary: data.message || ""});
  } else if (eventName === "paper_order_started") {
    appendAutomationItem(orderListEl, renderOrderCard(data.order || {}, "指令已生成"));
  } else if (eventName === "paper_order_finished") {
    appendAutomationItem(executionListEl, renderExecutionCard(data.execution || {}));
  } else if (eventName === "risk_event") {
    appendAutomationItem(riskListEl, renderRiskCard(data.event || {}));
  } else if (eventName === "intraday_alert") {
    appendAutomationItem(intradayListEl, renderIntradayCard(data.alert || {}));
  } else if (eventName === "review_report") {
    renderReview(data.review || {});
  } else if (eventName === "auto_trade_result") {
    if (data.run) {
      renderAutomation(data.run);
    }
  } else if (eventName === "run_finished") {
    finalEl.className = "final";
    if (data.auto_trade) {
      renderAutomation(data.auto_trade);
    }
    if (data.report) {
      renderWorkbench(data.report);
    }
    if (data.final) renderFinal(data.final);
    setStatus("Done", "");
  } else if (eventName === "run_error") {
    finalEl.className = "final";
    finalEl.textContent = `运行失败：${data.error || "unknown error"}`;
    setStatus("Error", "error");
  }
}

function renderAgentPromptEditors(items) {
  agentPromptsEl.innerHTML = "";
  agentPromptEditors = {};
  for (const item of items) {
    const details = document.createElement("details");
    details.className = "agent-prompt-card";
    details.open = item.name === "market_sentiment_agent";
    const summary = document.createElement("summary");
    const title = document.createElement("strong");
    title.textContent = item.title || item.name;
    const name = document.createElement("span");
    name.textContent = item.name;
    summary.append(title, name);
    const textarea = document.createElement("textarea");
    textarea.rows = 11;
    textarea.value = item.system_prompt || "";
    textarea.dataset.agent = item.name;
    details.append(summary, textarea);
    agentPromptsEl.appendChild(details);
    agentPromptEditors[item.name] = textarea;
  }
}

function renderWorkflowProgress(activeNode, status) {
  workflowProgressEl.innerHTML = "";
  for (const item of agentPromptDefaults) {
    const node = document.createElement("div");
    let state = "";
    if (item.name === activeNode) state = status || "running";
    node.className = `workflow-node ${state}`;
    node.dataset.node = item.name;
    node.innerHTML = `<strong>${escapeHtml(item.title || item.name)}</strong><span>${escapeHtml(item.name)}</span>`;
    workflowProgressEl.appendChild(node);
  }
}

function updateWorkflowProgress(nodeName, status) {
  for (const node of workflowProgressEl.querySelectorAll(".workflow-node")) {
    if (node.dataset.node === nodeName) {
      node.classList.remove("running", "done");
      node.classList.add(status);
    }
  }
}

function renderToolSchema(tool) {
  const fn = tool.function || {};
  const schema = fn.parameters || {};
  const details = document.createElement("details");
  details.className = "tool-card";

  const summary = document.createElement("summary");
  const name = document.createElement("strong");
  name.textContent = fn.name || "tool";
  const count = document.createElement("span");
  count.textContent = `${Object.keys((schema.properties || {})).length} fields`;
  summary.append(name, count);

  const description = document.createElement("p");
  description.className = "tool-description";
  description.textContent = fn.description || "";

  details.append(summary, description, renderSchemaTable(schema));
  return details;
}

function renderSchemaTable(schema) {
  const table = document.createElement("div");
  table.className = "schema-table";
  const required = new Set(schema.required || []);
  const properties = schema.properties || {};
  for (const [name, spec] of Object.entries(properties)) {
    const row = document.createElement("div");
    row.className = "schema-row";
    const field = document.createElement("strong");
    field.textContent = name;
    const type = document.createElement("span");
    type.textContent = `${spec.type || "any"}${required.has(name) ? " · required" : ""}`;
    row.append(field, type);
    table.appendChild(row);
  }
  if (!Object.keys(properties).length) {
    table.appendChild(renderMutedBlock("无参数"));
  }
  return table;
}

function renderToolCall(call) {
  const card = document.createElement("div");
  card.className = "tool-call-card";
  const head = document.createElement("div");
  head.className = "mini-head";
  const title = document.createElement("strong");
  title.textContent = call.name || "tool_call";
  const id = document.createElement("span");
  id.textContent = call.id || "no id";
  head.append(title, id);
  card.append(head, renderJsonDetails("arguments", call.arguments || {}, true));
  return card;
}

function renderResultSummary(output) {
  const summary = document.createElement("div");
  summary.className = "result-summary";
  for (const [key, value] of Object.entries(output).slice(0, 8)) {
    const item = document.createElement("div");
    item.className = "result-field";
    const label = document.createElement("span");
    label.textContent = key;
    const val = document.createElement("strong");
    val.textContent = compactValue(value);
    item.append(label, val);
    summary.appendChild(item);
  }
  return summary;
}

function renderKvList(values) {
  const summary = document.createElement("div");
  summary.className = "result-summary";
  for (const [key, value] of Object.entries(values)) {
    const item = document.createElement("div");
    item.className = "result-field";
    const label = document.createElement("span");
    label.textContent = key;
    const val = document.createElement("strong");
    val.textContent = compactValue(value);
    item.append(label, val);
    summary.appendChild(item);
  }
  return summary;
}

function renderJsonDetails(label, value, open) {
  const details = document.createElement("details");
  details.className = "json-details";
  details.open = Boolean(open);
  const summary = document.createElement("summary");
  summary.textContent = label;
  const body = document.createElement("pre");
  body.textContent = JSON.stringify(value, null, 2);
  details.append(summary, body);
  return details;
}

function renderTextBlock(text) {
  const block = document.createElement("div");
  block.className = "text-block";
  block.textContent = text;
  return block;
}

function renderReasoningBlock(text) {
  const details = document.createElement("details");
  details.className = "reasoning-block";
  details.open = true;
  const summary = document.createElement("summary");
  summary.textContent = "思考过程";
  const body = document.createElement("div");
  body.className = "reasoning-content";
  body.textContent = text;
  details.append(summary, body);
  return details;
}

function renderMutedBlock(text) {
  const block = document.createElement("div");
  block.className = "muted-block";
  block.textContent = text;
  return block;
}

function renderFinal(text) {
  const value = parseJsonObject(text);
  if (!value) {
    finalEl.textContent = text;
    return;
  }
  if (value.pre_market_report) {
    renderAutomation(value);
    renderWorkbench(value.pre_market_report);
    finalEl.innerHTML = "";
    finalEl.appendChild(renderAutoTradingReport(value));
    return;
  }
  renderWorkbench(value);
  finalEl.innerHTML = "";
  finalEl.appendChild(renderPreMarketReport(value));
}

function renderAutomation(run) {
  activeAutoTradeRun = run;
  const normalized = run || {};
  const orders = normalized.order_instructions || [];
  const executions = normalized.executions || [];
  const risks = normalized.risk_events || [];
  const positions = normalized.positions || [];
  const intraday = normalized.intraday_alerts || [];
  automationStatusEl.textContent = normalized.status || "Idle";
  automationSummaryEl.textContent = normalized.summary || "等待启动自动模拟盘流程。";
  orderInstructionCountEl.textContent = String(orders.length);
  acceptedExecutionCountEl.textContent = String(executions.filter((item) => item.status === "accepted").length);
  riskEventCountEl.textContent = String(risks.length);
  intradayAlertCountEl.textContent = String(intraday.length);
  renderOrderList(orders);
  renderExecutionList(executions);
  renderPositionList(positions);
  renderRiskList(risks);
  renderIntradayList(intraday);
  renderReview(normalized.review_report || null);
}

function renderWorkbench(report) {
  activeReport = report;
  downloadReportButton.disabled = !report;
  renderStrategyRevision(report?.strategy_revision);
  if (!report) {
    headlineEl.textContent = "等待盘前分析";
    reportDateEl.textContent = "--";
    decisionCopyEl.textContent = "等待今日研究结果。未提供执行反馈，持仓状态未知。";
    directionBadge.textContent = "方向：等待分析";
    modeBadge.textContent = "模式：observe";
    riskBadge.textContent = "风控：pending";
    setMetric(sentimentValueEl, sentimentMeterEl, null);
    setMetric(capitalValueEl, capitalMeterEl, null);
    setMetric(volatilityValueEl, volatilityMeterEl, null);
    renderIndustries([]);
    renderStocks([]);
    renderStockDetail(null);
    renderEvidence([]);
    return;
  }

  const market = report.market_state || {};
  const risk = report.risk_review || {};
  headlineEl.textContent = report.headline || "盘前报告";
  reportDateEl.textContent = report.report_date || "";
  decisionCopyEl.textContent = report.summary || market.summary || "";
  directionBadge.textContent = `方向：${market.direction || "unknown"}`;
  modeBadge.textContent = `模式：${market.trading_mode || "observe"}`;
  riskBadge.textContent = `风控：${risk.status || "pending"}`;
  setMetric(sentimentValueEl, sentimentMeterEl, market.sentiment_score);
  setMetric(capitalValueEl, capitalMeterEl, market.capital_intensity ?? market.capital_score);
  setMetric(volatilityValueEl, volatilityMeterEl, market.volatility_risk ?? market.volatility_risk_score);

  const industries = report.industries || [];
  if (!industries.some((item) => item.industry === activeIndustryName)) {
    activeIndustryName = industries[0]?.industry || "";
  }
  renderIndustries(industries);
  renderStocks(filteredStocksForActiveIndustry());
  renderEvidence(report.evidence_chain || []);
}

function renderStrategyRevision(revision) {
  const status = document.querySelector("#revisionStatus");
  const summary = document.querySelector("#revisionSummary");
  const list = document.querySelector("#revisionChanges");
  list.replaceChildren();
  if (!revision) {
    status.textContent = "等待分析";
    summary.textContent = "暂无对比";
    return;
  }
  status.textContent = revision.baseline_status === "provided"
    ? `${revision.previous_trade_date} → ${revision.trade_date}` : "首次分析 · 无 T-1 基线";
  summary.textContent = [revision.current_rationale,
    revision.execution_status === "unknown" ? "执行状态未知" : "执行反馈待核验",
    "撤回建议不代表卖出。"].filter(Boolean).join(" · ");
  const labels = {initial: "初始建议", added: "新增", retained: "保留", adjusted: "调整", withdrawn: "撤回建议", suspended: "暂停建议"};
  for (const change of revision.changes || []) {
    const row = document.createElement("article");
    row.className = "revision-row";
    const heading = document.createElement("strong");
    heading.textContent = `${change.symbol} · ${labels[change.status] || change.status}`;
    const body = document.createElement("p");
    const show = (plan) => plan ? `${plan.side} · 建议上限 ${plan.max_position}` : "无建议";
    body.textContent = `${show(change.before)} → ${show(change.after)}`;
    row.append(heading, body, renderJsonDetails("前后条件与原值", {
      changed_fields: change.changed_fields, before: change.before, after: change.after,
    }, false));
    list.appendChild(row);
  }
  if (!list.children.length) list.textContent = "暂无可对比建议";
}

function renderOrderList(items) {
  orderCountEl.textContent = `${items.length} orders`;
  renderCardList(orderListEl, items, renderOrderCard, "暂无订单");
}

function renderExecutionList(items) {
  executionCountEl.textContent = `${items.length} executions`;
  renderCardList(executionListEl, items, renderExecutionCard, "暂无执行");
}

function renderPositionList(items) {
  positionCountEl.textContent = `${items.length} positions`;
  renderCardList(positionListEl, items, renderPositionCard, "暂无持仓");
}

function renderRiskList(items) {
  riskCountEl.textContent = `${items.length} events`;
  renderCardList(riskListEl, items, renderRiskCard, "暂无风控事件");
}

function renderIntradayList(items) {
  intradayCountEl.textContent = `${items.length} alerts`;
  renderCardList(intradayListEl, items, renderIntradayCard, "暂无盘中事件");
}

function renderReview(review) {
  if (!review) {
    reviewStatusEl.textContent = "pending";
    reviewDetailEl.className = "order-list empty";
    reviewDetailEl.textContent = "暂无复盘";
    return;
  }
  reviewStatusEl.textContent = review.status || "unknown";
  reviewDetailEl.className = "order-list";
  reviewDetailEl.innerHTML = "";
  const card = document.createElement("div");
  card.className = "order-card";
  card.innerHTML = `
    <div class="order-head"><strong>${escapeHtml(review.risk_effectiveness || "review")}</strong><span>${escapeHtml(review.generated_at || "")}</span></div>
    <div class="order-meta">
      <span>行业Alpha ${escapeHtml(review.industry_alpha ?? 0)}</span>
      <span>个股Alpha ${escapeHtml(review.stock_alpha ?? 0)}</span>
      <span>成交率 ${escapeHtml(review.order_fill_rate ?? 0)}</span>
    </div>
  `;
  reviewDetailEl.appendChild(card);
  for (const note of review.notes || []) {
    const row = document.createElement("div");
    row.className = "report-row";
    row.textContent = note;
    reviewDetailEl.appendChild(row);
  }
}

function renderCardList(container, items, renderer, emptyText) {
  if (!items.length) {
    container.className = "order-list empty";
    container.textContent = emptyText;
    return;
  }
  container.className = "order-list";
  container.innerHTML = "";
  for (const item of items) {
    container.appendChild(renderer(item));
  }
}

function appendAutomationItem(container, node) {
  if (container.classList.contains("empty")) {
    container.className = "order-list";
    container.innerHTML = "";
  }
  container.appendChild(node);
}

function renderOrderCard(item, label) {
  const card = document.createElement("div");
  card.className = "order-card";
  card.innerHTML = `
    <div class="order-head"><strong>${escapeHtml(item.symbol || "UNKNOWN")} ${escapeHtml(item.side || "")}</strong><span>${escapeHtml(label || item.order_type || "market")}</span></div>
    <div class="order-meta">
      <span>数量 ${escapeHtml(item.quantity ?? "--")}</span>
      <span>有效期 ${escapeHtml(item.time_in_force || "day")}</span>
      <span>${escapeHtml(item.source_plan_ref || "")}</span>
    </div>
  `;
  return card;
}

function renderExecutionCard(item) {
  const card = document.createElement("div");
  card.className = `order-card ${item.status === "accepted" ? "accepted" : "rejected"}`;
  card.innerHTML = `
    <div class="order-head"><strong>${escapeHtml(item.symbol || "UNKNOWN")}</strong><span>${escapeHtml(item.status || "unknown")}</span></div>
    <div class="order-meta">
      <span>${escapeHtml(item.side || "")} ${escapeHtml(item.quantity ?? "--")}</span>
      <span>成交 ${escapeHtml(item.filled_quantity ?? 0)}</span>
      <span>${escapeHtml(item.submitted_at || "")}</span>
    </div>
  `;
  return card;
}

function renderPositionCard(item) {
  const card = document.createElement("div");
  card.className = "order-card";
  card.innerHTML = `
    <div class="order-head"><strong>${escapeHtml(item.symbol || "UNKNOWN")}</strong><span>${escapeHtml(item.weight || "0%")}</span></div>
    <div class="order-meta">
      <span>${escapeHtml(item.name || "")}</span>
      <span>数量 ${escapeHtml(item.quantity ?? 0)}</span>
      <span>浮盈亏 ${escapeHtml(item.unrealized_pnl_pct ?? 0)}%</span>
    </div>
  `;
  return card;
}

function renderRiskCard(item) {
  const card = document.createElement("div");
  card.className = `order-card risk-${item.level || "info"}`;
  card.innerHTML = `
    <div class="order-head"><strong>${escapeHtml(item.type || "risk")}</strong><span>${escapeHtml(item.status || "")}</span></div>
    <p>${escapeHtml(item.message || "")}</p>
    <div class="order-meta"><span>${escapeHtml(item.action || "")}</span><span>${escapeHtml(item.timestamp || "")}</span></div>
  `;
  return card;
}

function renderIntradayCard(item) {
  const card = document.createElement("div");
  card.className = `order-card ${item.status === "triggered" ? "accepted" : ""}`;
  card.innerHTML = `
    <div class="order-head"><strong>${escapeHtml(item.symbol || item.condition_ref || "monitor")}</strong><span>${escapeHtml(item.status || "")}</span></div>
    <p>${escapeHtml(item.message || "")}</p>
    <div class="order-meta"><span>${escapeHtml(item.action || "")}</span><span>value ${escapeHtml(item.actual_value ?? 0)}</span></div>
  `;
  return card;
}

function setMetric(valueEl, meterEl, value) {
  if (value === undefined || value === null || value === "") {
    valueEl.textContent = "--";
    meterEl.style.setProperty("--value", "0%");
    return;
  }
  const number = Math.max(0, Math.min(100, Number(value)));
  valueEl.textContent = String(number);
  meterEl.style.setProperty("--value", `${number}%`);
}

function renderIndustries(industries) {
  industryCountEl.textContent = `${industries.length} industries`;
  if (!industries.length) {
    industryListEl.className = "industry-list empty";
    industryListEl.textContent = "暂无行业";
    return;
  }
  industryListEl.className = "industry-list";
  industryListEl.innerHTML = "";
  for (const industry of industries) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `industry-button ${industry.industry === activeIndustryName ? "active" : ""}`;
    button.dataset.industry = industry.industry || "";
    const name = document.createElement("strong");
    name.textContent = industry.industry || "行业";
    const thesis = document.createElement("span");
    thesis.className = "muted";
    thesis.textContent = industry.thesis || "";
    const score = document.createElement("span");
    score.className = "industry-score";
    score.textContent = industry.score ?? "--";
    button.append(name, thesis, score);
    button.addEventListener("click", () => {
      activeIndustryName = industry.industry || "";
      activeStockSymbol = "";
      renderIndustries(activeReport?.industries || []);
      renderStocks(filteredStocksForActiveIndustry());
    });
    industryListEl.appendChild(button);
  }
}

function filteredStocksForActiveIndustry() {
  const stocks = activeReport?.stocks || [];
  if (!activeIndustryName) return stocks;
  const scoped = stocks.filter((stock) => stock.industry === activeIndustryName);
  return scoped.length ? scoped : stocks;
}

function renderStocks(stocks) {
  stockCountEl.textContent = `${stocks.length} stocks`;
  if (!stocks.length) {
    stockBodyEl.innerHTML = '<tr><td colspan="8" class="empty">暂无个股</td></tr>';
    renderStockDetail(null);
    return;
  }
  if (!stocks.some((stock) => stock.symbol === activeStockSymbol)) {
    activeStockSymbol = stocks[0]?.symbol || "";
  }
  stockBodyEl.innerHTML = "";
  for (const stock of stocks) {
    const row = document.createElement("tr");
    row.className = `stock-row ${stock.symbol === activeStockSymbol ? "active" : ""}`;
    row.dataset.symbol = stock.symbol || "";
    row.innerHTML = `
      <td><strong>${escapeHtml(stock.symbol || "")}</strong><br><span class="muted">${escapeHtml(stock.name || "")}</span></td>
      <td>${escapeHtml(stock.reason || "")}</td>
      <td class="num"><span class="score-badge">${escapeHtml(stock.total_score ?? "--")}</span></td>
      <td class="num">${escapeHtml(stock.quality ?? "--")}</td>
      <td class="num">${escapeHtml(stock.momentum ?? "--")}</td>
      <td class="num">${escapeHtml(stock.valuation ?? "--")}</td>
      <td class="num">${escapeHtml(stock.crowding ?? "--")}</td>
      <td class="num"><strong>${escapeHtml(stock.suggested_position || findTradePlan(stock.symbol)?.max_position || "--")}</strong></td>
    `;
    row.addEventListener("click", () => {
      activeStockSymbol = stock.symbol || "";
      renderStocks(filteredStocksForActiveIndustry());
    });
    stockBodyEl.appendChild(row);
  }
  renderStockDetail(stocks.find((stock) => stock.symbol === activeStockSymbol) || stocks[0]);
}

function renderStockDetail(stock) {
  if (!stock) {
    selectedStockEl.textContent = "个股详情";
    selectedScoreEl.textContent = "--";
    selectedReasonEl.textContent = "选择一只股票查看因子画像和交易约束。";
    factorGridEl.innerHTML = "";
    tradePlanDetailEl.innerHTML = "";
    return;
  }
  selectedStockEl.textContent = `${stock.symbol || ""} ${stock.name || ""}`.trim();
  selectedScoreEl.textContent = stock.total_score ?? "--";
  selectedReasonEl.textContent = stock.reason || "";
  factorGridEl.innerHTML = "";
  for (const [label, value] of [
    ["质量", stock.quality],
    ["动量", stock.momentum],
    ["估值", stock.valuation],
    ["流动性", stock.liquidity],
    ["拥挤", stock.crowding],
    ["风险", stock.risk_score],
  ]) {
    const item = document.createElement("div");
    item.className = "factor";
    item.innerHTML = `
      <div class="factor-top"><span>${label}</span><strong>${escapeHtml(value ?? "--")}</strong></div>
      <div class="meter"><span style="--value:${Number(value || 0)}%"></span></div>
    `;
    factorGridEl.appendChild(item);
  }

  const plan = findTradePlan(stock.symbol);
  tradePlanDetailEl.innerHTML = "";
  if (!plan) {
    tradePlanDetailEl.appendChild(renderMutedBlock("暂无交易计划"));
    return;
  }
  for (const [label, values] of [
    ["动作", [plan.side, `首笔 ${plan.first_position || "--"}`, `上限 ${plan.max_position || plan.planned_position || "--"}`].filter(Boolean)],
    ["买入条件", plan.buy_conditions || plan.entry_conditions || []],
    ["加仓条件", plan.add_conditions || []],
    ["减仓条件", plan.reduce_conditions || []],
    ["止损条件", plan.stop_loss_conditions || []],
    ["不交易条件", plan.no_trade_conditions || []],
  ]) {
    const row = document.createElement("div");
    row.className = "trade-row";
    const title = document.createElement("strong");
    title.textContent = label;
    const body = document.createElement("span");
    body.textContent = values.length ? formatConditions(values) : "暂无";
    row.append(title, body);
    tradePlanDetailEl.appendChild(row);
  }
}

function renderEvidence(items) {
  evidenceCountEl.textContent = `${items.length} items`;
  if (!items.length) {
    evidenceListEl.className = "evidence-list empty";
    evidenceListEl.textContent = "暂无证据";
    return;
  }
  evidenceListEl.className = "evidence-list";
  evidenceListEl.innerHTML = "";
  for (const item of items) {
    const node = document.createElement("div");
    node.className = "evidence-item";
    const source = document.createElement("strong");
    source.textContent = item.source || "source";
    const body = document.createElement("div");
    const summary = document.createElement("p");
    summary.textContent = item.summary || item.influence || "";
    const impact = document.createElement("span");
    impact.className = "muted";
    impact.textContent = item.impact || item.source_timestamp || "";
    body.append(summary, impact);
    node.append(source, body);
    evidenceListEl.appendChild(node);
  }
}

function findTradePlan(symbol) {
  return (activeReport?.trade_plan || []).find((item) => item.symbol === symbol);
}

function formatConditions(values) {
  return values.map((value) => {
    if (typeof value === "string") return value;
    if (value && typeof value === "object") {
      if (value.expression && value.text) return `${value.text} (${value.expression})`;
      return value.text || value.expression || JSON.stringify(value);
    }
    return String(value ?? "");
  }).filter(Boolean).join(" / ");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function parseJsonObject(text) {
  const raw = String(text || "").trim();
  const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/);
  const candidate = fenced ? fenced[1].trim() : raw;
  try {
    const value = JSON.parse(candidate);
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  } catch (_error) {
    return null;
  }
}

function renderPreMarketReport(report) {
  const wrap = document.createElement("div");
  wrap.className = "pre-market-report";

  const hero = document.createElement("section");
  hero.className = "report-hero";
  const title = document.createElement("h3");
  title.textContent = report.headline || "盘前报告";
  const meta = document.createElement("p");
  const market = report.market_state || {};
  meta.textContent = `${report.report_date || ""} · ${market.direction || "unknown"} · ${market.trading_mode || "observe"}`;
  hero.append(title, meta);
  wrap.appendChild(hero);

  wrap.appendChild(renderScoreGrid({
    sentiment: market.sentiment_score,
    capital: market.capital_intensity ?? market.capital_score,
    volatility: market.volatility_risk ?? market.volatility_risk_score,
  }));

  if (market.summary) {
    wrap.appendChild(renderSectionText("市场状态", market.summary));
  }
  wrap.appendChild(renderListSection("候选行业", report.industries || [], (item) => {
    return `${item.industry || ""} · ${item.score ?? "-"}分 · ${item.thesis || ""}`;
  }));
  wrap.appendChild(renderListSection("候选个股", report.stocks || [], (item) => {
    const position = item.suggested_position || findTradePlan(item.symbol)?.max_position || "-";
    return `${item.symbol || ""} ${item.name || ""} · ${item.total_score ?? "-"}分 · 仓位 ${position}`;
  }));
  if (report.risk_review) {
    wrap.appendChild(renderSectionText("风控审核", `${report.risk_review.status || "pending"} · ${report.risk_review.reason || ""}`));
  }
  wrap.appendChild(renderListSection("交易计划", report.trade_plan || [], (item) => {
    return `${item.symbol || ""} ${item.side || ""} · ${item.max_position || item.planned_position || ""} · ${formatConditions(item.buy_conditions || item.entry_conditions || [])}`;
  }));
  wrap.appendChild(renderJsonDetails("完整 JSON", report, false));
  return wrap;
}

function renderAutoTradingReport(run) {
  const wrap = document.createElement("div");
  wrap.className = "pre-market-report";
  const hero = document.createElement("section");
  hero.className = "report-hero";
  const title = document.createElement("h3");
  title.textContent = "自动模拟盘结果";
  const meta = document.createElement("p");
  meta.textContent = `${run.run_mode || "paper"} · ${run.status || "unknown"}`;
  hero.append(title, meta);
  wrap.appendChild(hero);
  if (run.summary) wrap.appendChild(renderSectionText("执行摘要", run.summary));
  wrap.appendChild(renderListSection("订单指令", run.order_instructions || [], (item) => {
    return `${item.symbol || ""} ${item.side || ""} · ${item.quantity ?? "-"} · ${item.order_type || ""}`;
  }));
  wrap.appendChild(renderListSection("执行结果", run.executions || [], (item) => {
    return `${item.symbol || ""} · ${item.status || ""} · filled ${item.filled_quantity ?? 0}`;
  }));
  wrap.appendChild(renderListSection("风控事件", run.risk_events || [], (item) => {
    return `${item.level || ""} · ${item.message || ""}`;
  }));
  wrap.appendChild(renderListSection("盘中监控", run.intraday_alerts || [], (item) => {
    return `${item.symbol || ""} · ${item.status || ""} · ${item.message || ""}`;
  }));
  if (run.review_report) {
    wrap.appendChild(renderSectionText("收盘复盘", `${run.review_report.status || ""} · ${run.review_report.risk_effectiveness || ""}`));
  }
  wrap.appendChild(renderJsonDetails("完整 JSON", run, false));
  return wrap;
}

function renderScoreGrid(scores) {
  const grid = document.createElement("div");
  grid.className = "score-grid";
  for (const [label, value] of Object.entries(scores)) {
    const item = document.createElement("div");
    item.className = "score-pill";
    const number = document.createElement("strong");
    number.textContent = value ?? "-";
    const name = document.createElement("span");
    name.textContent = label;
    item.append(number, name);
    grid.appendChild(item);
  }
  return grid;
}

function renderSectionText(title, text) {
  const section = document.createElement("section");
  section.className = "report-section";
  const heading = document.createElement("h4");
  heading.textContent = title;
  const body = document.createElement("p");
  body.textContent = text;
  section.append(heading, body);
  return section;
}

function renderListSection(title, items, formatter) {
  const section = document.createElement("section");
  section.className = "report-section";
  const heading = document.createElement("h4");
  heading.textContent = title;
  const list = document.createElement("div");
  list.className = "report-list";
  if (!items.length) {
    list.appendChild(renderMutedBlock("暂无"));
  }
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "report-row";
    row.textContent = formatter(item);
    list.appendChild(row);
  }
  section.append(heading, list);
  return section;
}

function compactValue(value) {
  if (Array.isArray(value)) return `${value.length} items`;
  if (value && typeof value === "object") return `${Object.keys(value).length} fields`;
  if (typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value ?? "");
}

async function loadLogs(runId) {
  const suffix = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  const response = await fetch(`/api/logs${suffix}`);
  const data = await response.json();
  renderLogs(data.logs || []);
}

function renderLogs(logs) {
  if (!logs.length) {
    logsEl.className = "logs empty";
    logsEl.textContent = "暂无日志";
    return;
  }
  logsEl.className = "logs";
  logsEl.innerHTML = "";
  for (const log of logs) {
    const node = document.createElement("section");
    node.className = "log-item";

    const title = document.createElement("div");
    title.className = "trace-title";
    const left = document.createElement("strong");
    left.textContent = `${log.purpose || "model"} · ${log.model_name || "model"}`;
    const right = document.createElement("span");
    right.textContent = `${log.duration_ms || 0} ms`;
    title.append(left, right);

    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = `${log.created_at || ""} · ${log.id || ""}`;
    const body = document.createElement("pre");
    body.textContent = JSON.stringify(log, null, 2);
    details.append(summary, body);

    node.append(title, details);
    logsEl.appendChild(node);
  }
}

async function clearLogs() {
  await fetch("/api/logs/clear", {method: "POST"});
  currentRunId = "";
  runIdEl.textContent = "No run";
  renderLogs([]);
}

resetPromptButton.addEventListener("click", () => {
  renderAgentPromptEditors(agentPromptDefaults);
});

previousReportFile.addEventListener("change", async () => {
  previousReport = null;
  baselineLabel.textContent = "未提供历史基线";
  const file = previousReportFile.files[0];
  if (!file) return;
  runButton.disabled = true;
  clearBaselineButton.disabled = true;
  previousReportFile.disabled = true;
  try {
    if (file.size > 1024 * 1024) throw new Error("历史报告不能超过 1 MiB");
    const report = JSON.parse(await file.text());
    if (!report || typeof report !== "object" || !Array.isArray(report.trade_plan) || !report.report_date) {
      throw new Error("请选择 PreMarketReport JSON");
    }
    previousReport = report;
    previousTradeDate.value = "";
    baselineLabel.textContent = `已载入 ${report.report_date} · 上一交易日待确认`;
    renderExecutionItems(report);
    autofillPreviousTradeDate(report.report_date);
  } catch (error) {
    previousReportFile.value = "";
    baselineLabel.textContent = error.message;
  } finally {
    runButton.disabled = false;
    clearBaselineButton.disabled = false;
    previousReportFile.disabled = false;
  }
});
clearBaselineButton.addEventListener("click", () => {
  previousReport = null;
  previousReportFile.value = "";
  previousTradeDate.value = "";
  baselineLabel.textContent = "未提供历史基线";
  renderExecutionItems(null);
});

async function autofillPreviousTradeDate(reportDate) {
  try {
    const response = await fetch("/api/calendar");
    if (!response.ok) return;
    const calendar = await response.json();
    if (!calendar.calendar_verified || !calendar.prev_trading_day) return;
    if (previousReport && previousReport.report_date === calendar.prev_trading_day) {
      previousTradeDate.value = calendar.prev_trading_day;
      baselineLabel.textContent = `已载入 ${previousReport.report_date} · 上一交易日 ${calendar.prev_trading_day}（日历推算）`;
    } else {
      baselineLabel.textContent = `已载入 ${reportDate} · 注意：日历推算 T-1 为 ${calendar.prev_trading_day}，与报告日期不一致，请核对`;
    }
  } catch (error) {
    // 日历接口不可用时保持人工确认，不改动输入。
  }
}

async function autoLoadLatestSnapshot() {
  try {
    const response = await fetch("/api/snapshot/latest");
    if (!response.ok) return;
    const data = await response.json();
    const snapshot = data.snapshot;
    if (!snapshot || typeof snapshot !== "object" || !snapshot.report_date || !Array.isArray(snapshot.trade_plan)) return;
    previousReport = snapshot;
    baselineLabel.textContent = `已载入 ${snapshot.report_date} · 上一交易日待确认（跨日自动载入）`;
    renderExecutionItems(snapshot);
    autofillPreviousTradeDate(snapshot.report_date);
  } catch (error) {
    // 无快照或接口不可用时保持手动选择。
  }
}
downloadReportButton.addEventListener("click", () => {
  if (!activeReport) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(activeReport, null, 2)], {type: "application/json"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = `advice-${activeReport.report_date}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

holdingsFile.addEventListener("change", async () => {
  const file = holdingsFile.files[0];
  if (!file) return;
  holdingsResultEl.className = "muted holdings-result";
  holdingsResultEl.textContent = "解析中…";
  try {
    if (file.size > 10 * 1024 * 1024) throw new Error("文件超过 10 MiB 限制");
    const buffer = await file.arrayBuffer();
    const response = await fetch("/api/holdings/import", {
      method: "POST",
      headers: {"Content-Type": "application/octet-stream"},
      body: buffer,
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "导入失败");
    renderHoldings(data.holdings);
  } catch (error) {
    holdingsResultEl.className = "muted holdings-result";
    holdingsResultEl.textContent = `导入失败：${error.message}`;
  } finally {
    holdingsFile.value = "";
  }
});

function renderHoldings(holdings) {
  const positions = (holdings && holdings.positions) || [];
  holdingsResultEl.className = "holdings-result";
  if (!positions.length) {
    holdingsResultEl.textContent = "未解析到持仓（导出文件可能为空）。";
    return;
  }
  const lines = positions.map((p) =>
    `${p.security_code} ${p.name}：持股 ${p.quantity}，可用 ${p.available_quantity}，冻结 ${p.frozen_quantity}，成本 ${p.cost_price}，现价 ${p.last_price}，市值 ${p.market_value}`
  );
  const note = holdings.snapshot_at
    ? `快照时间 ${holdings.snapshot_at}`
    : "导出文件非实时快照，下单前需重新核验资金与可卖数量。";
  holdingsResultEl.textContent = lines.join("\n") + "\n" + note;
}
runButton.addEventListener("click", runAgent);
emergencyStopButton.addEventListener("click", () => {
  renderAutomation({
    ...(activeAutoTradeRun || {}),
    status: "blocked",
    summary: "已触发本地紧急停止。当前原型只做前端状态阻断，不连接真实券商。",
    risk_events: [
      ...((activeAutoTradeRun || {}).risk_events || []),
      {
        event_id: `manual_stop_${Date.now()}`,
        type: "emergency_stop",
        level: "critical",
        status: "triggered",
        message: "用户触发紧急停止。",
        action: "block_orders",
        timestamp: new Date().toISOString(),
      },
    ],
  });
});
refreshLogsButton.addEventListener("click", () => loadLogs(currentRunId));
clearLogsButton.addEventListener("click", clearLogs);
devPanelButton.addEventListener("click", () => {
  const collapsed = researchShell.classList.toggle("dev-collapsed");
  devPanelButton.textContent = collapsed ? "Dev" : "Hide Dev";
});

setEmptyResults();
loadTools().catch((error) => {
  setStatus("Error", "error");
  toolsEl.textContent = error.message;
});
