import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reading_tasks.api import execute
from reading_tasks.queue import Queue
from video_reader.common import ReaderError, write_json
from video_reader.reader import Reader


class CatalogAPI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'config.json'
        write_json(self.config, {'cache_dir': 'cache', 'tasks': {'directory': 'tasks'}})
        self.reader = Reader(self.config)
        self.queue = Queue.from_settings(self.reader.config, self.config)

    def test_build_update_and_result_refresh_share_the_registered_records(self):
        self.assertFalse(execute(self.reader, 'catalog-status')['enabled'])
        item = self.queue.enqueue('BV1E1421t7m2', title='Original')['item']
        artifact = self.root / 'notes.html'
        artifact.write_text('<p>Original result</p>', encoding='utf-8')
        self.queue.record_result(item['id'], {'summary': 'First result', 'artifacts': [str(artifact)]}, complete=True)
        built = execute(self.reader, 'catalog-build', result={
            'views': [{'id': 'batch-one', 'label': 'First batch', 'task_ids': [item['id']]}]})
        self.assertEqual(built['stats']['videos'], 1)
        execute(self.reader, 'catalog-update', item['id'], result={
            'retention': '轻量记录', 'purposes': ['深入学习'], 'title': 'Display title'})
        saved = execute(self.reader, 'queue-result', item['id'], complete=True,
                        result={'summary': 'New result', 'artifacts': [str(artifact)],
                                'catalog': {'purposes': ['核查']}})
        self.assertEqual(saved['catalog_refresh']['status'], 'ready')
        snapshot = json.loads(Path(built['snapshot_path']).read_text(encoding='utf-8'))
        self.assertEqual(snapshot['stats']['results'], 2)
        video = snapshot['videos'][0]
        self.assertEqual(video['title'], 'Display title')
        self.assertEqual(video['purposes'], ['核查'])
        self.assertEqual(len(video['tasks'][0]['results']), 2)
        self.assertEqual(snapshot['views'][0]['task_ids'], [item['id']])

    def test_metadata_cannot_change_completion_state(self):
        item = self.queue.enqueue('BV1E1421t7m2')['item']
        with self.assertRaises(ReaderError):
            execute(self.reader, 'catalog-update', item['id'], result={'state': 'done'})
        self.assertEqual(self.queue.show(item['id'])['state'], 'pending')

    def test_mcp_uses_same_catalog_status_without_material_acquisition(self):
        from video_reader import mcp_server
        with patch.object(mcp_server, 'Reader', return_value=self.reader), \
                patch.object(self.reader, 'open', side_effect=AssertionError('no reading')):
            result = mcp_server.video_tasks(action='catalog-status')
        payload = json.loads(next(block.text for block in result if block.type == 'text'))
        self.assertEqual(payload['status'], 'not_built')
        self.assertFalse(payload['enabled'])


if __name__ == '__main__':
    unittest.main()
