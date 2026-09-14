import { parse } from 'espree';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../src/', import.meta.url));
const failures = [];
let files = 0;
const inputWords = new Set(['你好', '哈囉', '嗨', '您好', '建議', '可進一步詢問']);
const genders = new Set(['男', '女', '其他', '不願透露']);
function walkNode(node, file, parent) {
  if (!node || typeof node !== 'object') return;
  const value = node.type === 'Literal' && typeof node.value === 'string' ? node.value : node.type === 'JSXText' ? node.value : node.type === 'TemplateElement' ? node.value.raw : '';
  if (/[\p{Script=Han}]/u.test(value)) {
    const dataKey = parent?.type === 'Property' && parent.key === node;
    const persistedGender = file.endsWith('SignUpPage.jsx') && parent?.type === 'Property' && parent.key?.name === 'value' && genders.has(value);
    const inputMatcher = file.endsWith('workspace/page.jsx') && parent?.type === 'ArrayExpression' && inputWords.has(value);
    if (!dataKey && !persistedGender && !inputMatcher) failures.push(`${file}:${node.loc.start.line}: ${JSON.stringify(value)}`);
  }
  for (const child of Object.values(node)) if (Array.isArray(child)) child.forEach(n => walkNode(n, file, node)); else if (child && typeof child === 'object') walkNode(child, file, node);
}
function scan(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) scan(file);
    else if (/\.(js|jsx)$/.test(file)) {
      files++;
      walkNode(parse(readFileSync(file, 'utf8'), { ecmaVersion: 'latest', sourceType: 'module', ecmaFeatures: { jsx: true }, loc: true }), path.relative(root, file).replaceAll('\\', '/'));
    }
  }
}
scan(root);
if (failures.length) { console.error(failures.join('\n')); process.exitCode = 1; }
else console.log(`PASS: ${files} frontend modules contain no untranslated interface literals. Legacy input/data keys are explicitly allowed.`);
