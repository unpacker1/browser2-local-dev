import ast,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from patch_shop_template_v89 import patch,BEFORE,AFTER,CHECK_BEFORE,CHECK_AFTER,MARKER

# Synthetic exact V88 source anchors: no private client files committed.
SOURCE="""from __future__ import annotations
import json
def push(m,d):return bytes([9])+json.dumps({'m':m,'d':d}).encode()
def project(npc,cat):
    entries=[]
    for i,item in enumerate(cat['items']):
        vnum=item['itemVnum'];count=item['count']
        entries.append({'slot':i,'templateId':vnum,'count':count,'price':0})
    rows=[{'slot':i,'state':'locked','price':0} for i in range(len(entries))]
    return [{'id':'shop','entries':entries}], {'shopId':'shop','view':{'shopId':'shop','rows':rows}}
def frames(npc,cat):
    shops,view=project(npc,cat)
    return push('shop_catalog',shops),push('open_shop',view)
def validate_client_contract(catalog_frame,open_frame):
    catalog=json.loads(catalog_frame[1:]);op=json.loads(open_frame[1:])
    found=catalog['d'][0];rows=op['d']['view']['rows']
    if any(r.get('state')=='buyable' for r in rows):return False
    return all(type(x.get('templateId')) is int for x in found['entries'])
"""

class OriginalV28TemplateIds(unittest.TestCase):
    def test_replacement_only(self):
        text=patch(SOURCE)
        self.assertEqual(text.count(AFTER),1)
        self.assertEqual(text.count(CHECK_AFTER),1)
        self.assertNotIn(BEFORE,text)
        self.assertNotIn(CHECK_BEFORE,text)
    def test_original_wire_and_item_ids(self):
        ns={}
        exec(compile(patch(SOURCE),'test_v89','exec'),ns)
        catalog,opened=ns['frames'](9001,{'items':[{'itemVnum':20,'count':1},{'itemVnum':27001,'count':5}]})
        self.assertEqual(catalog[:1],b'\\x09')
        self.assertEqual([json.loads(x[1:])['m'] for x in (catalog,opened)],['shop_catalog','open_shop'])
        self.assertEqual([x['templateId'] for x in json.loads(catalog[1:])['d'][0]['entries']],['v2_20','v2_27001'])
        self.assertTrue(ns['validate_client_contract'](catalog,opened))
    def test_locked(self):
        ns={}
        exec(compile(patch(SOURCE),'test_v89','exec'),ns)
        _,opened=ns['frames'](9001,{'items':[{'itemVnum':20,'count':1}]})
        self.assertEqual(json.loads(opened[1:])['d']['view']['rows'][0]['state'],'locked')
    def test_reject_unknown(self):
        with self.assertRaises(ValueError):patch(SOURCE.replace(BEFORE,'print(vnum)'))
    def test_idempotent(self):
        a=patch(SOURCE);self.assertEqual(patch(a),a)
    def test_compiles_and_source_unchanged(self):
        self.assertIn(MARKER,patch(SOURCE))
        ast.parse(patch(SOURCE))
        self.assertNotIn('sqlite3.connect',patch(SOURCE))
        self.assertEqual(SOURCE.count(BEFORE),1)

if __name__=='__main__':unittest.main()
