import json
from pathlib import Path
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from reading_tasks.catalog import Catalog
from reading_tasks.queue import Queue
from reading_tasks.store import Store
from video_reader.common import ReaderError, read_json

URL='https://www.bilibili.com/video/BV1E1421t7m2?p=1'


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.queue=Queue(Store(self.root/'tasks','test-library'),self.root/'cache')
        self.catalog=Catalog(self.queue)
        self.template=self.root/'template.html'
        self.template.write_text('<!doctype html><script id="data" type="application/json">__CATALOG_DATA__</script>',encoding='utf-8')
        self.patcher=patch('reading_tasks.catalog.TEMPLATE',self.template)
        self.patcher.start();self.addCleanup(self.patcher.stop)

    def item(self, source=URL, task='整理内容', title='测试视频'):
        return self.queue.enqueue(source,task,title,new_task=True)['item']['id']

    def result(self,item_id,text='正文',complete=True,**extra):
        import uuid
        artifact=self.root/('note-'+uuid.uuid4().hex+'.md')
        artifact.write_text(text,encoding='utf-8')
        output=self.queue.record_result(item_id,{'summary':text,'artifacts':[str(artifact)],
            'task_scope':'本次约定范围','coverage':{'source_intervals':[[10,20]]},**extra},complete=complete)
        return output,artifact

    def snapshot(self):
        return read_json(self.catalog.snapshot_path)

    def test_groups_tasks_by_source_and_part_and_keeps_every_result_version(self):
        first=self.item(task='理解'); second=self.item(task='翻译')
        third=self.item(URL.replace('?p=1','?p=2'))
        self.result(first,'初稿',False);self.result(first,'修改稿')
        self.result(second,'译文');self.result(third,'第二分P')
        self.catalog.build()
        data=self.snapshot()
        self.assertEqual(data['stats']['videos'],2)
        self.assertEqual(data['stats']['tasks'],3)
        self.assertEqual(data['stats']['results'],4)
        video=next(v for v in data['videos'] if v['source']==URL)
        versions=next(t for t in video['tasks'] if t['id']==first)['results']
        self.assertEqual([x['summary'] for x in versions],['修改稿','初稿'])
        self.assertEqual([x['complete'] for x in versions],[True,False])
        self.assertFalse(any(x['full_video_verified'] for t in video['tasks'] for x in t['results']))
        self.assertEqual({t['id'] for t in data['tasks']},{first,second,third})
        for source in data['videos']:
            for task in source['tasks']:
                self.assertEqual(next(t for t in data['tasks'] if t['id']==task['id']),task)
                self.assertEqual(task['source'],source['source'])
                self.assertEqual(task['source_title'],source['title'])
                self.assertEqual(task['preview_url'],source['preview_url'])

    def test_cache_and_manual_done_without_results_do_not_become_reading_entries(self):
        unfinished=self.item()
        self.queue.update(unfinished,state='done')
        cache=self.root/'cache/v_fixture';cache.mkdir(parents=True)
        (cache/'manifest.json').write_text('{"title":"not read"}',encoding='utf-8')
        self.catalog.build()
        self.assertEqual(self.snapshot()['videos'],[])
        self.assertEqual(self.snapshot()['stats']['excluded_without_results'],1)
        task=self.snapshot()['tasks'][0]
        self.assertEqual((task['id'],task['state']),(unfinished,'done'))
        self.assertEqual(task['results'],[])
        self.assertEqual(task['delivery']['formats'],[])
        self.assertNotIn('task_description',task['metadata'])

    def test_task_view_includes_unstarted_tasks_without_creating_result_entries(self):
        pending=self.item(task='整理为笔记',title='待整理视频')
        completed=self.item(task='保存至Casebook',title='待整理视频')
        self.result(completed)
        self.catalog.build({'task_metadata':{pending:{'task_description':'整理为笔记','format':'HTML'},
                                              completed:{'task_description':'保存至Casebook'}}})
        data=self.snapshot()
        self.assertEqual(data['stats']['total_tasks'],2)
        self.assertEqual(data['stats']['without_results'],1)
        self.assertEqual(data['stats']['total_task_states'],{'pending':1,'done':1})
        self.assertEqual(data['stats']['tasks'],1)
        self.assertEqual(data['stats']['task_states'],{'done':1})
        self.assertEqual(data['stats']['results'],1)
        self.assertEqual([t['id'] for t in data['videos'][0]['tasks']],[completed])
        task=next(t for t in data['tasks'] if t['id']==pending)
        self.assertEqual((task['state'],task['work']),('pending','整理为笔记'))
        self.assertEqual(task['results'],[])
        self.assertEqual(task['delivery'],{'formats':[],'target':'HTML','matches_target':False})
        self.assertEqual(task['source'],URL)
        self.assertEqual(task['source_title'],'待整理视频')
        self.assertEqual(task['preview_url'],'')
        self.assertEqual(task['metadata']['task_description'],'整理为笔记')

    def test_task_description_is_free_text_and_does_not_change_state(self):
        item=self.item(task='请整理为笔记')
        self.catalog.build()
        self.assertNotIn('task_description',self.snapshot()['tasks'][0]['metadata'])
        description='把里面的交互想法整理好，保存到我指定的资料夹；保留当时上下文。'
        self.catalog.update_metadata(item,{'task_description':description})
        task=self.snapshot()['tasks'][0]
        self.assertEqual(task['task_description'],description)
        self.assertNotIn('task_description',task['metadata'])
        self.assertEqual((task['state'],task['results']),('pending',[]))
        self.catalog.update_metadata(item,{'task_description':'任'*4000})
        self.assertEqual(self.snapshot()['tasks'][0]['task_description'],'任'*4000)
        for invalid in (['整理为笔记'],1,{},'任'*4001):
            with self.subTest(invalid=invalid),self.assertRaises(ReaderError):
                self.catalog.update_metadata(item,{'task_description':invalid})
        self.catalog.update_metadata(item,{'task_description':''})
        self.assertIsNone(self.snapshot()['tasks'][0]['task_description'])

    def test_new_enqueue_refreshes_enabled_catalog_after_commit_without_reading(self):
        first=self.queue.enqueue(URL,task='先保存链接')
        self.assertTrue(first['created'])
        self.assertNotIn('catalog_refresh',first)
        self.assertFalse(self.catalog.directory.exists())
        self.catalog.build()
        with patch.object(Catalog,'_records',wraps=self.catalog._records) as records:
            added=self.queue.enqueue(URL,task='另一个需要完成的工作')
        self.assertEqual(records.call_count,1)
        self.assertTrue(added['created'])
        self.assertFalse(added['video_reading_started'])
        self.assertEqual(added['item']['state'],'pending')
        self.assertEqual(added['catalog_refresh']['status'],'ready')
        data=self.snapshot()
        self.assertEqual({t['id'] for t in data['tasks']},{first['item_id'],added['item_id']})
        self.assertEqual(data['stats']['without_results'],2)
        self.assertEqual(data['videos'],[])
        duplicate=self.queue.enqueue(URL,task='另一个需要完成的工作')
        self.assertTrue(duplicate['duplicate'])
        self.assertNotIn('catalog_refresh',duplicate)

    def test_enqueue_refresh_failure_keeps_the_committed_task_and_can_be_rebuilt(self):
        self.catalog.build()
        with patch.object(Catalog,'_write_html',side_effect=RuntimeError('renderer unavailable')):
            saved=self.queue.enqueue(URL,task='稍后整理这个材料')
        self.assertTrue(saved['created'])
        self.assertFalse(saved['video_reading_started'])
        self.assertEqual(saved['catalog_refresh']['status'],'failed')
        self.assertEqual(self.queue.show(saved['item_id'])['task'],'稍后整理这个材料')
        self.assertEqual(self.catalog.status()['status'],'needs_refresh')
        self.catalog.build()
        self.assertEqual(self.snapshot()['tasks'][0]['id'],saved['item_id'])
        self.assertEqual(self.catalog.status()['status'],'ready')

    def test_partial_result_remains_paused_and_coverage_is_preserved(self):
        item=self.item();self.result(item,complete=False)
        self.queue.update(item,state='paused')
        self.catalog.build()
        task=self.snapshot()['videos'][0]['tasks'][0]
        self.assertEqual(task['state'],'paused')
        self.assertFalse(task['results'][0]['complete'])
        self.assertEqual(task['results'][0]['coverage'],{'source_intervals':[[10,20]]})

    def test_missing_and_modified_artifacts_keep_the_history_with_integrity_flags(self):
        first=self.item();second=self.item(task='另一个要求')
        _,changed=self.result(first,'before');_,missing=self.result(second)
        changed.write_text('after',encoding='utf-8');missing.unlink()
        self.catalog.build()
        data=self.snapshot()
        self.assertEqual(data['stats']['changed_artifacts'],1)
        self.assertEqual(data['stats']['missing_artifacts'],1)
        artifacts=[a for t in data['videos'][0]['tasks'] for r in t['results'] for a in r['artifacts']]
        self.assertEqual({(a['exists'],a['hash_valid']) for a in artifacts},{(True,False),(False,None)})

    def test_results_and_state_updates_refresh_only_after_catalog_enabled(self):
        item=self.item();saved,_=self.result(item)
        self.assertNotIn('catalog_refresh',saved)
        self.assertFalse(self.catalog.directory.exists())
        self.catalog.build()
        saved,_=self.result(item,'second version')
        self.assertEqual(saved['catalog_refresh']['status'],'ready')
        self.assertEqual(self.snapshot()['stats']['results'],2)
        changed=self.queue.update(item,state='paused',task='新的要求')
        self.assertEqual(changed['catalog_refresh']['status'],'ready')
        task=self.snapshot()['videos'][0]['tasks'][0]
        self.assertEqual((task['state'],task['request']),('paused','新的要求'))

    def test_render_failure_never_discards_committed_result_and_can_be_rebuilt(self):
        item=self.item();self.catalog.build()
        with patch.object(Catalog,'_write_html',side_effect=RuntimeError('renderer unavailable')):
            saved,_=self.result(item)
        self.assertEqual(saved['state'],'done')
        self.assertEqual(saved['catalog_refresh']['status'],'failed')
        self.assertEqual(self.queue.show(item)['latest_result']['summary'],'正文')
        self.assertEqual(self.catalog.status()['status'],'needs_refresh')
        self.catalog.build()
        self.assertEqual(self.catalog.status()['status'],'ready')
        self.assertEqual(self.snapshot()['stats']['results'],1)

    def test_views_are_only_task_id_filters_and_metadata_cannot_replace_state(self):
        item=self.item();self.result(item)
        self.catalog.build({'task_metadata':{item:{'retention':'轻量记录','purposes':['核查'],'title':'明确标题','notes':'Repo待核'}},
                            'views':[{'id':'batch-one','label':'第一批','task_ids':[item]}]})
        snapshot=self.snapshot()
        self.assertEqual(snapshot['views'][0],{'id':'batch-one','label':'第一批','task_ids':[item]})
        self.assertEqual(snapshot['videos'][0]['title'],'明确标题')
        self.queue.update(item,state='paused')
        self.assertEqual(self.snapshot()['videos'][0]['tasks'][0]['state'],'paused')
        with self.assertRaises(ReaderError):
            self.catalog.update_metadata(item,{'state':'done'})
        with self.assertRaises(ReaderError):
            self.catalog.build({'views':[{'id':'bad','label':'bad','task_ids':[{}]}]})

    def test_later_result_metadata_and_later_manual_metadata_take_precedence_per_field(self):
        item=self.item();self.result(item)
        self.catalog.build({'task_metadata':{item:{'retention':'轻量记录','title':'fixed title','purposes':['参考']}}})
        self.result(item,'deeper',catalog={'retention':'深度提取','purposes':['深入学习']})
        task=self.snapshot()['videos'][0]['tasks'][0]
        self.assertEqual(task['metadata']['retention'],'深度提取')
        self.assertEqual(task['metadata']['title'],'fixed title')
        self.catalog.update_metadata(item,{'retention':'简述索引'})
        self.assertEqual(self.snapshot()['videos'][0]['tasks'][0]['metadata']['retention'],'简述索引')

    def test_untrusted_text_cannot_terminate_inline_json(self):
        item=self.item(title='</script><script>bad()</script>')
        self.result(item,'<img onerror=bad()>\u2028&')
        self.catalog.build()
        html=self.catalog.index_path.read_text(encoding='utf-8')
        payload=html.split('application/json">',1)[1].rsplit('</script>',1)[0]
        self.assertNotIn('</script>',payload)
        decoded=json.loads(payload)
        self.assertEqual(decoded['videos'][0]['title'],'</script><script>bad()</script>')
        self.assertIn('\\u2028',payload)

    def test_preview_uses_only_referenced_material_and_never_creates_an_unread_entry(self):
        item=self.item();self.result(item)
        image=self.root/'cached.png';image.write_bytes(b'preserved preview bytes')
        self.catalog.build({'task_metadata':{item:{'preview_path':str(image)}}})
        self.assertTrue(self.snapshot()['videos'][0]['preview_url'].startswith('data:image/png;base64,'))
        self.assertEqual(self.snapshot()['stats']['videos'],1)

    def test_two_concurrent_results_cannot_publish_an_older_snapshot_last(self):
        first=self.item();second=self.item(task='second');self.catalog.build()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures=[executor.submit(self.result,item,str(i)) for i,item in enumerate((first,second))]
            for future in futures: self.assertEqual(future.result()[0]['catalog_refresh']['status'],'ready')
        self.assertEqual(self.snapshot()['stats']['tasks'],2)
        self.assertEqual(self.snapshot()['stats']['results'],2)

    def test_target_format_does_not_replace_actual_output_formats(self):
        item=self.item()
        self.result(item)
        self.catalog.build({'task_metadata':{item:{'format':'HTML'}}})
        task=self.snapshot()['videos'][0]['tasks'][0]
        self.assertEqual(task['delivery'],{'formats':['Markdown'],'target':'HTML','matches_target':False})
        html=self.root/'answer.html';html.write_text('<p>HTML output</p>',encoding='utf-8')
        receipt=self.root/'receipt.json';receipt.write_text('{}',encoding='utf-8')
        self.queue.record_result(item,{'summary':'已整理HTML','artifacts':[str(html),str(receipt)]},complete=True)
        task=self.snapshot()['videos'][0]['tasks'][0]
        self.assertEqual(task['delivery']['formats'],['HTML'])
        self.assertTrue(task['delivery']['matches_target'])
        self.assertEqual(task['results'][1]['delivery_formats'],['Markdown'])

    def test_origin_snapshots_and_valid_intent_are_projected_without_adjacent_messages(self):
        item=self.item(task='想核一下论据')
        other=self.item(task='另一个视频要求')
        origin={'id':'im_quote','text':'想核一下论据','seq':5,'sent_at':123,
                'msg_type':1,'provider':'bilibili_dm','peer':'private-peer','account_scope':'private-scope'}
        note={'original':'想核一下论据','kind':'request','request':'想核一下论据','comment':None,
              'basis':'explicit_user_confirmation','source_message_id':'im_quote'}
        with self.queue.store.connect() as db:
            self.queue.link_origin(db,item,origin)
            self.queue.record_intent(db,item,note)
            self.queue.link_origin(db,other,{'id':'im_unlinked','text':'无关附言','seq':6})
        self.result(item)
        self.catalog.build()
        task=self.snapshot()['videos'][0]['tasks'][0]
        self.assertEqual(task['note'],note)
        self.assertEqual([m['text'] for m in task['messages']],['想核一下论据'])
        self.assertNotIn('peer',task['messages'][0])
        self.assertNotIn('account_scope',task['messages'][0])
        self.queue.update(item,task='改后的问题')
        task=self.snapshot()['videos'][0]['tasks'][0]
        self.assertEqual(task['note']['kind'],'unclassified')
        self.assertIsNone(task['note']['request'])
        self.assertEqual(task['messages'][0]['text'],'想核一下论据')

    def test_direct_answer_is_a_result_without_a_note_file(self):
        item=self.item(task='这个推断成立吗？')
        self.catalog.build()
        saved=self.queue.record_result(item,{'summary':'这个推断不成立。','answer':{
            'question':'从一次调用能推出训练决策吗？','text':'不能；演示没有排除宿主注入与检索。',
            'status':'answered','limitations':'未复现实验。'},'catalog':{'format':'直接答复'}},complete=True)
        self.assertEqual(saved['state'],'done')
        task=self.snapshot()['videos'][0]['tasks'][0]
        self.assertEqual(task['delivery']['formats'],['直接答复'])
        self.assertTrue(task['delivery']['matches_target'])
        self.assertEqual(task['results'][0]['artifacts'],[])
        self.assertIn('不能',task['results'][0]['answer']['text'])
        self.assertFalse(task['results'][0]['full_video_verified'])
        match=self.queue.search('宿主注入')
        self.assertEqual(match['items'][0]['item_id'],item)
        self.assertIn('answer_text',match['items'][0]['matched_fields'])

    def test_empty_or_partial_answer_cannot_masquerade_as_completed(self):
        item=self.item()
        for answer in ({'question':'问题','text':''},
                       {'question':'问题','text':'仅回答一半','status':'partial'}):
            with self.assertRaises(ReaderError):
                self.queue.record_result(item,{'summary':'答复','answer':answer},complete=True)
        with self.assertRaises(ReaderError):
            self.queue.record_result(item,{'summary':'只有摘要','artifacts':[]},complete=True)
        partial=self.queue.record_result(item,{'summary':'尚有疑点','answer':{
            'question':'问题','text':'尚有一个部分需要核对','status':'partial'}},complete=False)
        self.assertEqual(partial['state'],'pending')

    def test_retention_does_not_replace_the_concrete_work_or_turn_a_comment_into_a_request(self):
        item=self.item(task='这想法不错')
        with self.queue.store.connect() as db:
            self.queue.record_intent(db,item,{'original':'这想法不错','kind':'comment',
                'request':None,'comment':'这想法不错'})
        self.result(item)
        self.catalog.build({'task_metadata':{item:{'retention':'轻量记录',
            'task_goal':'保留项目入口与想法，不扩成实际安装试用。'}}})
        task=self.snapshot()['videos'][0]['tasks'][0]
        self.assertIsNone(task['task_description'])
        self.queue.update(item,task_description='保留项目入口与想法，不扩成实际安装试用。')
        task=self.snapshot()['videos'][0]['tasks'][0]
        self.assertEqual(task['work'],'保留项目入口与想法，不扩成实际安装试用。')
        self.assertEqual(task['note']['comment'],'这想法不错')
        self.assertIsNone(task['note']['request'])
        self.queue.update(item,task='请回答新的具体问题')
        changed=self.snapshot()['videos'][0]['tasks'][0]
        self.assertEqual(changed['work'],'请回答新的具体问题')
        self.assertNotIn('task_goal',changed['metadata'])
        self.result(item,catalog={'task_goal':'针对新问题作判断'})
        current=self.snapshot()['videos'][0]['tasks'][0]
        self.assertEqual(current['work'],'请回答新的具体问题')
        self.assertEqual(current['metadata']['task_goal'],'针对新问题作判断')
        self.queue.update(item,task='另一个工作')
        self.assertEqual(self.snapshot()['videos'][0]['tasks'][0]['work'],'另一个工作')

    def test_manual_task_description_is_bound_independently_to_the_current_request(self):
        item=self.item(task='保存项目入口')
        self.catalog.build({'task_metadata':{item:{'task_description':'只保存项目入口供以后回看',
                                                 'task_goal':'保存入口以便回看'}}})
        self.queue.update(item,task='整理项目的操作笔记')
        changed=self.snapshot()['tasks'][0]
        self.assertNotIn('task_description',changed['metadata'])
        self.assertNotIn('task_goal',changed['metadata'])
        self.catalog.update_metadata(item,{'task_goal':'写出操作步骤'})
        self.assertNotIn('task_description',self.snapshot()['tasks'][0]['metadata'])
        self.catalog.update_metadata(item,{'task_description':'把操作步骤整理为笔记，留待试做'})
        self.assertEqual(self.snapshot()['tasks'][0]['task_description'],
                         '把操作步骤整理为笔记，留待试做')
        self.assertEqual(self.queue.show(item)['state'],'pending')

    def test_result_task_description_expires_when_request_changes_and_obeys_field_precedence(self):
        item=self.item(task='收藏项目')
        self.result(item,catalog={'task_description':'只在本地留下入口'})
        self.catalog.build()
        self.assertEqual(self.snapshot()['tasks'][0]['metadata']['task_description'],'只在本地留下入口')
        self.queue.update(item,state='pending',task='请整理为笔记')
        self.assertNotIn('task_description',self.snapshot()['tasks'][0]['metadata'])
        self.result(item,catalog={'task_description':'写成便于操作的笔记'})
        self.assertEqual(self.snapshot()['tasks'][0]['metadata']['task_description'],'写成便于操作的笔记')
        self.catalog.update_metadata(item,{'task_description':'保留案例上下文，收进casebook'})
        self.assertEqual(self.snapshot()['tasks'][0]['task_description'],'保留案例上下文，收进casebook')
        self.assertEqual(self.snapshot()['tasks'][0]['metadata']['task_description'],'写成便于操作的笔记')
        self.result(item,catalog={'task_description':''})
        self.assertIsNone(self.snapshot()['tasks'][0]['metadata']['task_description'])
        self.assertEqual(self.snapshot()['tasks'][0]['task_description'],'保留案例上下文，收进casebook')
        self.result(item,catalog={'task_description':'仅保存至本地收藏'})
        self.assertEqual(self.snapshot()['tasks'][0]['metadata']['task_description'],'仅保存至本地收藏')
        self.queue.update(item,task='回答是否适用')
        self.assertNotIn('task_description',self.snapshot()['tasks'][0]['metadata'])

    def test_description_history_retains_exact_wording_without_assigning_stale_suggestions(self):
        item=self.item(task='保存项目')
        first='保存至casebook，保留具体想法'
        second='保存到casebook，保留具体想法'
        third='先整理为个人操作参考，再决定保存位置'
        self.catalog.build({'task_metadata':{item:{'task_description':first}}})
        self.catalog.update_metadata(item,{'task_description':second})
        self.result(item,catalog={'task_description':third})
        self.catalog.update_metadata(item,{'task_description':first})
        self.queue.update(item,task='改为回答一个具体问题')
        snapshot=self.snapshot()
        self.assertNotIn('task_description',snapshot['tasks'][0]['metadata'])
        self.assertTrue({first,second,third}.issubset(snapshot['description_history']))
        self.assertEqual(len(snapshot['description_history']),len(set(snapshot['description_history'])))
        self.assertEqual(self.catalog.status()['description_history'],snapshot['description_history'])
        self.assertEqual(read_json(self.catalog.metadata_path)['description_history'],
                         snapshot['description_history'])
        other=self.item(task='一个没有描述的新要求')
        self.assertNotIn('task_description',next(t for t in self.snapshot()['tasks'] if t['id']==other)['metadata'])
        self.catalog.update_metadata(other,{'task_description':' '})
        self.catalog.update_metadata(other,{'task_description':''})
        history=self.snapshot()['description_history']
        self.assertTrue({first,second,third}.issubset(history))
        self.assertFalse(any(not value.strip() for value in history))
        self.assertIsNone(next(t for t in self.snapshot()['tasks'] if t['id']==other)['task_description'])


if __name__=='__main__':
    unittest.main()
