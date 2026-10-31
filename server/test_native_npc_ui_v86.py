import unittest
from unittest.mock import patch
from types import SimpleNamespace
import threading
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent))
import native_npc_ui_v86 as n
from patch_native_ui_v86 import transform

class NativeNpcV86Tests(unittest.TestCase):
    def setUp(self):
        self.b=SimpleNamespace()
        n.attach(self.b)
    def test_click_shows_real_sql_ids_and_count(self):
        c={'state':'source_catalog_verified','shops':[{'shopVnum':22,'name':'Smith','items':[{'itemVnum':19,'count':2},{'itemVnum':33,'count':1}]}]}
        with patch.object(n,'_wiki_index',return_value={}):
            n.clicked(self.b,'tester',9001)
            n.clicked(self.b,'tester',9001,c)
        result=n.snapshot(self.b,'tester')
        self.assertEqual(result['npcVnum'],9001)
        self.assertEqual(result['shops'][0]['items'][0]['vnum'],19)
        self.assertFalse(result['purchaseEnabled'])
        self.assertFalse(result['liveShopPacketDecoded'])
    def test_auth_login_isolation(self):
        n.clicked(self.b,'account_a',9003)
        self.assertEqual(n.snapshot(self.b,'account_b')['seq'],0)
        self.assertNotEqual(n.snapshot(self.b,'account_a')['seq'],0)
    def test_each_click_reopens_even_same_npc(self):
        n.clicked(self.b,'a',9003);first=n.snapshot(self.b,'a')['seq']
        n.clicked(self.b,'a',9003);self.assertGreater(n.snapshot(self.b,'a')['seq'],first)
    def test_script_cp949_literal_text(self):
        n.clicked(self.b,'a',9003)
        s='Merhaba esnaf! [NEXT] <script>alert(1)</script>'
        self.assertTrue(n.script(self.b,'a',9003,{'originalScriptBytesHex':s.encode('cp949').hex()}))
        self.assertIn('<script>',n.snapshot(self.b,'a')['script'])
        self.assertIn('textContent',n.PLAY_EXTRA)
        self.assertNotIn('innerHTML',n.PLAY_EXTRA)
    def test_script_not_cross_npc_or_user(self):
        n.clicked(self.b,'a',9003)
        self.assertFalse(n.script(self.b,'a',9004,{'originalScriptBytesHex':'6162'}))
        self.assertFalse(n.script(self.b,'b',9003,{'originalScriptBytesHex':'6162'}))
    def test_shop_sanitizes_bad_and_excess(self):
        cat={'state':'source_catalog_verified','shops':[{'shopVnum':1,'name':'ok','items':[{'itemVnum':3,'count':1}, {'itemVnum':-3,'count':1},{'itemVnum':2,'count':'1'}]}]}
        with patch.object(n,'_wiki_index',return_value={}):n.clicked(self.b,'a',9003,cat)
        self.assertEqual(len(n.snapshot(self.b,'a')['shops'][0]['items']),1)
    def test_fail_closed_without_v85_source(self):
        with self.assertRaises(ValueError):transform('def status(self): pass')
    def test_patch_preserves_js_assets_and_native_binary(self):
        sample="# V85: undefined V80 preview is optional\nfrom pathlib import Path\nclass NativeBridge:\n    def status(self): return {}\n    def world_loop(self,ws):\n        last_clicked_npc_at=now\n        bridge.metrics['native_shop_catalog_after_verified_click']+=1\n        bridge.metrics['native_npc_scripts_received']+=1\n\ndef start_server():\n    bridge=NativeBridge(engine,root)\n    x=PLAY_HTML.replace('__ORIGINAL_AUTH_MODULE__','/assets/'+auth_module).encode('utf-8')\n    if True:\n        if True:\n            if True:\n                if p=='/__native__/status':return self.json(200,bridge.status())\n"
        result,status=transform(sample)
        self.assertEqual(status,'patched')
        self.assertEqual(result.count('npcui.clicked('),2)
        self.assertEqual(result.count('npcui.script('),1)
        self.assertIn("'/__native__/npc-ui'",result)
        self.assertIn('return self.json(200,npcui.snapshot',result)
        self.assertNotIn('CG_SHOP',result)
        self.assertEqual(transform(result)[1],'already_installed')

if __name__=='__main__':unittest.main()