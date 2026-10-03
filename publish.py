"""Publish today's approved post from queue/schedule.json to Instagram.

Runs in GitHub Actions. Images live in this (public) repo so Meta can fetch
them from raw.githubusercontent.com. Env: IG_USER_ID, IG_TOKEN, GITHUB_REPOSITORY,
optional GRAPH_VERSION (default v25.0), POST_DATE (YYYY-MM-DD, default today in
America/New_York), DRY_RUN=1.
"""
import json, os, sys, time, glob, datetime, urllib.request, urllib.parse
from zoneinfo import ZoneInfo

GRAPH = f"https://graph.instagram.com/{os.environ.get('GRAPH_VERSION', 'v25.0')}"
DRY = os.environ.get("DRY_RUN") == "1"
REPO = os.environ.get("GITHUB_REPOSITORY", "OWNER/REPO")
BRANCH = os.environ.get("GITHUB_REF_NAME", "main")

def api(method, path, **params):
    params["access_token"] = os.environ["IG_TOKEN"]
    data = urllib.parse.urlencode(params).encode()
    url = f"{GRAPH}/{path}"
    if method == "GET":
        req = urllib.request.Request(url + "?" + data.decode())
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"Graph API error on {path}: {e.code} {e.read().decode()}")

def wait_ready(cid):
    for _ in range(30):
        s = api("GET", cid, fields="status_code").get("status_code")
        if s == "FINISHED": return
        if s in ("ERROR", "EXPIRED"): sys.exit(f"container {cid} status {s}")
        time.sleep(5)
    sys.exit(f"container {cid} not ready")

def main():
    today = os.environ.get("POST_DATE") or datetime.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    sched = json.load(open("queue/schedule.json"))
    entry = next((e for e in sched if e["date"] == today), None)
    if not entry: print(f"{today}: nothing scheduled"); return
    if not entry.get("approved"): print(f"{today}: {entry['post']} not approved, skipping"); return
    if entry.get("published_id"): print(f"{today}: already published"); return

    folder = f"posts/{entry['post']}"
    images = sorted(glob.glob(f"{folder}/*.jpg"))
    caption = open(f"{folder}/caption.txt").read().strip()
    assert 1 <= len(images) <= 10, "need 1-10 images"
    assert len(caption) <= 2200, "caption over 2200 chars"
    assert caption.count("#") <= 5, "Instagram allows max 5 hashtags"
    urls = [f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{p}" for p in images]
    print(f"{today}: publishing {entry['post']} ({len(urls)} images)")
    if DRY:
        print("\n".join(urls)); print(caption); return

    uid = os.environ["IG_USER_ID"]
    if len(urls) == 1:
        cid = api("POST", f"{uid}/media", image_url=urls[0], caption=caption)["id"]
    else:
        kids = []
        for u in urls:
            k = api("POST", f"{uid}/media", image_url=u, is_carousel_item="true")["id"]
            wait_ready(k); kids.append(k)
        cid = api("POST", f"{uid}/media", media_type="CAROUSEL", children=",".join(kids), caption=caption)["id"]
    wait_ready(cid)
    mid = api("POST", f"{uid}/media_publish", creation_id=cid)["id"]
    link = api("GET", mid, fields="permalink").get("permalink")
    entry["published_id"], entry["permalink"] = mid, link
    json.dump(sched, open("queue/schedule.json", "w"), indent=2)
    print("published:", link)

if __name__ == "__main__":
    main()
