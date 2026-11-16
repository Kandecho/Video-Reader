from pathlib import Path
from html.parser import HTMLParser
import shutil
import subprocess
import tempfile
import unittest
from urllib.parse import unquote, urlsplit

from reading_tasks.catalog import Catalog
from reading_tasks.followups import Followups
from reading_tasks.queue import Queue
from reading_tasks.store import Store


class StaticFileLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and 'data-artifact-path' in attrs:
            self.links.append(attrs)


class CatalogLinkTests(unittest.TestCase):
    def test_static_links_include_current_history_and_copies_with_escaped_relative_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = Queue(Store(root / 'tasks', 'link-library'))
            item = queue.enqueue('https://www.bilibili.com/video/BV1E1421t7m2?p=1',
                                 task='整理', new_task=True)['item_id']
            old = root / '历史笔记.md'
            current = root / "笔记 & ' #1 50%.html"
            copy = root / '副本.md'
            missing = root / '已缺失.md'
            for file in [old, current, copy, missing]:
                file.write_text('local fixture', encoding='utf-8')
            queue.record_result(item, {'summary':'旧稿', 'artifacts':[str(old), str(missing)]})
            queue.record_result(item, {'summary':'完成', 'artifacts':[str(current), str(old)]}, complete=True)
            Followups(queue).save(item, {'description':'另存副本', 'state':'done', 'artifacts':[str(copy)]})
            missing.unlink()
            catalog = Catalog(queue)
            catalog.build()
            rendered = catalog.index_path.read_text(encoding='utf-8')
            parser = StaticFileLinks()
            parser.feed(rendered)
            self.assertEqual({link['data-artifact-path'] for link in parser.links},
                             {str(old), str(current), str(copy)})
            self.assertEqual(len(parser.links), 3)
            for link in parser.links:
                href = link['href']
                self.assertEqual(urlsplit(href).scheme, '')
                self.assertFalse(href.startswith(('/', '\\')))
                self.assertEqual((catalog.directory / unquote(href)).resolve(), Path(link['data-artifact-path']))
            self.assertIn('%23', rendered)
            self.assertIn('%25', rendered)
            self.assertIn('&#x27;', rendered)
            self.assertNotIn('__CATALOG_FILE_LINKS__', rendered)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed to execute the catalog link helpers')
    def test_dynamic_entries_reuse_host_processed_static_links(self):
        result = subprocess.run(
            [shutil.which('node'), str(Path(__file__).with_name('catalog_links.cjs'))],
            capture_output=True, text=True, encoding='utf-8', timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
