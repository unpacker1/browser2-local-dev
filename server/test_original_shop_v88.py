import os,sys,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import original_shop_v88 as m
import patch_v88_original_window as p

CAT={'state':'source_catalog_verified','npcVnum':9001,'purchaseEnabled':False,
     'liveShopPacketDecoded':False,'source':'native_player_sqlite_readonly',
     'shops':[{'shopVnum':1,'name':'Weapons','items':[
         {'itemVnum':20,'count':1},{'itemVnum':27001,'count':5}]}]}
class OriginalV28ContractTests(unittest.TestCase):
    def test_exact_tag_and_original_event_names(self):
        frames=m.frames(9001,CAT);self.assertEqual(len(frames),2)
        self.assertEqual(frames[0][0],9);self.assertEqual(frames[1][0],9)
        msg=[json.loads(f[1:]) for f in frames]
        self.assertEqual([x['m'] for x in msg],['shop_catalog','open_shop'])
        self.assertIsInstance(msg[0]['d'],list)
        self.assertEqual(msg[1]['d']['shopId'],msg[0]['d'][0]['id'])
        self.assertEqual(msg[1]['d']['view']['shopId'],msg[1]['d']['shopId'])
    def test_no_game_price_no_buyable_rows(self):
        a,b=m.frames(9001,CAT)
        self.assertTrue(m.validate_client_contract(a,b))
        self.assertEqual(json.loads(a[1:])['d'][0]['entries'][1],{'slot':1,'templateId':27001,'count':5,'price':0})
        self.assertTrue(all(x['state']=='locked' for x in json.loads(b[1:])['d']['view']['rows']))
    def test_unverified_and_wrong_npc_fail_closed(self):
        self.assertEqual(m.frames(9002,CAT),())
        for state in ('no_shop_for_clicked_npc','native_shop_sql_read_failed'):
            self.assertEqual(m.frames(9001,{**CAT,'state':state}),())
        self.assertEqual(m.frames(9001,{**CAT,'purchaseEnabled':True}),())
        self.assertEqual(m.frames(9001,{**CAT,'liveShopPacketDecoded':True}),())
    def test_reject_malformed_native_rows(self):
        for bad in (0,-1,'27001',1e99):
            self.assertEqual(m.frames(9001,{**CAT,'shops':[{'shopVnum':1,'items':[{'itemVnum':bad,'count':1}]}]}),())
    def test_tab_split_for_many_items(self):
        cat={**CAT,'shops':[{'shopVnum':2,'items':[{'itemVnum':i+10,'count':1} for i in range(101)]}]}
        a,b=m.frames(9001,cat);items=json.loads(a[1:])['d'][0];self.assertEqual(len(items['tabs']),3)
        self.assertEqual([x['slot'] for x in items['entries']],list(range(101)))
        self.assertEqual(len(json.loads(b[1:])['d']['view']['rows']),101)
    def test_no_synthetic_quest_answer_or_purchase(self):
        src=Path(m.__file__).read_text()
        self.assertNotIn('UPDATE player',src)
        self.assertNotIn('proc.stdin',src)
        self.assertNotIn('buyFromShop',src)
    def test_patch_rejects_unrelated_source(self):
        with self.assertRaises(ValueError):p.transform('print("foo")\n')
    def test_patch_removes_only_html_inject_and_adds_native_push(self):
        src=(p.PREV+'\n'+'# V85: undefined V80 preview is optional\n'
             'import native_npc_ui_v86 as npcui\n'
             "a=PLAY_HTML.replace('__ORIGINAL_AUTH_MODULE__','/assets/'+auth_module).replace('</html>',npcui.PLAY_EXTRA+'</html>').encode('utf-8')\n"
             'def dummy():\n'
             '    '+p.CATALOG_CALL+'\n')
        got=p.transform(src)
        self.assertIn('import original_shop_v88 as originalshop',got)
        self.assertNotIn('npcui.PLAY_EXTRA',got)
        self.assertIn('originalshop.frames(last_clicked_npc_vnum,bridge.native_shop_last)',got)
        self.assertEqual(got,p.transform(got))
if __name__=='__main__':unittest.main()