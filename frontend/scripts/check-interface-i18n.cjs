const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const espree = require('espree');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/context/LanguageContext.jsx'), 'utf8');
const extra = fs.readFileSync(path.join(root, 'src/context/interfaceEnglish.js'), 'utf8').replace('export const', 'const');
let nodes = [];
let attributes = [];
const context = vm.createContext({
  NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
  Node: { TEXT_NODE: 3 },
  document: {
    body: {},
    createTreeWalker(_body, _type, filter) {
      const accepted = nodes.filter(n => filter.acceptNode(n) === 1);
      let index = 0;
      return { currentNode: null, nextNode() { this.currentNode = accepted[index++]; return this.currentNode; } };
    },
    querySelectorAll(selector) { return selector.startsWith('[placeholder]') ? attributes : []; },
  },
});
vm.runInContext(extra + '\n' + source.slice(source.indexOf('const legacyEnglish'), source.indexOf('const LanguageContext =')).replace('export function', 'function'), context);
const translate = (value, language) => context.translateInterfaceText(value, language);
const bridge = language => context.translateLegacyInterface(language);
const node = (text, protectedContent = false) => ({ nodeValue: text, parentElement: { closest: () => protectedContent ? {} : null } });

assert.equal(translate('正在載入問卷詳情…', 'en'), 'Loading survey details…');
assert.equal(translate('正在整理題目、統計與回覆資料，請稍候。', 'en'), 'Preparing questions, statistics, and responses. Please wait.');
assert.equal(translate('正在載入問卷詳情…', 'zh-TW'), '正在載入問卷詳情…');
assert.equal(translate('自訂問卷名稱', 'en'), '自訂問卷名稱');

nodes = [node('正在整理題目、統計與回覆資料，請稍候。'), node('正在整理題目、統計與回覆資料，請稍候。', true), node('分'), node('王平均')];
bridge('en');
assert.equal(nodes[0].nodeValue, 'Preparing questions, statistics, and responses. Please wait.');
assert.equal(nodes[1].nodeValue, '正在整理題目、統計與回覆資料，請稍候。');
assert.equal(nodes[2].nodeValue, '分');
assert.equal(nodes[3].nodeValue, '王平均');
bridge('zh-TW');
assert.equal(nodes[0].nodeValue, '正在整理題目、統計與回覆資料，請稍候。');
nodes[0].nodeValue = '連結已複製，可以分享給其他人了。';
bridge('en');
assert.equal(nodes[0].nodeValue, 'Link copied. You can now share it with others.');

const attrs = { 'aria-label': '關閉邀請視窗' };
attributes = [{ closest: () => null, getAttribute: key => attrs[key], setAttribute: (key, value) => { attrs[key] = value; } }];
bridge('en');
assert.equal(attrs['aria-label'], 'Close invitation dialog');

let checked = 0;
function scan(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) { scan(file); continue; }
    if (!file.endsWith('.jsx')) continue;
    const ast = espree.parse(fs.readFileSync(file, 'utf8'), { ecmaVersion: 'latest', sourceType: 'module', ecmaFeatures: { jsx: true } });
    function visit(n) {
      if (!n || typeof n !== 'object') return;
      if (n.type === 'JSXElement' && n.openingElement.name.name === 'InterfaceText') {
        for (const child of n.children) {
          const value = child.expression?.value;
          if (typeof value === 'string') {
            assert.ok(!/[\u4e00-\u9fff]/.test(translate(value, 'en')), `${file}: missing English for ${value}`);
            assert.equal(translate(value, 'zh-TW'), value);
            checked++;
          }
        }
      }
      for (const value of Object.values(n)) {
        if (Array.isArray(value)) value.forEach(visit);
        else if (value && typeof value === 'object') visit(value);
      }
    }
    visit(ast);
  }
}
scan(path.join(root, 'src'));
console.log(`Passed: ${checked} fixed UI labels, language switching, dynamic messages, attributes, and protected user content.`);
