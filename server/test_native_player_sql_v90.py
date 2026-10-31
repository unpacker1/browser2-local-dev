import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_player_sql_v90 import player_state, BAG_CAPACITY
from patch_native_player_v90 import transform, MARKER

class NativeSqlProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        with sqlite3.connect(self.folder/'account.sqlite3') as c:
            c.execute('CREATE TABLE account(id INTEGER PRIMARY KEY, login TEXT UNIQUE)')
            c.execute('INSERT INTO account(id,login) VALUES (13,"zzqauser"),(14,"anotheruser")')
        with sqlite3.connect(self.folder/'player.sqlite3') as c:
            c.execute('CREATE TABLE player(id INTEGER PRIMARY KEY,account_id INTEGER,gold INTEGER)')
            c.execute('INSERT INTO player VALUES (101,13,123456),(102,14,98765)')
            c.execute('CREATE TABLE item(id INTEGER PRIMARY KEY,owner_id INTEGER,vnum INTEGER,count INTEGER,window INTEGER,pos INTEGER)')
            c.executemany('INSERT INTO item VALUES (?,?,?,?,?,?)',[
                (1,101,20,1,1,0),(2,101,27001,200,1,20),
                (3,101,14000,1,2,0),(4,102,77777,11,1,0)])
    def state(self,login='zzqauser',pid=101):
        return player_state(self.folder,login,pid)
    def test_owner_gold_and_bag(self):
        st=self.state()
        self.assertEqual(st['status'],'sql_inventory_snapshot')
        self.assertEqual(st['gold'],123456)
        self.assertEqual(st['itemCount'],2)
        self.assertEqual(st['unmappedWindowRows'],1)
        self.assertEqual(len(st['bag']),BAG_CAPACITY)
        self.assertEqual(st['bag'][0],{'uid':'1','templateId':'v2_20','quantity':1})
        self.assertEqual(st['bag'][20],{'uid':'2','templateId':'v2_27001','quantity':200})
        self.assertNotIn('v2_77777',str(st['bag']))
        self.assertIsNone(st['bag'][1])
    def test_identity_rejects_other_accounts(self):
        for args in [('zzqauser',102),('anotheruser',101),('missinguser',101)]:
            st=self.state(*args)
            self.assertIsNone(st['gold']);self.assertIsNone(st['bag'])
    def test_unchanged_source_database(self):
        before=(self.folder/'player.sqlite3').read_bytes()
        self.state()
        self.assertEqual((self.folder/'player.sqlite3').read_bytes(),before)
    def test_no_item_table_no_invented_empty_bag(self):
        with sqlite3.connect(self.folder/'player.sqlite3') as db:
            db.execute('DROP TABLE item')
        st=self.state()
        self.assertEqual(st['status'],'item_schema_unverified')
        self.assertIsNone(st['bag'])
        self.assertEqual(st['gold'],123456)
    def test_collision_fails_closed(self):
        with sqlite3.connect(self.folder/'player.sqlite3') as db:
            db.execute('INSERT INTO item VALUES (99,101,3020,1,1,0)')
        st=self.state()
        self.assertEqual(st['status'],'bag_position_invalid')
        self.assertIsNone(st['bag'])
    def test_other_windows_not_claimed(self):
        with sqlite3.connect(self.folder/'player.sqlite3') as db:
            db.execute('UPDATE item SET window=9 WHERE id=2')
        st=self.state()
        self.assertEqual(st['itemCount'],1)
        self.assertEqual(st['unmappedWindowRows'],2)
        self.assertIsNone(st['bag'][20])
    def test_bad_counts_and_pos(self):
        with sqlite3.connect(self.folder/'player.sqlite3') as db:
            db.execute('UPDATE item SET count=0 WHERE id=1')
        self.assertEqual(self.state()['status'],'item_values_invalid')
        with sqlite3.connect(self.folder/'player.sqlite3') as db:
            db.execute('UPDATE item SET count=1,pos=200 WHERE id=1')
        self.assertEqual(self.state()['status'],'bag_position_invalid')
    def test_no_sensitive_fields(self):
        st=self.state()
        self.assertFalse({'password','email','account_id','login','player_id'} & set(st.keys()))
    def test_isolation_and_source_contract(self):
        bridge_source=Path('/mnt/data/v88/native_v69.py')
        if bridge_source.is_file():
            code=bridge_source.read_text('utf-8')
        else:
            # Synthetic stand-in with the exact source anchors. CI tests
            # AST/source patching even without the user's original game files.
            code=("import original_shop_v88 as originalshop\n"
              "class Demo:\n"
              "    def status(self):\n"
              "        return {\n"
              "                'nativeWorldTransportExceptions':self.metrics['native_ws_uncaught'],'nativeSqlDirectReadOnly':True,\n"
              "        }\n"
              "    def run(self,ws,base,bridge,user,ch,ready,points,handle):\n"
              "        bridge.engine.live(user['login'],user['password'],ch['_slot'])\n"
              "                        ws.send(base.jbytes({'id':ch['id'],'name':ch['name'],'level':int(points.get('level',ch['level'])),\n"
              "                          'skills':[{'id':s['vnum'],'level':s['level']} for s in ready.get('nativeSkills',[]) if type(s.get('vnum'))==int],\n"
              "                          'buffs':[],'gold':max(0,int(points.get('gold',0)))},3))\n"
              "                        # Native inventory packet representation differs; do not invent item IDs.\n"
              "                        ws.send(base.jbytes({'items':[],'equipment':{},'gold':max(0,int(points.get('gold',0)))},4))\n"
              "                        pass\n")

        new=transform(code)
        self.assertIn(MARKER,new)
        self.assertIn('nativeplayer.player_state',new)
        self.assertIn("'bag':sqlstate['bag']",new)
        self.assertNotIn("{'items':[],'equipment':{}",new)
        self.assertEqual(new,transform(new))
    def test_reject_unrecognized_bridge(self):
        with self.assertRaises(ValueError):transform('print("Hello")')

if __name__=='__main__':unittest.main()