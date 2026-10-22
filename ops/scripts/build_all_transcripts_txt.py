#!/usr/bin/env python3
"""Create ONE source-preserving AI-searchable transcript TXT from JiangLens and later public sources.
No paraphrasing or automated rewriting. Missing sources are explicitly listed.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import hashlib, html, json, re, subprocess, tempfile, urllib.request, os
from difflib import SequenceMatcher

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "JIANG_XUEQIN_ALL_TRANSCRIPTS_2026-10-21.txt"
NEW_LECTURES = [
("2026-07-15", "Substack Founding Members Livestream #2", "substack-founding-members-livestream-2"),
("2026-07-17", "Global Meet-Up #1 (Tokyo): Japan's Geo-Political Outlook", "global-meet-up-1-tokyo-japans-geo-political-outlook"),
("2026-07-18", "Live with Predictive History #2: US-Iran War, World Cup", "live-with-predictive-history-2-us-iran-war-world-cup"),
("2026-07-20", "Emergency Discussion #1: Spain Wins World Cup, US Plans Ground Invasion of Iran", "emergency-discussion-1-spain-wins-world-cup-us-plans-ground-invasion-of-iran"),
("2026-08-02", "Emergency Discussion #2: The Blackmailing of Spain", "emergency-discussion-2-the-blackmailing-of-spain"),
("2026-08-16", "Global Meet-Up #3 (New York City): The Eschatology of Capitalism", "global-meet-up-3-new-york-city-the-eschatology-of-capitalism"),
("2026-08-18", "Global Meet-Up #2 (Los Angeles): The End of the World US Tour", "global-meet-up-2-los-angeles-the-end-of-the-world-us-tour"),
("2026-09-01", "Global Meet-Up #4 (Austin, Texas): American Prophecy", "global-meet-up-4-austin-texas-american-prophecy"),
("2026-09-16", "Global Meet-Up #5 (Toronto): Canada's Corporate Re-Structuring", "global-meet-up-5-toronto-canadas-corporate-re-structuring"),
("2026-09-25", "Emergency Discussion #3: Xi Visits Trump", "emergency-discussion-3-xi-visits-trump"),
("2026-10-04", "Global Meet-Up #6 (Montreal): The Supremacy of Sin", "global-meet-up-6-montreal-the-supremacy-of-sin"),
("2026-10-11", "Global Meet-Up #7 (Toronto): The Rupture", "global-meet-up-7-toronto-the-rupture"),
]
NEW_INTERVIEWS = [
("2026-06-01","Jiang Xueqin: U.S. Trapped in Iran, Europe and Russia, China bargain (Glenn Diesen)","Pk15Ov0v98U"),
("2026-06-16","Jiang You Son of a***, I'm In! (Kurt Metzger)","V7fuk6qU0tU"),
("2026-06-19","SNEAKO X Professor Jiang: End of Iran War?","Y-Zc4RP7CvA"),
("2026-06-30","Professor Jiang vs Andrew Bustamante on Iran War (Piers Morgan)","PJUxFvPhpBQ"),
("2026-07-01","Jiang Xueqin: Trump's World Order and Normalising Insanity (Glenn Diesen)","Kygtd00Xbto"),
("2026-07-03","I debated Professor Jiang (Hasan Piker)","ygFDUNHxCa8"),
("2026-07-11","Professor Jiang Xueqin: America Will Invade Iran Next! (Cyrus Janssen)","NuumRbqItBg"),
("2026-07-19","Professor Jiang: Could 50% of Humanity Disappear? (Gleb Solomin)","KXk-CJ75PQE"),
("2026-07-23","SNEAKO interviews Professor Jiang: The War You Can't See","RKueEd9nwFY"),
("2026-08-11","Jiang Xueqin: Breaking Point (Glenn Diesen)","QEysVg7ftWk"),
("2026-08-12","World Order Is a Lie: The Next 50 Years Will Change Everything","ywd-Ve8a8Tc"),
("2026-08-14","Professor Jiang | This Past Weekend w/ Theo Von #675","3cZN0OcSsqE"),
("2026-08-15","Zombie Apocalypse: Professor Jiang on Biggest Threat to Humanity (Piers Morgan)","vblpKgbJ0GE"),
("2026-08-24","They Control Trump & Netanyahu (Danny Jones)","_TlzUQrnI1I"),
("2026-09-14","The Man Who Predicted The Iran War (Diary Of A CEO)","C5o3tgr-AgI"),
("2026-09-19","Professor Jiang: They're Planning It! The Draft (Jack Neel)","62MYlt8SC-I"),
("2026-09-22","Professor Jiang: They Will Fake A Second Coming (Jack Neel)","wN_A7rtGEt8"),
("2026-09-26","Nick Fuentes vs Professor Jiang (Jack Neel Podcast)","39hqY3nH5ug"),
]
def yaml_field(s, key):
    m = re.search(r"^"+re.escape(key)+r":\s*(.*?)\s*$", s, re.MULTILINE)
    return m.group(1).strip('"\'') if m else ""
def norm(s):
    return " ".join(re.findall(r"[a-z0-9]+", (s or "").casefold()))
def is_duplicate(title, previous):
    t=norm(title)
    if not t: return False
    return any(t == norm(p) or (len(t)>20 and SequenceMatcher(None,t,norm(p)).ratio()>.96) for p in previous)
def read_old():
    records=[]
    base=ROOT/"content/sources/videos"
    for p in sorted(base.glob("*/transcripts/v1/transcript.clean.md")):
        txt=p.read_text(encoding="utf-8-sig")
        if len(txt.split())<30: continue
        source=p.parents[2]/"source.yaml"
        meta=source.read_text(encoding="utf-8") if source.exists() else ""
        title=yaml_field(meta,"title") or p.parents[2].name
        url=yaml_field(meta,"source_url")
        date=yaml_field(meta,"published_at")
        vid=yaml_field(meta,"video_id")
        records.append(dict(id=p.parents[2].name,title=title,date=date or "Undated",
                            url=url, video_id=vid, source="JiangLens GitHub, transcript.clean.md",
                            content=txt.rstrip(), original_path=str(p.relative_to(ROOT))))
    return records
def get_page(item):
    date,title,slug=item
    url="https://www.predictivehistory.com/"+slug+"/"
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; archival research)"})
    try:
        with urllib.request.urlopen(req,timeout=20) as resp: raw=resp.read(5_000_000)
        soup=BeautifulSoup(raw,"html.parser")
        for bad in soup.select("script,style,nav,footer,aside,form,iframe,svg"):bad.decompose()
        candidates=[]
        for sel in (".gh-content",".post-content",".article-content",".post-full-content","article","main"):
            for n in soup.select(sel):
                candidates.append((len(n.get_text(" ",strip=True)),n))
        if not candidates:raise ValueError("No main article node")
        node=max(candidates,key=lambda x:x[0])[1]
        lines=[]
        for child in node.find_all(["h1","h2","h3","h4","p","li","blockquote"]):
            if child.name in ("p","li") and child.find_parent(["p","li","blockquote"]):continue
            val=child.get_text(" ",strip=True)
            if not val or val in lines[-1:]:continue
            if child.name.startswith("h") and child.name[1].isdigit():val="#"*int(child.name[1])+" "+val
            lines.append(val)
        txt="\n\n".join(lines)
        if len(txt.split())<250:raise ValueError("No complete freely accessible transcript ("+str(len(txt.split()))+" words)")
        return dict(id="published-"+slug,title=title,date=date,url=url,video_id="",
                    source="PredictiveHistory.com public transcript article",content=txt,original_path=url),None
    except Exception as exc: return None,(title,url,str(exc)[:130])
def subtitle_text(filepath):
    raw=Path(filepath).read_text(encoding="utf-8-sig",errors="replace")
    words=[]
    for line in raw.splitlines():
        line=line.strip()
        if not line or line.isdigit() or "-->" in line or line.startswith(("WEBVTT","Kind:","Language:","NOTE","STYLE","REGION")):continue
        clean=" ".join(html.unescape(re.sub(r"<[^>]+>","",line)).split())
        if not clean:continue
        current=clean.split()
        overlap=0
        for n in range(min(len(current),len(words)),0,-1):
            if [w.casefold() for w in words[-n:]]==[w.casefold() for w in current[:n]]:
                overlap=n
                break
        words.extend(current[overlap:])
    return " ".join(words)
def get_caption(item):
    date,title,vid=item
    url="https://www.youtube.com/watch?v="+vid
    try:
        with tempfile.TemporaryDirectory() as temp:
            cmd=["yt-dlp","--ignore-config","--no-playlist","--skip-download","--write-subs","--write-auto-subs",
                 "--sub-langs","en.*,en","--sub-format","vtt/srt","--ignore-no-formats-error",
                 "--socket-timeout","8","--retries","1","-o",str(Path(temp)/(vid+".%(ext)s")),url]
            result=subprocess.run(cmd,capture_output=True,text=True,timeout=52)
            subs=list(Path(temp).glob(vid+".*.vtt"))+list(Path(temp).glob(vid+".*.srt"))
            subs.sort(key=lambda p:(not p.name.endswith(".en.vtt"),p.suffix!=".vtt",p.name))
            for sub in subs:
                content=subtitle_text(sub)
                if len(content.split())>=100:
                    return dict(id="external-"+vid,title=title,date=date,url=url,video_id=vid,
                                source="YouTube subtitle captions, de-rolled",content=content,original_path=url),None
            raise ValueError("No usable English caption file ("+result.stderr[-110:].replace("\n"," ")+")")
    except Exception as exc: return None,(title,url,str(exc)[:130])

def main():
    originals=read_old()
    print("JiangLens transcript files: ",len(originals),flush=True)
    added=[];missing=[];titles=[x["title"] for x in originals]
    with ThreadPoolExecutor(max_workers=12) as pool:
        for record,error in pool.map(get_page,NEW_LECTURES):
            if record and not is_duplicate(record["title"],titles):
                added.append(record);titles.append(record["title"])
            elif error:missing.append(error)
    vids={x["video_id"] for x in originals if x["video_id"]}
    new_interviews=[x for x in NEW_INTERVIEWS if x[2] not in vids]
    with ThreadPoolExecutor(max_workers=10) as pool:
        for record,error in pool.map(get_caption,new_interviews):
            if record and not is_duplicate(record["title"],titles):
                added.append(record);titles.append(record["title"])
            elif error:missing.append(error)
    records=originals+added
    # Deduplicate by stable video ID and title while preserving the original JiangLens version.
    seen_vid=set();seen_title=set();unique=[]
    for item in records:
        vid=item["video_id"];title=norm(item["title"])
        if (vid and vid in seen_vid) or title in seen_title:continue
        if vid:seen_vid.add(vid)
        seen_title.add(title)
        unique.append(item)
    unique.sort(key=lambda r:(r["date"]=="Undated",r["date"],r["title"].casefold()))
    now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    output=["JIANG XUEQIN / PREDICTIVE HISTORY: COMPLETE RETRIEVED TRANSCRIPT COLLECTION",
            "Generated: "+now,
            "Number of full transcript documents present: "+str(len(unique)),
            "Archived JiangLens source files: "+str(len(originals)),
            "Newly retrieved full transcripts: "+str(len(added)),
            "Not obtained (listed below): "+str(len(missing)),
            "Scope: available public lecture/interview transcripts, including known 2026 additions.",
            "Text policy: source wording preserved. No AI paraphrasing, rewriting, or unverified typo substitutions.",
            "Timestamps/speaker labels preserved from the JiangLens originals.",
            "For subtitle-only additions, overlapping rolling subtitle lines are de-duplicated.",
            "This collection is not a claim that every video ever published is available.",
            "",
            "===== SEARCHABLE TABLE OF CONTENTS ====="]
    for i,r in enumerate(unique,1):
        output.append(f'{i:03} | {r["date"]} | {r["title"]} | ID={r["id"]}')
    output+=["","===== BEGIN TRANSCRIPTS =====",""]
    for i,r in enumerate(unique,1):
        body=r["content"]
        sha=hashlib.sha256(body.encode("utf-8")).hexdigest()
        output.extend([
            "="*100,f"TRANSCRIPT START | {i:03}/{len(unique)} | {r['id']}",
            "TITLE: "+r["title"],"DATE: "+r["date"],"VIDEO: "+r["url"],
            "SOURCE TYPE: "+r["source"],"SOURCE LOCATION: "+r["original_path"],
            "CONTENT SHA256: "+sha,
            "WORD COUNT: "+str(len(body.split())),"",
            body,"",f"TRANSCRIPT END | {r['id']}","="*100,""
        ])
    if missing:
        output+=["","===== TRANSCRIPTS NOT RETRIEVED (NO TEXT INVENTED) ====="]
        for title,url,error in missing:output.append(f"{title} | {url} | {error}")
    OUT.write_text("\n".join(output),encoding="utf-8")
    print(json.dumps({"output":str(OUT),"total_transcripts":len(unique),"base":len(originals),
                      "additional":len(added),"missing":len(missing),"bytes":OUT.stat().st_size}),flush=True)
if __name__=="__main__":main()
