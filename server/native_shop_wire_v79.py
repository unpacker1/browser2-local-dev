#!/usr/bin/env python3
"""V79 source-constrained native GAME GC_SHOP decoder; OFFLINE ONLY.

No invented slots, no synthetic live SHOP events, no purchases, no native server alteration.
Decodes only a full genuine unencrypted GC_SHOP frame supplied separately by a trusted
source; this tool never attaches to, proxies, or captures the GAME connection.
"""
from __future__ import annotations
import dataclasses, struct

MAX_PACKET = 16384
SHOP_EVENT_NAMES = {
  0: 'START', 1: 'END', 2: 'UPDATE_ITEM', 3: 'UPDATE_PRICE',
  4: 'OK', 5: 'NOT_ENOUGH_MONEY', 6: 'SOLDOUT', 7: 'INVENTORY_FULL',
  8: 'INVALID_POS', 9: 'SOLD_OUT', 10: 'START_EX', 11: 'NOT_ENOUGH_MONEY_EX'
}

@dataclasses.dataclass(frozen=True)
class ShopABI:
    item_count: int
    item_size: int
    tab_name_size: int | None = None
    tab_items_offset: int | None = None
    tab_struct_size: int | None = None

    def validate(self):
        if not 1 <= self.item_count <= 255: raise ValueError('item_count_invalid')
        if not 10 <= self.item_size <= 160: raise ValueError('item_size_invalid')
        if self.tab_name_size is not None and not 1 <= self.tab_name_size <= 128:
            raise ValueError('tab_name_size_invalid')
        if self.tab_items_offset is not None and (self.tab_name_size is None or self.tab_items_offset < self.tab_name_size + 1):
            raise ValueError('tab_items_offset_invalid')
        if self.tab_struct_size is not None and (self.tab_items_offset is None or self.tab_struct_size < self.tab_items_offset + self.item_count * self.item_size):
            raise ValueError('tab_struct_size_invalid')

def _read_items(data:bytes, abi:ShopABI) -> list[dict]:
    if len(data) != abi.item_count * abi.item_size:raise ValueError('item_array_size_mismatch')
    out=[]
    for idx in range(abi.item_count):
        block=data[idx * abi.item_size : (idx + 1) * abi.item_size]
        vnum,price=struct.unpack_from('<II',block)
        count,display_pos=block[8],block[9]
        if not vnum: continue
        if not (1 <= count <= 255 and 0 <= display_pos < abi.item_count):
            raise ValueError('invalid_native_item_count_or_display_pos')
        out.append({'nativeArrayIndex':idx,'nativeDisplayPos':display_pos,
                    'itemVnum':vnum,'serverPrice':price,'count':count})
    return out

def decode_frame(frame:bytes, abi:ShopABI) -> dict:
    abi.validate()
    if not isinstance(frame,bytes) or len(frame)<4 or frame[0] != 38:
        raise ValueError('not_a_native_gc_shop_frame')
    total=int.from_bytes(frame[1:3],'little')
    if total<4 or total>MAX_PACKET or total != len(frame):
        raise ValueError('native_shop_frame_size_mismatch')
    sub=frame[3]
    if sub not in SHOP_EVENT_NAMES:raise ValueError('unknown_native_shop_subheader')
    data=frame[4:]
    result={'gcHeader':38,'subheader':sub,'event':SHOP_EVENT_NAMES[sub],
            'wireTotalBytes':total,'nativeGAMEPacket':True}
    if sub==0: # TPacketGCShopStart: ownerVID + constant N slots
        if len(data)!=4+abi.item_count*abi.item_size:raise ValueError('native_start_size_mismatch')
        result['ownerVid']=struct.unpack_from('<I',data)[0]
        result['entries']=_read_items(data[4:],abi)
    elif sub==10: # TPacketGCShopStartEx
        if None in (abi.tab_name_size,abi.tab_items_offset,abi.tab_struct_size):
            raise ValueError('native_extended_abi_not_verified')
        if len(data)<5:raise ValueError('native_extended_header_short')
        owner,tab_count=struct.unpack_from('<IB',data)
        if not 1<=tab_count<=12:raise ValueError('native_extended_tab_count_bad')
        if len(data)!=5+tab_count*abi.tab_struct_size:
            raise ValueError('native_extended_frame_size_mismatch')
        tabs=[]
        for t in range(tab_count):
            base=5+t*abi.tab_struct_size
            raw_name=data[base:base+abi.tab_name_size].split(b'\0')[0]
            name=raw_name.decode('cp949',errors='replace')
            coin_type=data[base+abi.tab_name_size]
            offset=base+abi.tab_items_offset
            tabitems=data[offset:offset+abi.item_count*abi.item_size]
            tabs.append({'tabIndex':t,'name':name,'coinType':coin_type,
                         'entries':_read_items(tabitems,abi)})
        result.update(ownerVid=owner,tabs=tabs)
    elif sub==2: # UPDATE_ITEM: pos + original item data
        if len(data)!=1+abi.item_size:raise ValueError('native_update_item_size_mismatch')
        pos=data[0]
        if pos>=abi.item_count:raise ValueError('native_update_item_pos_bad')
        item=struct.unpack_from('<II',data,1)
        result.update(pos=pos,itemVnum=item[0],serverPrice=item[1],count=data[9])
    elif sub==3: # UPDATE_PRICE (int32)
        if len(data)!=4:raise ValueError('native_update_price_size_mismatch')
        result['serverPrice']=struct.unpack_from('<i',data)[0]
    elif data:
        raise ValueError('native_status_or_end_has_unexpected_payload')
    return result

def selftest():
    a=ShopABI(item_count=45,item_size=52)
    blank=bytearray(45*52)
    struct.pack_into('<II',blank,2*52,11209,15000)
    blank[2*52+8]=1;blank[2*52+9]=5
    payload=struct.pack('<I',777)+blank
    f=bytes([38])+struct.pack('<H',4+len(payload))+bytes([0])+payload
    got=decode_frame(f,a)
    assert got['ownerVid']==777 and got['entries']==[{'nativeArrayIndex':2,'nativeDisplayPos':5,'itemVnum':11209,'serverPrice':15000,'count':1}]
    for bad in (f[:-1], b'\x25'+f[1:], f[:1]+b'\x00\x00'+f[3:]):
        try:decode_frame(bad,a)
        except ValueError:pass
        else:raise AssertionError('malformed frame accepted')
    assert decode_frame(b'\x26\x04\x00\x01',a)['event']=='END'
    try:decode_frame(b'\x26\x04\x00\x0a',a)
    except ValueError:pass
    else:raise AssertionError('unsupported START_EX without verified ABI was accepted')
    # Synthetic START_EX with explicitly verified offsets.
    ex=ShopABI(45,52,tab_name_size=16,tab_items_offset=20,tab_struct_size=20+45*52)
    tab=bytearray(ex.tab_struct_size);tab[:5]=b'Armor';tab[16]=0;tab[20:]=blank
    body=struct.pack('<IB',444,1)+tab
    ex_frame=bytes([38])+struct.pack('<H',4+len(body))+bytes([10])+body
    got2=decode_frame(ex_frame,ex)
    assert got2['tabs'][0]['entries'][0]['itemVnum']==11209
    print('[V79 SELFTEST] Native GC_SHOP source-constrained START/START_EX/END validation OK (synthetic packets only)')

if __name__=='__main__':selftest()
