#!/usr/bin/env python3
import csv, html, io, json, os, re, sys, uuid, zipfile
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

OUT = Path('Torah_Hebrew_Metsudah_Eli_Spiro.epub')
REPORT = Path('torah_build_report.txt')
MAM_REPO = 'bdenckla/MAM-for-Sefaria'
MAM_REV = '5f41c16c4737e1b1fddb2e76a88deae272be5b5a'
MET_REPO = 'Orthodox-Union/ShnayimMikrah-Files'
MET_REV = 'c6f1a1fb9ec56f86a829cd87e447b14c15b593d5'
HEBCAL_REPO = 'hebcal/hebcal-leyning'
HEBCAL_REV = 'e6768f6cdd3d8d738315e88baf05b5c23adb3fc9'

BOOKS = [
    ('Genesis', 'בראשית'),
    ('Exodus', 'שמות'),
    ('Leviticus', 'ויקרא'),
    ('Numbers', 'במדבר'),
    ('Deuteronomy', 'דברים'),
]
HE_PARSHIOT = [
'בראשית','נח','לך־לך','וירא','חיי שרה','תולדות','ויצא','וישלח','וישב','מקץ','ויגש','ויחי',
'שמות','וארא','בא','בשלח','יתרו','משפטים','תרומה','תצוה','כי תשא','ויקהל','פקודי',
'ויקרא','צו','שמיני','תזריע','מצורע','אחרי מות','קדושים','אמור','בהר','בחקתי',
'במדבר','נשא','בהעלותך','שלח','קרח','חקת','בלק','פינחס','מטות','מסעי',
'דברים','ואתחנן','עקב','ראה','שופטים','כי תצא','כי תבוא','נצבים','וילך','האזינו','וזאת הברכה'
]
HE_ALIYOT = ['ראשון','שני','שלישי','רביעי','חמישי','שישי','שביעי']
EN_ALIYOT = ['First','Second','Third','Fourth','Fifth','Sixth','Seventh']


def raw_url(repo, rev, path):
    return f'https://raw.githubusercontent.com/{repo}/{rev}/{quote(path, safe="/")}'

def download_text(url):
    req = Request(url, headers={'User-Agent': 'Torah-EPUB-builder/1.0'})
    with urlopen(req, timeout=90) as r:
        return r.read().decode('utf-8-sig')

def parse_ref(s):
    m = re.fullmatch(r'(\d+):(\d+)', s.strip())
    if not m:
        raise ValueError(f'Bad chapter:verse ref: {s!r}')
    return int(m.group(1)), int(m.group(2))

def he_num(n):
    if n <= 0:
        return str(n)
    vals = [(400,'ת'),(300,'ש'),(200,'ר'),(100,'ק'),(90,'צ'),(80,'פ'),(70,'ע'),(60,'ס'),(50,'נ'),(40,'מ'),(30,'ל'),(20,'כ')]
    if n == 15: letters='טו'
    elif n == 16: letters='טז'
    else:
        letters=''
        x=n
        for v,ch in vals:
            while x >= v:
                letters += ch; x -= v
        ones = ['', 'א','ב','ג','ד','ה','ו','ז','ח','ט','י','יא','יב','יג','יד','טו','טז','יז','יח','יט']
        if x: letters += ones[x]
    if len(letters) == 1:
        return letters + '׳'
    return letters[:-1] + '״' + letters[-1]

def break_kind(raw):
    for marker, kind in [('{ש}','shira'),('{פ}','petucha'),('{ר}','linebreak'),('{ס}','setuma')]:
        if marker in raw:
            return kind
    return None

def clean_mam(raw):
    t = re.sub(r'<i\s+class=["\']footnote["\'][^>]*>.*?</i>', '', raw, flags=re.I|re.S)
    t = re.sub(r'<sup[^>]*>.*?</sup>', '', t, flags=re.I|re.S)
    t = re.sub(r'\{[פסרש]\}', '', t)
    t = re.sub(r'<br\s*/?>', ' ', t, flags=re.I)
    t = re.sub(r'<[^>]+>', '', t)
    t = html.unescape(t)
    t = re.sub(r'[ \t\r\n\u00a0]+', ' ', t).strip()
    return t

