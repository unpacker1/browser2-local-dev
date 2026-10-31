import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import native_npc_ui_v87 as m

class NativeNpcV87Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)
        self.folder=self.home/'sqlite';self.folder.mkdir()
        c=sqlite3.connect(self.folder/'player.sqlite3')
        c.execute('CREATE TABLE item_proto (vnum INTEGER PRIMARY KEY, name BLOB, locale_name BLOB)')
        c.execute('INSERT INTO item_proto VALUES (?,?,?)',(20,b'Basic Sword', 'Uzun Kılıç'.encode('cp949','replace')))
        c.execute('INSERT INTO item_proto VALUES (?,?,?)',(27001,b'Potion','Kırmızı İksir'.encode('utf-8')))
        c.commit();c.close()
        self.cat={'state':'source_catalog_verified','shops':[{'shopVnum':1,'name':'Silahci','items':[
            {'itemVnum':20,'count':1},{'itemVnum':99999,'count':3}]}]}
    def test_native_proto_names_and_unknown_vnum(self):
        rows,cmp=m._project(9001,self.cat,self.folder)
        self.assertEqual(rows[0]['items'][0]['vnum'],20)
        self.assertEqual(rows[0]['items'][0]['nameSource'],'native_item_proto')
        self.assertEqual(rows[0]['items'][1]['name'],'')
        self.assertIsNone(rows[0]['items'][0]['wikiPrice'])
        self.assertIsNone(cmp)
    def test_wiki_not_native(self):
        import json
        p=self.home/'storage/downloads';p.mkdir(parents=True)
        (p/'v70_catalog.json').write_text(json.dumps({'shops':[{'npcVnum':9001,'name':'Weapons',
            'entries':[{'itemVnum':20,'name':'Wiki long sword','price':400,'count':1},
                       {'itemVnum':3009,'name':'Wiki Glaive','price':25000,'count':1}]}]}),encoding='utf-8')
        with patch.object(m.Path,'home',return_value=self.home):
            rows,cmp=m._project(9001,self.cat,self.folder)
        self.assertEqual(rows[0]['items'][0]['wikiPrice'],400)
        self.assertEqual(rows[0]['items'][0]['nameSource'],'native_item_proto')
        self.assertEqual(cmp['nativeMatchingVnums'],1)
        self.assertEqual([a['vnum'] for a in cmp['wikiOnly']],[3009])
        self.assertFalse(rows[0]['items'][0]['priceFromGame'])
    def test_cp949_script_question_format(self):
        txt="[QUESTION 1;I want to upgrade something. |2;Manufacture the Scroll of War |3;Producing Dragon Scroll |4;Produce a Blacksmith' Handbook |5;Close]"
        self.assertEqual(len(m._quest_choices(txt)),5)
        self.assertEqual(m._quest_choices(txt)[0]['label'],'I want to upgrade something.')
    def test_script_session_scope(self):
        bridge=SimpleNamespace(runtime=self.home)
        m.attach(bridge)
        m.clicked(bridge,'playerA',20016)
        x='[QUESTION 1;Upgrade |2;Close]'
        self.assertTrue(m.script(bridge,'playerA',20016,{'originalScriptBytesHex':x.encode('cp949').hex()}))
        self.assertFalse(m.snapshot(bridge,'playerB')['questChoices'])
        self.assertEqual(len(m.snapshot(bridge,'playerA')['questChoices']),2)
        self.assertFalse(m.snapshot(bridge,'playerA')['questAnswerEnabled'])
    def test_no_shop_for_blacksmith(self):
        b=SimpleNamespace(runtime=self.home)
        m.attach(b)
        m.clicked(b,'playerA',20016,{'state':'no_shop_for_clicked_npc','shops':[]})
        v=m.snapshot(b,'playerA')
        self.assertEqual(v['shops'],[])
        self.assertFalse(v['purchaseEnabled'])
    def test_no_sql_modifications(self):
        c=sqlite3.connect(self.folder/'player.sqlite3');n=c.execute('SELECT count(*) FROM item_proto').fetchone()[0];c.close()
        m._proto_names(self.folder,[20,27001])
        c=sqlite3.connect(self.folder/'player.sqlite3');self.assertEqual(n,c.execute('SELECT count(*) FROM item_proto').fetchone()[0]);c.close()

if __name__=='__main__':unittest.main()