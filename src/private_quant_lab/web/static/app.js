const taskInput = document.querySelector("#task");
const modelInput = document.querySelector("#model");
const maxStepsInput = document.querySelector("#maxSteps");
const maxTokensInput = document.querySelector("#maxTokens");
const thinkingModeInput = document.querySelector("#thinkingMode");
const llmObservationInput = document.querySelector("#llmObservation");
const systemPromptInput = document.querySelector("#systemPrompt");
const resetPromptButton = document.querySelector("#resetPromptButton");
const runButton = document.querySelector("#runButton");
const sampleButton = document.querySelector("#sampleButton");
const statusEl = document.querySelector("#status");
const traceEl = document.querySelector("#trace");
const finalEl = document.querySelector("#final");
const traceCountEl = document.querySelector("#traceCount");
const toolsEl = document.querySelector("#tools");
const logsEl = document.querySelector("#logs");
const runIdEl = document.querySelector("#runId");
const refreshLogsButton = document.querySelector("#refreshLogsButton");
const clearLogsButton = document.querySelector("#clearLogsButton");

const sampleTask = "先用 web_search 查 NVDA AI demand，再用 news_sentiment 分析 NVDA 新闻情绪，最后输出 Final。";
let currentRunId = "";
let traceItems = [];
let defaultSystemPrompt = "";

async function loadTools() {
  const response = await fetch("/api/tools");
  const data = await response.json();
  taskInput.value = data.default_task || sampleTask;
  defaultSystemPrompt = data.default_system_prompt || "";
  systemPromptInput.value = defaultSystemPrompt;
  toolsEl.innerHTML = "";
  for (const tool of data.tool_schemas || []) {
    toolsEl.appendChild(renderToolSchema(tool));
  }
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
  logsEl.className = "logs empty";
  logsEl.textContent = "暂无日志";
  runIdEl.textContent = "No run";
}

function resetRunView() {
  traceItems = [];
  traceEl.className = "trace";
  traceEl.innerHTML = "";
  finalEl.className = "final empty";
  finalEl.textContent = "运行中...";
  traceCountEl.textContent = "0 steps";
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
  if (item.type === "assistant") return "Assistant";
  if (item.type === "tool") return `Observation · ${item.name}`;
  if (item.type === "tool_started") return `Tool Call · ${item.name}`;
  return "Event";
}

async function runAgent() {
  const payload = {
    task: taskInput.value,
    model: modelInput.value,
    max_steps: Number(maxStepsInput.value || 4),
    max_tokens: Number(maxTokensInput.value || 900),
    thinking_mode: thinkingModeInput.checked,
    llm_observation: llmObservationInput.checked,
    system_prompt: systemPromptInput.value,
  };

  setStatus("Running", "running");
  runButton.disabled = true;
  resetRunView();

  try {
    const response = await fetch("/api/run_stream", {
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
    if (currentRunId) {
      await loadLogs(currentRunId);
    }
  }
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
    appendTrace({
      type: "assistant",
      step: data.step,
      content: data.content || "",
      reasoning_content: data.reasoning_content || "",
      tool_calls: data.tool_calls || [],
    });
  } else if (eventName === "tool_started") {
    appendTrace({type: "tool_started", step: data.step, name: data.name, arguments: data.arguments});
  } else if (eventName === "tool_finished") {
    appendTrace({type: "tool", step: data.step, name: data.name, output: data.output});
  } else if (eventName === "final") {
    finalEl.className = "final";
    finalEl.textContent = data.final || "";
  } else if (eventName === "run_finished") {
    finalEl.className = "final";
    finalEl.textContent = data.final || finalEl.textContent;
    setStatus("Done", "");
  } else if (eventName === "run_error") {
    finalEl.className = "final";
    finalEl.textContent = `运行失败：${data.error || "unknown error"}`;
    setStatus("Error", "error");
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

sampleButton.addEventListener("click", () => {
  taskInput.value = sampleTask;
});

resetPromptButton.addEventListener("click", () => {
  systemPromptInput.value = defaultSystemPrompt;
});

runButton.addEventListener("click", runAgent);
refreshLogsButton.addEventListener("click", () => loadLogs(currentRunId));
clearLogsButton.addEventListener("click", clearLogs);

setEmptyResults();
loadTools().catch((error) => {
  setStatus("Error", "error");
  toolsEl.textContent = error.message;
});