def clean_en(raw):
    placeholders = {}
    def keep(m):
        key=f'@@TAG{len(placeholders)}@@'; placeholders[key]=m.group(0).lower(); return key
    t = re.sub(r'</?(?:i|em|b|strong)>', keep, raw, flags=re.I)
    t = re.sub(r'<[^>]+>', '', t)
    t = html.unescape(t)
    t = re.sub(r'\s+', ' ', t).strip()
    t = html.escape(t, quote=False)
    for k,v in placeholders.items(): t=t.replace(k,v)
    return t

def load_mam(book):
    url = raw_url(MAM_REPO, MAM_REV, f'csv/{book}.csv')
    text = download_text(url)
    verses = {}
    breaks = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2: continue
        m = re.fullmatch(re.escape(book) + r' (\d+):(\d+)', row[0].strip())
        if not m: continue
        ref=(int(m.group(1)), int(m.group(2)))
        raw=row[1]
        verses[ref]=clean_mam(raw)
        breaks[ref]=break_kind(raw)
    if not verses: raise RuntimeError(f'No MAM verses parsed for {book}')
    return verses, breaks

def load_metsudah(book):
    path=f'Chumash/{book}/English/Metsudah Chumash, Metsudah Publications, 2009.json'
    data=json.loads(download_text(raw_url(MET_REPO, MET_REV, path)))
    if 'Metsudah Chumash' not in data.get('versionTitle',''):
        raise RuntimeError(f'Wrong English version for {book}')
    verses={}
    for ci, chapter in enumerate(data['text'], 1):
        for vi, verse in enumerate(chapter, 1):
            verses[(ci,vi)] = clean_en(verse)
    return verses, data.get('license','unknown')

def xhtml_doc(title, body, lang='en'):
    return f'''<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" lang="{lang}">\n<head><meta charset="utf-8"/><title>{html.escape(title)}</title><link rel="stylesheet" type="text/css" href="../style/torah.css"/></head>\n<body>{body}</body></html>'''

def section_break(kind):
    return {
        'petucha':'<div class="petucha" title="פתוחה"></div>',
        'setuma':'<span class="setuma" title="סתומה">&#160;&#160;&#160;&#160;</span>',
        'linebreak':'<br class="mam-linebreak"/>',
        'shira':'<div class="shira-break"></div>',
    }.get(kind,'')

def render_section(refs, verse_map, break_map, aliyah_starts, maftir_ref, hebrew):
    out=[]
    current_ch=None
    ali_label = dict(zip(aliyah_starts, HE_ALIYOT if hebrew else EN_ALIYOT))
    for ref in refs:
        if ref in ali_label:
            label=ali_label[ref]
            out.append(f'<div class="aliyah">{html.escape(label)}</div>')
        if ref == maftir_ref:
            out.append(f'<div class="maftir">{"מפטיר" if hebrew else "Maftir"}</div>')
        ch, v = ref
        if ch != current_ch:
            current_ch=ch
            lbl=f'פרק {he_num(ch)}' if hebrew else f'Chapter {ch}'
            out.append(f'<div class="chapter">{lbl}</div>')
        vn=he_num(v) if hebrew else str(v)
        out.append(f'<span class="verse"><sup class="vnum">{vn}</sup>&#160;{verse_map[ref]} </span>')
        br=break_map.get(ref)
        if br: out.append(section_break(br))
    return ''.join(out)

def zip_write(zf, name, data, compress=True):
    zf.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED)

