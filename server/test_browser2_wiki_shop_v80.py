#!/usr/bin/env python3
"""Offline transactional test suite, with only synthetic catalog fixtures."""
import concurrent.futures
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from browser2_wiki_shop_v80 import (install,stats,shops,shop,state,buy_demo,ShopError,DEMO_GOLD,audit_native)

class WikiShopV80Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        self.source=root/'offline_wiki.json'
        self.db=root/'wiki_shop_v80_ISOLATED.sqlite3'
        self.source.write_text(json.dumps({'shops':[
            {'id':'armour','npcVnum':9002,'name':'Armour Dealer','role':'shop','entries':[
                {'slot':0,'tabId':'armor','itemVnum':11209,'templateId':'v2_11209','name':'Armor +9','iconId':'11200','count':1,'price':25000,'status':'vnum_confirmable'},
                {'slot':1,'tabId':'armor','itemVnum':None,'templateId':'beta_test','name':'Unknown','iconId':None,'count':1,'price':100,'status':'template_only'},
                {'slot':2,'tabId':'armor','itemVnum':27001,'templateId':'v2_27001','name':'Potion','iconId':'27001','count':10,'price':100000,'status':'vnum_confirmable'}]},
            {'id':'weapons','npcVnum':9001,'name':'Weapon Dealer','entries':[
                {'slot':0,'tabId':'weapons','itemVnum':11209,'count':1,'price':200000,'status':'vnum_confirmable'}]}
        ]},ensure_ascii=False),encoding='utf8')
        install(self.source,self.db)
    def tearDown(self):self.temp.cleanup()
    def test_catalog_is_exact_and_unresolved_preserved(self):
        summary=stats(self.db)
        self.assertEqual((summary['shops'],summary['entries'],summary['buyableDemoEntries'],summary['unresolved']),(2,4,3,1))
        self.assertFalse(summary['nativePurchaseEnabled'])
        self.assertEqual(shop(self.db,9002)['entries'][1]['item_vnum'],None)
    def test_single_purchase_wallet_inventory_ledger(self):
        result=buy_demo(self.db,9002,0,'request-000001')
        self.assertTrue(result['accepted']);self.assertFalse(result['nativeGAMEPurchase'])
        s=state(self.db)
        self.assertEqual(s['gold'],DEMO_GOLD-25000)
        self.assertEqual(s['inventory'][0],{'item_vnum':11209,'purchases':1,'total_items':1})
        self.assertEqual(s['purchases'][0]['paid'],25000)
    def test_duplicate_request_is_idempotent(self):
        first=buy_demo(self.db,9002,0,'request-000001')
        again=buy_demo(self.db,9002,0,'request-000001')
        self.assertFalse(first['idempotent']);self.assertTrue(again['idempotent'])
        self.assertEqual(state(self.db)['gold'],DEMO_GOLD-25000)
        self.assertEqual(len(state(self.db)['purchases']),1)
    def test_duplicate_request_different_slot_rejected(self):
        buy_demo(self.db,9002,0,'request-000001')
        with self.assertRaisesRegex(ShopError,'request_id_reused'):
            buy_demo(self.db,9002,2,'request-000001')
    def test_unverified_item_not_buyable(self):
        original=state(self.db)
        with self.assertRaisesRegex(ShopError,'item_vnum_unresolved'):
            buy_demo(self.db,9002,1,'request-000003')
        self.assertEqual(state(self.db),original)
    def test_insufficient_funds_atomic(self):
        with sqlite3.connect(self.db) as c:c.execute('UPDATE demo_wallet SET gold=1')
        with self.assertRaisesRegex(ShopError,'insufficient_demo_gold'):
            buy_demo(self.db,9002,0,'request-000004')
        self.assertEqual(state(self.db)['gold'],1)
        self.assertFalse(state(self.db)['purchases'])
    def test_multiple_stacks_and_catalog_reload_keeps_purchase(self):
        buy_demo(self.db,9002,2,'request-000005')
        self.assertEqual(state(self.db)['inventory'][0]['total_items'],10)
        install(self.source,self.db)
        self.assertEqual(state(self.db)['inventory'][0]['total_items'],10)
    def test_injection_and_boolean_rejected(self):
        for val in ('9002 OR 1=1',True,-1,0,11_000_000):
            with self.subTest(value=val):
                with self.assertRaises(ShopError):shop(self.db,val)
        with self.assertRaises(ShopError):buy_demo(self.db,9002,0,'invalid id;')
    def test_concurrent_duplicate_requests_only_once(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda _:buy_demo(self.db,9002,0,'same-request-0001'),range(6)))
        self.assertEqual(sum(not x['idempotent'] for x in results),1)
        self.assertEqual(state(self.db)['gold'],DEMO_GOLD-25000)
        self.assertEqual(len(state(self.db)['purchases']),1)
    def test_concurrent_distinct_purchase_atomicity(self):
        with sqlite3.connect(self.db) as c:c.execute('UPDATE demo_wallet SET gold=50000')
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures=[pool.submit(buy_demo,self.db,9002,0,'unique-id-'+str(i).zfill(8)) for i in range(5)]
            accepted=0
            for f in futures:
                try:accepted+=int(f.result()['accepted'])
                except ShopError as e:self.assertEqual(e.code,'insufficient_demo_gold')
        self.assertEqual(accepted,2)
        self.assertEqual(state(self.db)['gold'],0)
        self.assertEqual(len(state(self.db)['purchases']),2)
    def test_native_catalog_reconciliation_read_only(self):
        native_folder=self.db.parent/'native';native_folder.mkdir()
        native_db=native_folder/'player.sqlite3'
        with sqlite3.connect(native_db) as c:
            c.executescript('CREATE TABLE shop(vnum INT,npc_vnum INT);CREATE TABLE shop_item(shop_vnum INT,item_vnum INT,count INT);')
            c.execute('INSERT INTO shop VALUES(7,9002)')
            c.execute('INSERT INTO shop_item VALUES(7,11209,1)')
        before=native_db.read_bytes()
        result=audit_native(self.db,native_folder)
        self.assertEqual(result['state'],'native_shop_source_compared')
        self.assertEqual(next(x for x in result['shops'] if x['npcVnum']==9002)['matchedVnumAndCountRows'],1)
        self.assertEqual(next(x for x in result['shops'] if x['npcVnum']==9002)['wikiRowsNotInNative'],1)
        self.assertFalse(result['purchaseEnabled'])
        self.assertEqual(before,native_db.read_bytes())

    def test_native_database_target_names_forbidden(self):
        for name in ['player.sqlite3','account.sqlite3','common.sqlite3','local.sqlite3']:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ShopError,'target_forbidden'):
                    install(self.source,self.db.parent/name)
    def test_invalid_catalog_fails_and_keeps_prior(self):
        old=stats(self.db)
        raw=json.loads(self.source.read_text());raw['shops'][0]['entries'][0]['price']=-1
        self.source.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ShopError,'invalid_catalog_integer'):
            install(self.source,self.db)
        self.assertEqual(stats(self.db),old)
    def test_import_original_v70_sqlite_fixture_shape(self):
        p=self.db.parent/'source.sqlite3'
        with sqlite3.connect(p) as c:
            c.executescript('''CREATE TABLE wiki_shop(shop_id TEXT,npc_vnum INTEGER,name TEXT,role TEXT);
              CREATE TABLE wiki_entry(shop_id TEXT,slot INTEGER,tab_id TEXT,item_vnum INTEGER,template_id TEXT,name TEXT,icon_id TEXT,item_count INTEGER,price INTEGER,status TEXT);''')
            c.execute('INSERT INTO wiki_shop VALUES(?,?,?,?)',('alchemist',20001,'Alchemist','shop'))
            c.execute('INSERT INTO wiki_entry VALUES (?,?,?,?,?,?,?,?,?,?)',('alchemist',0,'alchemy',100100,'v2_100100','Dragon','100100',1,100000,'vnum_confirmable'))
        r=install(p,self.db)
        self.assertEqual((r['shops'],r['entries']), (1,1))
        self.assertEqual(shop(self.db,20001)['entries'][0]['price'],100000)

if __name__=='__main__':unittest.main(verbosity=2)