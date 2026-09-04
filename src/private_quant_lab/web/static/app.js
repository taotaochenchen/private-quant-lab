const taskInput = document.querySelector("#task");
const modelInput = document.querySelector("#model");
const maxStepsInput = document.querySelector("#maxSteps");
const maxTokensInput = document.querySelector("#maxTokens");
const llmObservationInput = document.querySelector("#llmObservation");
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

async function loadTools() {
  const response = await fetch("/api/tools");
  const data = await response.json();
  taskInput.value = data.default_task || sampleTask;
  toolsEl.innerHTML = "";
  for (const tool of data.tools || []) {
    const pill = document.createElement("div");
    pill.className = "tool-pill";
    pill.textContent = tool;
    toolsEl.appendChild(pill);
  }
}

function setStatus(text, state) {
  statusEl.textContent = text;
  statusEl.className = `status ${state || ""}`.trim();
}

function setEmptyResults() {
  traceEl.className = "trace empty";
  traceEl.textContent = "等待运行";
  finalEl.className = "final empty";
  finalEl.textContent = "暂无结果";
  traceCountEl.textContent = "0 steps";
  logsEl.className = "logs empty";
  logsEl.textContent = "暂无日志";
  runIdEl.textContent = "No run";
}

function renderTrace(trace) {
  traceEl.className = "trace";
  traceEl.innerHTML = "";
  traceCountEl.textContent = `${trace.length} steps`;
  for (const [index, item] of trace.entries()) {
    const node = document.createElement("section");
    node.className = "trace-item";

    const title = document.createElement("div");
    title.className = "trace-title";
    const left = document.createElement("strong");
    left.textContent = item.type === "tool" ? `Tool: ${item.name}` : "Assistant";
    const right = document.createElement("span");
    right.textContent = `#${index + 1}`;
    title.append(left, right);

    const body = document.createElement("pre");
    if (item.type === "tool") {
      body.textContent = JSON.stringify(item.output, null, 2);
    } else {
      body.textContent = item.content || "";
    }

    node.append(title, body);
    traceEl.appendChild(node);
  }
}

async function runAgent() {
  const payload = {
    task: taskInput.value,
    model: modelInput.value,
    max_steps: Number(maxStepsInput.value || 4),
    max_tokens: Number(maxTokensInput.value || 900),
    llm_observation: llmObservationInput.checked,
  };

  setStatus("Running", "running");
  runButton.disabled = true;
  finalEl.className = "final empty";
  finalEl.textContent = "运行中...";
  traceEl.className = "trace empty";
  traceEl.textContent = "等待 Agent 返回调用过程...";

  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (Array.isArray(data.trace)) {
      renderTrace(data.trace);
    }
    currentRunId = data.run_id || "";
    runIdEl.textContent = currentRunId ? `Run ${currentRunId.slice(0, 8)}` : "No run";
    await loadLogs(currentRunId);
    if (!data.ok) {
      throw new Error(data.error || "run failed");
    }
    finalEl.className = "final";
    finalEl.textContent = data.final || "";
    setStatus("Done", "");
  } catch (error) {
    finalEl.className = "final";
    finalEl.textContent = `运行失败：${error.message}`;
    setStatus("Error", "error");
  } finally {
    runButton.disabled = false;
  }
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
    details.open = false;
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

runButton.addEventListener("click", runAgent);
refreshLogsButton.addEventListener("click", () => loadLogs(currentRunId));
clearLogsButton.addEventListener("click", clearLogs);

setEmptyResults();
loadTools().catch((error) => {
  setStatus("Error", "error");
  toolsEl.textContent = error.message;
});