def main():
    font_candidates=list(Path('/usr/share/fonts').rglob('NotoSerifHebrew-Regular.ttf'))
    if not font_candidates:
        raise RuntimeError('NotoSerifHebrew-Regular.ttf not found after fonts-noto-core installation')
    font_bytes=font_candidates[0].read_bytes()

    aliyot=json.loads(download_text(raw_url(HEBCAL_REPO, HEBCAL_REV, 'src/aliyot.json')))
    portions=[]
    for name, rec in aliyot.items():
        num=rec.get('num') if isinstance(rec,dict) else None
        fk=rec.get('fullkriyah') if isinstance(rec,dict) else None
        if isinstance(num,int) and 1 <= num <= 54 and isinstance(fk,dict) and all(str(i) in fk for i in range(1,8)):
            portions.append((num,name,rec))
    bynum={}
    for item in portions:
        bynum.setdefault(item[0], item)
    if set(bynum) != set(range(1,55)):
        raise RuntimeError(f'Hebcal annual parsha numbers found: {sorted(bynum)}')
    portions=[bynum[i] for i in range(1,55)]

    he_books={}; en_books={}; br_books={}; en_licenses={}
    for book,_ in BOOKS:
        he_books[book], br_books[book]=load_mam(book)
        en_books[book], en_licenses[book]=load_metsudah(book)
        if set(he_books[book]) != set(en_books[book]):
            missing_en=sorted(set(he_books[book])-set(en_books[book]))[:10]
            missing_he=sorted(set(en_books[book])-set(he_books[book]))[:10]
            raise RuntimeError(f'Verse mismatch {book}; missing EN {missing_en}; missing HE {missing_he}')

    book_by_num={i+1:BOOKS[i][0] for i in range(5)}
    last_end={}
    parsha_data=[]
    for num,name,rec in portions:
        bnum=rec['book']; book=book_by_num[bnum]; fk=rec['fullkriyah']
        starts=[parse_ref(fk[str(i)][0]) for i in range(1,8)]
        end=parse_ref(fk['7'][1])
        start=starts[0]
        m_rng=fk.get('M') or fk.get('m')
        if not m_rng: raise RuntimeError(f'No Maftir for {name}')
        maftir=parse_ref(m_rng[0])
        ordered=sorted(he_books[book])
        idx={r:i for i,r in enumerate(ordered)}
        if start not in idx or end not in idx: raise RuntimeError(f'Bad parsha range {name}: {start}-{end}')
        if idx[start] > idx[end]: raise RuntimeError(f'Reversed parsha range {name}')
        refs=ordered[idx[start]:idx[end]+1]
        for r in starts+[maftir]:
            if r not in set(refs): raise RuntimeError(f'Boundary {r} outside {name}')
        if book in last_end and idx[start] != idx[last_end[book]]+1:
            raise RuntimeError(f'Gap/overlap before {name}: prev {last_end[book]}, start {start}')
        if book not in last_end and idx[start] != 0:
            raise RuntimeError(f'{name} does not begin {book}')
        last_end[book]=end
        parsha_data.append((num,name,book,refs,starts,maftir))
    for book,_ in BOOKS:
        if last_end.get(book) != sorted(he_books[book])[-1]:
            raise RuntimeError(f'Parsha coverage does not reach end of {book}')

    total_verses=sum(len(x) for x in he_books.values())
    total_trope=sum(1 for b in he_books.values() for t in b.values() for c in t if 0x0591 <= ord(c) <= 0x05AF)
    total_niqqud=sum(1 for b in he_books.values() for t in b.values() for c in t if 0x05B0 <= ord(c) <= 0x05BC or ord(c) in (0x05C1,0x05C2,0x05C7))
    if total_trope < 10000 or total_niqqud < 50000:
        raise RuntimeError(f'Unexpectedly low Hebrew marks: trope={total_trope}, niqqud={total_niqqud}')

    css='''@font-face{font-family:"Noto Serif Hebrew";src:url("../fonts/NotoSerifHebrew-Regular.ttf") format("truetype");font-style:normal;font-weight:400;}\nbody{margin:5%;line-height:1.55;}h1,h2{text-align:center;} .titlepage{text-align:center;margin-top:25%;} .subtitle{font-size:1.1em;} .small{font-size:.86em;} .sefer{page-break-before:always;break-before:page;text-align:center;margin-top:28%;} .parsha-title{text-align:center;margin:0 0 1.4em;} .hebrew{direction:rtl;text-align:right;font-family:"Noto Serif Hebrew",serif;font-size:1.20em;line-height:1.95;} .english{direction:ltr;text-align:left;font-family:serif;font-size:1em;line-height:1.58;} .english-start{page-break-before:always;break-before:page;} .aliyah{font-weight:600;text-align:center;margin:1.35em 0 .6em;padding:.25em 0;border-top:1px solid #aaa;border-bottom:1px solid #aaa;} .maftir{font-weight:600;text-align:center;margin:.9em 0 .45em;font-size:.88em;} .chapter{text-align:center;font-size:.72em;letter-spacing:.03em;margin:1.2em 0 .45em;opacity:.72;} .verse{display:inline;} .vnum{font-size:.56em;line-height:0;vertical-align:super;opacity:.62;} .petucha{display:block;height:.8em;clear:both;} .setuma{display:inline-block;min-width:3.3em;} .mam-linebreak{display:block;} .shira-break{display:block;height:1.3em;} .credits p,.howto p{margin:.75em 0;} nav ol{list-style:none;padding-left:1.1em;} nav li{margin:.35em 0;} a{text-decoration:none;color:inherit;}'''

    parsha_by_book={b:[] for b,_ in BOOKS}
    for num,name,book,refs,starts,maftir in parsha_data:
        fn=f'text/parsha-{num:02d}.xhtml'
        parsha_by_book[book].append((num,name,fn))

    title_body='''<div class="titlepage"><h1 dir="rtl" class="hebrew">תורה</h1><h1>Torah</h1><p class="subtitle">Hebrew with Metsudah English</p><p class="small">Compiled and created by Eli Spiro using ChatGPT.</p></div>'''
    howto_body='''<div class="howto"><h1>How to Use This Book</h1><p>Each weekly parsha begins with the entire Hebrew reading, followed by the entire Metsudah English translation.</p><p>Aliyah headings appear in both sections. The Maftir starting point is marked without repeating the verses.</p><p>The Hebrew retains niqqud, ta’amei hamikra, and the Torah’s פתוחה/סתומה section divisions in a Kindle-friendly reflow format. Additional MAM line/song breaks are retained where present. Verse and chapter markers are included unobtrusively for reference.</p><p>This edition is designed for convenient Torah reading and study. It does not make a claim about the halachic requirements of shnayim mikra v’echad targum.</p></div>'''
    lic_text=', '.join(sorted(set(en_licenses.values())))
    credits_body=f'''<div class="credits"><h1>Credits &amp; Attribution</h1><p><strong>Compiled and created by Eli Spiro using ChatGPT.</strong></p><p><strong>Hebrew text:</strong> <em>Miqra according to the Masorah (MAM)</em>, a digital Masoretic edition based principally on the Aleppo Codex and related manuscripts. Source: MAM-for-Sefaria. License: CC BY-SA 4.0.</p><p><strong>English translation:</strong> <em>Metsudah Chumash, Metsudah Publications, 2009</em>, digitized by Sefaria; source files from the Orthodox Union Shnayim Mikrah data repository. Source-file license metadata: {html.escape(lic_text)}.</p><p><strong>Aliyah and Maftir boundaries:</strong> Hebcal leyning data (BSD-2-Clause).</p><p><strong>Hebrew typeface:</strong> Noto Serif Hebrew Regular, distributed under the SIL Open Font License 1.1.</p><p class="small">This is a personal, noncommercial compilation. Copyright and license terms of all source materials remain with their respective rights holders. No source translation has been rewritten or modernized for this edition.</p></div>'''

    items={}
    items['text/title.xhtml']=xhtml_doc('Torah',title_body)
    items['text/howto.xhtml']=xhtml_doc('How to Use This Book',howto_body)
    items['text/credits.xhtml']=xhtml_doc('Credits & Attribution',credits_body)
    for bi,(book,hebook) in enumerate(BOOKS,1):
        fn=f'text/sefer-{bi}.xhtml'
        items[fn]=xhtml_doc(f'{hebook} · {book}',f'<div class="sefer"><h1 dir="rtl" class="hebrew">ספר {hebook}</h1><h1>{book}</h1></div>')
    for num,name,book,refs,starts,maftir in parsha_data:
        he_title=HE_PARSHIOT[num-1]
        h=render_section(refs,he_books[book],br_books[book],starts,maftir,True)
        e=render_section(refs,en_books[book],br_books[book],starts,maftir,False)
        body=f'<div class="parsha-title"><h1 dir="rtl" class="hebrew">פרשת {he_title}</h1><h2>{html.escape(name)}</h2></div><section class="hebrew" lang="he" dir="rtl"><h2>עברית</h2>{h}</section><section class="english english-start" lang="en" dir="ltr"><h2>English</h2>{e}</section>'
        items[f'text/parsha-{num:02d}.xhtml']=xhtml_doc(f'{he_title} · {name}',body)

    nav=['<nav epub:type="toc" id="toc"><h1>Contents</h1><ol>', '<li><a href="text/title.xhtml">Torah</a></li>', '<li><a href="text/howto.xhtml">How to Use This Book</a></li>', '<li><a href="text/credits.xhtml">Credits &amp; Attribution</a></li>']
    for bi,(book,hebook) in enumerate(BOOKS,1):
        nav.append(f'<li><a href="text/sefer-{bi}.xhtml">{hebook} · {book}</a><ol>')
        for num,name,fn in parsha_by_book[book]:
            nav.append(f'<li><a href="{fn}">{HE_PARSHIOT[num-1]} · {html.escape(name)}</a></li>')
        nav.append('</ol></li>')
    nav.append('</ol></nav>')
    nav_body=''.join(nav)
    nav_xhtml=f'''<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en"><head><meta charset="utf-8"/><title>Contents</title><link rel="stylesheet" type="text/css" href="style/torah.css"/></head><body>{nav_body}</body></html>'''

    uid=str(uuid.uuid4())
    navpoints=[]; play=1
    def np(label,src,children=''):
        nonlocal play
        p=play; play+=1
        return f'<navPoint id="navPoint-{p}" playOrder="{p}"><navLabel><text>{html.escape(label)}</text></navLabel><content src="{src}"/>{children}</navPoint>'
    navpoints.append(np('Torah','text/title.xhtml'))
    navpoints.append(np('How to Use This Book','text/howto.xhtml'))
    navpoints.append(np('Credits & Attribution','text/credits.xhtml'))
    for bi,(book,hebook) in enumerate(BOOKS,1):
        children=''.join(np(f'{HE_PARSHIOT[num-1]} · {name}',fn) for num,name,fn in parsha_by_book[book])
        navpoints.append(np(f'{hebook} · {book}',f'text/sefer-{bi}.xhtml',children))
    ncx=f'''<?xml version="1.0" encoding="UTF-8"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head><meta name="dtb:uid" content="{uid}"/></head><docTitle><text>Torah — Hebrew with Metsudah English</text></docTitle><navMap>{''.join(navpoints)}</navMap></ncx>'''

    spine=['title','howto','credits']
    manifest=[('nav','nav.xhtml','application/xhtml+xml','nav'),('ncx','toc.ncx','application/x-dtbncx+xml',None),('css','style/torah.css','text/css',None),('font','fonts/NotoSerifHebrew-Regular.ttf','font/ttf',None),('title','text/title.xhtml','application/xhtml+xml',None),('howto','text/howto.xhtml','application/xhtml+xml',None),('credits','text/credits.xhtml','application/xhtml+xml',None)]
    for bi,(book,_) in enumerate(BOOKS,1):
        manifest.append((f'sefer{bi}',f'text/sefer-{bi}.xhtml','application/xhtml+xml',None)); spine.append(f'sefer{bi}')
        for num,name,fn in parsha_by_book[book]:
            manifest.append((f'p{num:02d}',fn,'application/xhtml+xml',None)); spine.append(f'p{num:02d}')
    man=''.join(f'<item id="{i}" href="{href}" media-type="{mt}"'+(f' properties="{prop}"' if prop else '')+'/>' for i,href,mt,prop in manifest)
    sp=''.join(f'<itemref idref="{i}"/>' for i in spine)
    opf=f'''<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0" xml:lang="en"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="bookid">urn:uuid:{uid}</dc:identifier><dc:title>תורה · Torah — Hebrew with Metsudah English</dc:title><dc:creator>Eli Spiro</dc:creator><dc:contributor>ChatGPT</dc:contributor><dc:language>en</dc:language><dc:language>he</dc:language><dc:rights>Personal noncommercial compilation; source licenses apply.</dc:rights><meta property="dcterms:modified">2026-08-24T00:00:00Z</meta></metadata><manifest>{man}</manifest><spine toc="ncx">{sp}</spine></package>'''
    container_xml='''<?xml version="1.0" encoding="UTF-8"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''

    with zipfile.ZipFile(OUT,'w') as zf:
        zip_write(zf,'mimetype','application/epub+zip',compress=False)
        zip_write(zf,'META-INF/container.xml',container_xml)
        zip_write(zf,'OEBPS/content.opf',opf)
        zip_write(zf,'OEBPS/nav.xhtml',nav_xhtml)
        zip_write(zf,'OEBPS/toc.ncx',ncx)
        zip_write(zf,'OEBPS/style/torah.css',css)
        zip_write(zf,'OEBPS/fonts/NotoSerifHebrew-Regular.ttf',font_bytes)
        for path,data in items.items(): zip_write(zf,'OEBPS/'+path,data)

    with zipfile.ZipFile(OUT) as zf:
        names=set(zf.namelist())
        if zf.namelist()[0] != 'mimetype' or zf.getinfo('mimetype').compress_type != zipfile.ZIP_STORED:
            raise RuntimeError('EPUB mimetype entry invalid')
        if len([n for n in names if re.fullmatch(r'OEBPS/text/parsha-\d\d\.xhtml',n)]) != 54:
            raise RuntimeError('Expected 54 parsha XHTML files')
        if 'OEBPS/fonts/NotoSerifHebrew-Regular.ttf' not in names: raise RuntimeError('Font missing')
        joined=''.join(zf.read(f'OEBPS/text/parsha-{i:02d}.xhtml').decode('utf-8') for i in range(1,55))
        if joined.count('class="aliyah"') != 54*14: raise RuntimeError('Aliyah heading count mismatch')
        if joined.count('class="maftir"') != 54*2: raise RuntimeError('Maftir marker count mismatch')
        if 'Compiled and created by Eli Spiro using ChatGPT.' not in zf.read('OEBPS/text/credits.xhtml').decode('utf-8'):
            raise RuntimeError('Attribution line missing')

    REPORT.write_text('\n'.join([
        'Torah EPUB build validation: PASS',
        f'Output: {OUT}',
        'Parshiyot: 54',
        f'Total Torah verses: {total_verses}',
        f'Hebrew cantillation code points (U+0591–U+05AF): {total_trope}',
        f'Hebrew niqqud code points counted: {total_niqqud}',
        'Hebrew source: Miqra according to the Masorah (MAM)',
        'English source: Metsudah Chumash, Metsudah Publications, 2009',
        'Aliyah source: Hebcal leyning',
        f'English source-file license metadata: {lic_text}',
        f'EPUB bytes: {OUT.stat().st_size}',
    ])+'\n', encoding='utf-8')
    print(REPORT.read_text())

if __name__ == '__main__': main()
