// Exercise the actual shipped helpers without a browser or filesystem navigation.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const template = fs.readFileSync(path.resolve(__dirname, '../reading_tasks/catalog_view.html'), 'utf8');
const start = template.indexOf('  const safeURL=');
const end = template.indexOf('  const option=', start);
assert.ok(start >= 0 && end > start, 'Missing shipped link helpers');
const declarations = template.slice(start, end);
function helpers(href, baseURI, anchors = []) {
  const document = {baseURI, querySelectorAll: () => anchors.map(file => ({
    dataset: {artifactPath: file.path}, getAttribute: name => name === 'href' ? file.href : null,
  }))};
  const sandbox = { URL, location: { href }, document, el: (tag, cls, text) => ({ tag, cls, text }) };
  vm.createContext(sandbox);
  vm.runInContext(declarations + '\nglobalThis.buildLink = link; globalThis.buildArtifactLink = artifactLink;', sandbox);
  return sandbox;
}
const catalog = 'file:///D:/IA/apps/video-reader/data/tasks/catalog/index.html';
const relative = '../../inbox-20261115/buddy-discussion.html';
const expected = 'file:///D:/IA/apps/video-reader/data/inbox-20261115/buddy-discussion.html';
for (const page of [catalog, 'about:srcdoc', 'https://preview.example.test/file-view']) {
  const context = helpers(page, catalog);
  for (const [label, cls] of [['打开笔记', 'main-artifact'], ['buddy-discussion.html', '']]) {
    const result = context.buildLink(label, relative, cls);
    assert.equal(result.tag, 'a', `${page}: ${label} must remain clickable`);
    assert.equal(result.href, expected, `${page}: ${label} must refer to the original artifact`);
  }
}
const artifact = { path: 'D:\\IA\\apps\\video-reader\\data\\inbox-20261115\\buddy-discussion.html', url: relative };
const mapped = 'https://preview.example.test/authorized/note#review';
for (const [href, base] of [
  [catalog, catalog], ['about:srcdoc', 'about:blank'],
  ['about:srcdoc', 'https://preview.example.test/file-view'],
  ['https://preview.example.test/file-view', 'https://preview.example.test/file-view'],
]) {
  const context = helpers(href, base, [{path:artifact.path, href:mapped}]);
  for (const label of ['打开笔记', 'buddy-discussion.html', '查看副本']) {
    const result = context.buildArtifactLink(label, artifact);
    assert.equal(result.tag, 'a');
    assert.equal(result.href, mapped, 'Reuse the host-rewritten static href');
  }
}
const native = helpers(catalog, catalog, [{path:artifact.path, href:relative}]);
assert.equal(native.buildArtifactLink('原生文件', artifact).href, expected);
const blocked = helpers(catalog, catalog, [{path:artifact.path, href:'data:,'}]);
assert.equal(blocked.buildArtifactLink('宿主拒绝的文件', artifact).tag, 'span', 'Do not bypass a blocked static href');
const unmapped = helpers('about:srcdoc', 'about:blank');
assert.equal(unmapped.buildArtifactLink('未映射的文件', artifact).tag, 'span', 'Do not invent an unapproved file URI');
const served = helpers('https://example.test/preview', 'https://example.test/library/catalog/index.html');
assert.equal(served.buildLink('笔记', '../notes/%E7%AC%94%E8%AE%B0%20%231.html').href,
  'https://example.test/library/notes/%E7%AC%94%E8%AE%B0%20%231.html');
for (const url of ['javascript:alert(1)', 'data:text/html,test', '', null]) {
  assert.equal(served.buildLink('无效地址', url).tag, 'span');
}
assert.equal(served.buildArtifactLink('仅提供网址', {url:'https://example.test/note'}).href, 'https://example.test/note');
console.log('Catalog link checks passed: static href reuse, opaque previews, main/detail/copy links and host blocks.');
