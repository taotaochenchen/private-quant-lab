// Lightweight DOM contract test; this does not replace browser visual testing.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function element() {
  return {
    children: [], value: '', options: [], disabled: false,
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    setAttribute() {},
  };
}
const elements = new Map();
const get = id => {
  if (!elements.has(id)) elements.set(id, element());
  return elements.get(id);
};
const mode = get('mode');
mode.value = 'local';
mode.options = ['local', 'llm', 'real'].map(value => ({value, disabled: false}));
Object.defineProperty(mode, 'selectedOptions', {get() { return this.options.filter(o => o.value === this.value); }});
const document = {getElementById: get, createElement: element, querySelectorAll: () => []};
const source = fs.readFileSync(path.join(__dirname, '../src/private_quant_lab/web/static/tools.js'), 'utf8');
new vm.Script(source);
const context = vm.createContext({document, console, assert});
vm.runInContext(source.replace(/\ninit\(\);\s*$/, '') + `
catalog = [
  {name:'snowball_quotec',provider:'xueqiu',group:'雪球 · 行情',description:'行情',modes:['real'],schema:{},example:{symbols:'SH600000'}},
  {name:'snowball_fund_info',provider:'danjuan',group:'蛋卷 · 基金',description:'基金',modes:['real'],schema:{},example:{fund_code:'000001'}}
];
selectTool(catalog[0]);
assert.equal($('mode').value, 'real');
assert.equal($('mode').options[0].disabled, true);
assert.equal($('mode').options[1].disabled, true);
assert.equal($('modelField').hidden, true);
assert.equal($('run').disabled, false);
assert.ok($('catalog').children.some(item => item.textContent === '雪球 · 行情'));
assert.ok($('catalog').children.some(item => item.textContent === '蛋卷 · 基金'));
assert.equal(JSON.parse($('arguments').value).symbols, 'SH600000');
assert.equal($('snowballConfig').hidden, false);
$('provider').value = 'danjuan'; renderCatalog();
assert.equal($('count').textContent, '1 个工具');
assert.ok(!$('catalog').children.some(item => item.textContent === '雪球 · 行情'));
showResult({mode:'real', response:{ok:false, result:{status:'network_error', data_missing:true}}});
assert.ok($('error').textContent.includes('网络连接失败'));
assert.equal($('quality').textContent, '有缺失项');
showResult({mode:'real', response:{ok:true, result:{status:'ok', mock:false, fetched_at:'2026-09-13T12:00:00Z', schema_verified:false}}});
assert.equal($('error').textContent, '');
assert.equal($('fetchedAt').textContent, '2026-09-13T12:00:00Z');
assert.equal($('quality').textContent, '真实返回');
assert.equal($('resultNotice').hidden, false);
assert.ok($('logs').textContent.includes('未请求模型'));
showResult({mode:'real', response:{ok:false, result:{status:'token_required'}}});
assert.ok($('error').textContent.includes('u 可省略'));
selectTool({name:'mock_tool',description:'Mock',group:'量化',modes:['local'],example:{},schema:{}});
assert.equal($('snowballConfig').hidden, true);
console.log('tools.js syntax and real-only mode/group contracts OK');
`, context);
