import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from video_reader.host_runtime import HostError,host_environment


class HostTransportTests(unittest.TestCase):
    def test_quota_category_preserves_existing_pause_terms_without_log_path_matching(self):
        with tempfile.TemporaryDirectory() as directory:
            missing=Path(directory)/'quota-429'/'missing.log'
            for message in ('usage limit reached','rate limit reached','model quota exceeded',
                            'insufficient credits','HTTP 429'):
                with self.subTest(message=message):
                    self.assertEqual(HostError(message,missing).category,'host_quota')
            self.assertEqual(HostError('Task host failed',missing).category,'host_failed')
            self.assertEqual(HostError('Task host timed out',missing,timeout=True).category,'host_timeout')

    def test_diagnostic_quota_is_classified_before_transport_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            log=Path(directory)/'host.log'
            log.write_text(json.dumps({'type':'turn.failed','error':{'message':'connection rejected: usage limit reached'}}),encoding='utf-8')
            error=HostError('Task host failed',log)
            self.assertEqual(error.category,'host_quota')
            self.assertIn('connection rejected',str(error))

    def test_windows_system_proxy_reaches_child_environment_without_mutating_parent(self):
        with patch.dict(os.environ,{'NO_PROXY':'localhost,127.0.0.1','KEEP':'unchanged'},clear=True), \
                patch('video_reader.host_runtime.os.name','nt'), \
                patch('urllib.request.getproxies_registry',create=True,return_value={
                    'http':'http://127.0.0.1:12345','https':'http://127.0.0.1:12345','ftp':'http://ignored'}):
            child=host_environment()
            self.assertEqual(child['HTTPS_PROXY'],'http://127.0.0.1:12345')
            self.assertEqual(child['HTTP_PROXY'],'http://127.0.0.1:12345')
            self.assertEqual(child['NO_PROXY'],'localhost,127.0.0.1')
            self.assertEqual(child['KEEP'],'unchanged')
            self.assertNotIn('FTP_PROXY',child)
            self.assertNotIn('HTTPS_PROXY',os.environ)

    def test_explicit_proxy_including_empty_values_is_preserved(self):
        for name,value in (('HTTPS_PROXY','http://explicit:1234'),('http_proxy',''),('ALL_PROXY','socks5://explicit:1080')):
            with self.subTest(name=name),patch.dict(os.environ,{name:value},clear=True), \
                    patch('video_reader.host_runtime.os.name','nt'), \
                    patch('urllib.request.getproxies_registry',create=True) as registry:
                self.assertEqual({key.lower():value for key,value in host_environment().items()},{name.lower():value})
                registry.assert_not_called()

    def test_no_system_proxy_leaves_environment_unchanged(self):
        with patch.dict(os.environ,{'KEEP':'unchanged'},clear=True), \
                patch('video_reader.host_runtime.os.name','nt'), \
                patch('urllib.request.getproxies_registry',create=True,return_value={}):
            self.assertEqual(host_environment(),{'KEEP':'unchanged'})

    def test_non_windows_never_reads_registry(self):
        with patch.dict(os.environ,{'KEEP':'unchanged'},clear=True), \
                patch('video_reader.host_runtime.os.name','posix'), \
                patch('urllib.request.getproxies_registry',create=True) as registry:
            self.assertEqual(host_environment(),{'KEEP':'unchanged'})
            registry.assert_not_called()

    def test_workspace_route_failure_is_transport_failure_not_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            log=Path(directory)/'host.log'
            log.write_text(json.dumps({'type':'turn.failed','error':{'message':'workspace routing discovery failed'}}),encoding='utf-8')
            error=HostError('Task host failed',log)
            self.assertEqual(error.category,'host_transport')
            self.assertIn('workspace routing discovery failed',str(error))
