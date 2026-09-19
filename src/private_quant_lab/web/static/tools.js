const $ = (id) => document.getElementById(id);
const pretty = (value) => JSON.stringify(value, null, 2);
let catalog = [], selected = null, current = null, history = [], busy = false;
const failureHints = {
  content_permission_required: '本地许可未确认；确认具备相应用途许可后设置 XUEQIU_CONTENT_PERMISSION_CONFIRMED。请求未发出。',
  token_required: '未配置凭据。在 .env 中设置 XUEQIUTOKEN="xq_a_token=..."，u 可省略。请求未发出。',
  invalid_token_configuration: '凭据格式错误，请检查 .env 的 XUEQIUTOKEN。',
  invalid_snowball_configuration: '配置格式错误，请检查超时和许可配置。',
  auth_or_access_denied: '上游拒绝访问，可能是凭据失效或访问限制；不能仅据此判断 token 无效。',
  network_error: '网络连接失败，请检查服务端网络、代理和运行权限。',
  timeout: '请求超时，本次未获得数据。',
  rate_limited: '上游限流，请稍后手动重试。',
  access_challenge: '上游要求访问验证，本次停止请求。',
  redirect_blocked: '上游返回重定向，本次停止请求。',
  busy: '另一个真实查询正在执行，请稍后重试。',
  empty: '上游返回空数据。',
  invalid_json: '上游未返回有效 JSON。',
  upstream_error: '上游返回业务错误。',
  upstream_mapping_unverified: '上游接口映射尚未验证，返回内容不可作为有效指标。',
  missing_dependency: '服务端尚未安装 pysnowball 可选依赖。',
};
function failureMessage(response) {
  if (response?.ok) return '';
  const code = response?.result?.status;
  return failureHints[code] ? `${failureHints[code]} (${code})` : response?.error || code || '请求失败';
}
function renderConfigRequirement() {
  $('snowballConfig').hidden = !selected?.name.startsWith('snowball_');
  $('authRequirement').textContent = selected?.requires_token
    ? '此接口需要 xq_a_token；u 可省略。配置已读取不代表认证已通过。'
    : '此接口不发送雪球 Cookie；配置状态不代表接口连通状态。';
}
async function refreshConfig() {
  $('refreshConfig').disabled = true; $('configStatus').textContent = '读取中';
  try {
    const response = await fetch('/api/tools/snowball_config', {cache: 'no-store'});
    if (!response.ok) throw Error('配置状态读取失败，请确认已启动新版服务。');
    const config = await response.json();
    $('configStatus').textContent = config.status === 'ok'
      ? `Token ${config.token_configured ? '已配置' : '未配置'} · 内容许可${config.content_permission_confirmed ? '已确认' : '未确认'} · 超时 ${config.timeout_seconds} 秒`
      : '配置格式错误，请检查服务端 .env。';
  } catch (error) { $('configStatus').textContent = error.message; }
  finally { $('refreshConfig').disabled = false; }
}
function tree(value, root, depth = 0) {
  if (value === null || typeof value !== 'object') { root.textContent = String(value); return; }
  for (const [key, item] of Object.entries(value)) {
    if (item !== null && typeof item === 'object') {
      const details = document.createElement('details'), summary = document.createElement('summary');
      summary.textContent = `${key} ${Array.isArray(item) ? '[' + item.length + ']' : '{' + Object.keys(item).length + '}'}`;
      details.open = depth < 1; details.append(summary); tree(item, details, depth + 1); root.append(details);
    } else {
      const row = document.createElement('div'); row.className = 'leaf';
      for (const text of [key, item === null ? 'null' : String(item)]) { const cell = document.createElement('span'); cell.textContent = text; row.append(cell); }
      root.append(row);
    }
  }
}
function renderCatalog() {
  $('catalog').replaceChildren();
  const items = catalog.filter(t => (!$('provider').value || (t.provider || 'quant') === $('provider').value)
    && (t.name + t.description).toLowerCase().includes($('search').value.toLowerCase()));
  $('count').textContent = `${items.length} 个工具`;
  for (const group of [...new Set(catalog.map(t => t.group))]) {
    const tools = items.filter(t => t.group === group); if (!tools.length) continue;
    const title = document.createElement('p'); title.className = 'group-title'; title.textContent = group; $('catalog').append(title);
    for (const tool of tools) { const button = document.createElement('button'); button.textContent = tool.name; button.className = selected?.name === tool.name ? 'selected' : ''; button.disabled = busy; button.onclick = () => selectTool(tool); $('catalog').append(button); }
  }
}
function selectTool(tool) {
  selected = tool; $('name').textContent = tool.name; $('description').textContent = tool.description;
  renderConfigRequirement();
  for (const option of $('mode').options) option.disabled = !(tool.modes || ['local', 'llm']).includes(option.value);
  if ($('mode').selectedOptions[0].disabled) $('mode').value = tool.modes?.[0] || 'local';
  $('mode').onchange();
  $('group').textContent = tool.group; $('implementation').textContent = tool.implementation;
  $('schema').textContent = pretty(tool.schema); $('arguments').value = pretty(tool.example); $('run').disabled = false;
  $('error').textContent = ''; showResult(null); renderCatalog();
}
function showResult(record) {
  current = record; $('tree').replaceChildren(); $('logs').replaceChildren();
  $('raw').textContent = record ? pretty(record.response) : '';
  $('status').textContent = record ? (record.response.ok ? '执行成功' : '执行失败') : '未执行';
  $('status').className = record ? (record.response.ok ? 'ok' : 'bad') : '';
  $('duration').textContent = record ? `${record.response.elapsed_ms ?? '--'} ms` : '--';
  const result = record?.response.result;
  $('error').textContent = record ? failureMessage(record.response) : '';
  $('fetchedAt').textContent = result?.fetched_at || '--';
  $('source').textContent = result?.observation_source || result?.source || (result?.mock ? 'local_mock' : '--');
  $('quality').textContent = result ? (result.data_missing || result.missing_fields?.length ? '有缺失项' : result.observation_error || result.observation_source === 'local_fallback' ? '已降级' : result.is_mock || result.mock ? '模拟数据' : '真实返回') : '--';
  const notices = [...(result?.warnings || [])];
  if (result?.schema_verified === false) notices.unshift('上游字段口径未校验。');
  $('resultNotice').textContent = notices.join(' '); $('resultNotice').hidden = !notices.length;
  if (record) tree(record.response.result ?? record.response, $('tree')); else $('tree').textContent = '暂无结果';
  if (record?.logs?.length) tree(record.logs, $('logs')); else $('logs').textContent = record?.logsError || (record?.mode === 'real' ? '真实接口直连，本次未请求模型。' : '无模型请求记录');
  $('copy').disabled = $('download').disabled = !record;
}
function renderHistory() {
  $('history').replaceChildren();
  if (!history.length) $('history').textContent = '暂无记录';
  for (const record of history) {
    const button = document.createElement('button'); button.className = 'record'; button.disabled = busy;
    for (const text of [record.name, record.time, record.response.ok ? '成功' : '失败']) { const span = document.createElement('span'); span.textContent = text; button.append(span); }
    button.onclick = () => { selectTool(catalog.find(t => t.name === record.name)); $('arguments').value = pretty(record.arguments); $('mode').value = record.mode; $('model').value = record.model; $('mode').onchange(); showResult(record); }; $('history').append(button);
  }
}
async function execute() {
  if (!selected || busy) return;
  $('error').textContent = ''; let args;
  try { args = JSON.parse($('arguments').value); if (!args || typeof args !== 'object' || Array.isArray(args)) throw Error('参数必须是 JSON 对象'); } catch (error) { $('error').textContent = error.message; return; }
  const record = {name: selected.name, arguments: args, mode: $('mode').value, model: $('model').value, time: new Date().toLocaleTimeString()};
  busy = true; showResult(null); $('status').textContent = '执行中'; $('run').textContent = '执行中…';
  for (const id of ['run', 'example', 'format', 'arguments', 'mode', 'model', 'clear']) $(id).disabled = true;
  renderCatalog(); renderHistory();
  try {
    const response = await fetch('/api/tools/execute', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(record)});
    record.response = await response.json();
    if (!response.ok && record.response.ok !== false) record.response = {ok: false, error: `HTTP ${response.status}`};
    if (record.mode === 'llm' && record.response.run_id) {
      try { const logs = await fetch(`/api/logs?run_id=${encodeURIComponent(record.response.run_id)}`); if (!logs.ok) throw Error('模型日志查询失败'); record.logs = (await logs.json()).logs; } catch (error) { record.logsError = error.message; }
    }
  } catch (error) { record.response = {ok: false, error: error.message}; $('error').textContent = error.message; }
  finally {
    busy = false; for (const id of ['run', 'example', 'format', 'arguments', 'mode', 'model', 'clear']) $(id).disabled = false;
    $('run').textContent = '执行工具'; history.unshift(record); history = history.slice(0, 30); showResult(record); renderHistory(); renderCatalog();
  }
}
$('search').oninput = renderCatalog;
$('provider').onchange = renderCatalog;
$('refreshConfig').onclick = refreshConfig;
$('example').onclick = () => { if (selected) $('arguments').value = pretty(selected.example); };
$('format').onclick = () => { try { $('arguments').value = pretty(JSON.parse($('arguments').value)); $('error').textContent = ''; } catch (error) { $('error').textContent = error.message; } };
$('mode').onchange = () => { $('modelField').hidden = $('mode').value !== 'llm'; };
$('run').onclick = execute;
$('clear').onclick = () => { history = []; renderHistory(); };
$('copy').onclick = async () => { try { await navigator.clipboard.writeText(pretty(current.response)); } catch (error) { $('error').textContent = '复制失败：' + error.message; } };
$('download').onclick = () => { const url = URL.createObjectURL(new Blob([pretty(current.response)], {type: 'application/json'})); const a = document.createElement('a'); a.href = url; a.download = current.name + '.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
document.querySelectorAll('[data-view]').forEach(button => { button.onclick = () => { document.querySelectorAll('[data-view]').forEach(tab => tab.setAttribute('aria-selected', String(tab === button))); for (const view of ['tree', 'raw', 'logs']) $(view).hidden = view !== button.dataset.view; }; });
async function init() { try { const response = await fetch('/api/tool_catalog'); if (!response.ok) throw Error('工具列表加载失败'); catalog = (await response.json()).tools; if (catalog.length) selectTool(catalog.find(t => t.name === 'snowball_pankou') || catalog[0]); } catch (error) { $('name').textContent = '加载失败'; $('error').textContent = error.message; } await refreshConfig(); }
init();
