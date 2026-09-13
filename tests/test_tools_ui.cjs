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
  {name:'snowball_quotec',group:'雪球 · 行情',description:'行情',modes:['real'],schema:{},example:{symbols:'SH600000'}},
  {name:'snowball_fund_info',group:'蛋卷 · 基金',description:'基金',modes:['real'],schema:{},example:{fund_code:'000001'}}
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
console.log('tools.js syntax and real-only mode/group contracts OK');
`, context);
