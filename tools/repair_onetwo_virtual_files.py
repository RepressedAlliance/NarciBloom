"""Stage the actual Chinese patch modules outside Enigma's virtual file layer."""
import json
import re
import shutil
import struct
from build_font_settings import *

unpacked=TOOLS/'unpacked-onetwo'
repair=TOOLS/'repair-onetwo'
assert unpacked.is_dir()
repair.mkdir(exist_ok=True)
for source in unpacked.rglob('*'):
    if source.is_file():
        target=repair/source.relative_to(unpacked)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)

original=(unpacked/'#mjo/pausemenu.mjo').read_bytes()
patched,hooks,functions,hashes=patch_pause(original)
translated=(unpacked/'#txt/pausemenu.txt').read_text(encoding='utf-16').splitlines()
assert translated[8]=='字体设置'
translated[8]='字体 / 字号'
base=Script(original)
old_nonascii=[i for i in base.ins if i.name=='ldstr' and any(c>=128 for c in i.fields['s'])]
assert len(old_nonascii)==len(translated)
added=[i.fields['s'].rstrip(b'\0').decode('gbk') for i in Script(patched).ins
       if i.offset>=len(base.code) and i.name=='ldstr' and any(c>=128 for c in i.fields['s'])]
# The Chinese DLL recognizes Shift-JIS source strings and substitutes UTF-16
# translations. GBK source literals are not valid markers for that loader.
prepared=Script(patched)
for old in base.ins:
    if old.name=='ldstr' and old.fields['s'].rstrip(b'\0')=='フォント設定'.encode('cp932'):
        prepared.code[old.offset:old.offset+len(old.raw)]=old.raw
for item in prepared.ins:
    if item.offset>=len(base.code) and item.name=='ldstr' and any(c>=128 for c in item.fields['s']):
        marker='設定'.encode('cp932')
        assert len(marker)<len(item.fields['s'])
        raw=marker.ljust(len(item.fields['s'])-1,b' ')+b'\0'
        prepared.code[item.offset+4:item.offset+len(item.raw)]=raw
patched=prepared.finish()
(repair/'#mjo/pausemenu.mjo').write_bytes(patched)
translated.extend(added)
assert len(translated)==sum(i.name=='ldstr' and any(c>=128 for c in i.fields['s']) for i in Script(patched).ins)
(repair/'#txt/pausemenu.txt').write_text('\r\n'.join(translated)+'\r\n',encoding='utf-16',newline='')

console,rects=patch_console_bounded((unpacked/'#mjo/console.mjo').read_bytes())
(repair/'#mjo/console.mjo').write_bytes(console)
override={name:record[2] for name,record in entries((OUT/'narci_onetwo/update12.arc').read_bytes()).items()}
override.pop('pausemenu.mjo')
override.pop('console.mjo')
(repair/'update12.arc').write_bytes(archive(override))

# These are UTF-16 dialog resources. Pad with spaces to keep each template and
# its following controls at their original offsets. Narrow sample text is ASCII
# so it remains legible under either Shift-JIS or GBK conversion hooks.
exe=bytearray((unpacked/'narci_onetwo.exe').read_bytes())
changes=[]
mapping={'フォント選択':'Font','フォント名':'Font','ｷｬﾝｾﾙ':'Back','OK':'OK',
         'スピード設定':'Speed','サウンド設定':'Sound','スクリーン詳細設定':'Display',
         'コンフィグレーション':'Settings','初期化':'Def','画面効果':'FX','文字表示':'Text',
         '高速':'Hi','低速':'Lo','オートモード':'Auto','最小':'Lo','最大':'Hi',
         '音声':'VO','音楽':'BG','効果音':'SE','全画面モード':'Full',
         '常に手前に表示':'On top'}
pe=struct.unpack_from('<I',exe,0x3c)[0]
count=struct.unpack_from('<H',exe,pe+6)[0]
optional=struct.unpack_from('<H',exe,pe+20)[0]
resources=None
for index in range(count):
    off=pe+24+optional+index*40
    name,vs,va,rs,raw=struct.unpack_from('<8sIIII',exe,off)
    if name.rstrip(b'\0')==b'.rsrc':resources=(raw,raw+rs)
assert resources
lo,hi=resources
for old,new in mapping.items():
    assert len(new)<=len(old)
    needle=old.encode('utf-16le')+b'\0\0'
    replacement=new.ljust(len(old)).encode('utf-16le')+b'\0\0'
    for match in list(re.finditer(re.escape(needle),bytes(exe[lo:hi]))):
        pos=lo+match.start()
        assert pos%2==0
        exe[pos:pos+len(needle)]=replacement
        changes.append({'resource':old,'translation':new,'offset':pos})
for old,new in [('文字サンプルです。１２３４','Font preview 1234 ABCD'),('\u3000'*30,' '*60)]:
    needle=old.encode('cp932')+b'\0';replacement=new.encode('ascii')+b'\0'
    assert len(replacement)<=len(needle)
    locations=[m.start() for m in re.finditer(re.escape(needle),bytes(exe))]
    assert len(locations)==1,(old,locations)
    pos=locations[0]
    exe[pos:pos+len(needle)]=new.encode('ascii').ljust(len(needle)-1,b' ')+b'\0'
    changes.append({'sample':old,'offset':pos})
assert len(exe)==(unpacked/'narci_onetwo.exe').stat().st_size
(repair/'narci_onetwo.exe').write_bytes(exe)
# Both original translation DLLs replace lpWindowName on every CreateWindowExA
# call, including child buttons and labels. Skip that assignment while keeping
# the forwarding call and its relocatable operand intact.
import sys
import pefile
title_hooks=[]
for dll,rva,expected in [('Narcissu_cn.dll',0x5113,bytes.fromhex('c7451068630310')),
                         ('FontPatch.dll',0x1443,bytes.fromhex('c745104c3d0110'))]:
    path=repair/dll
    data=bytearray(path.read_bytes())
    image=pefile.PE(data=data)
    offset=image.get_offset_from_rva(rva)
    assert data[offset:offset+7]==expected
    data[offset:offset+2]=b'\xeb\x05'
    path.write_bytes(data)
    title_hooks.append({'dll':dll,'rva':rva,'change':'preserve original window/control caption'})
from check_font_settings import check_vm
check_vm(functions,hashes)
report={'source':'original Chinese patch virtual files','added_menu_translations':added,
        'menu_hooks':hooks,'dialog_resource_changes':changes,'caption_hooks':title_hooks,'console_regions':rects,
        'menu_logic_checks':'passed','source_files':[str(p.relative_to(repair)) for p in repair.rglob('*') if p.is_file()]}
(TOOLS/'repair-onetwo-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'staged_files':len(report['source_files']),'menu_translations':len(translated),
                  'dialog_changes':len(changes),'menu_logic_checks':'passed'},ensure_ascii=False))
