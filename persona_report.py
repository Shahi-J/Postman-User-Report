#!/usr/bin/env python3
"""
Combined per-user persona report: one row per user with their footprint and
activity, names and emails attached.

Output CSV columns:
  user_id, user_name, email,
  workspaces_created, collections_created,      # objects they created (active)
  workspaces_active_in, collections_active_in,  # distinct ones they've used
  api_requests_count, last_active
sorted by api_requests_count (then footprint) descending.

Sources (VERIFIED live against Postman Analytics + Audit APIs, July 2026):
  analytics user/active_users         (30d)  -> user_id, api_requests_count, last_active_ts
  analytics workspace/active_workspaces (30d, detailed) -> created_by (=user id)
  analytics workspace/active_collections(30d, detailed) -> created_by (=user id)
  analytics workspace/user_requests   (180d, detailed) -> user_id, workspace_id, collection_id
  audit/logs                                 -> user id -> name + email

Honest limits:
  - "created" counts are active objects each user created, not lifetime totals.
  - "active_in" counts are distinct workspaces/collections a user has SENT
    REQUESTS in over the last 180 days (that's the only per-user link Postman
    exposes, and it's request-level, so this pull is the heavy part on a big
    team). Environments and cross-team membership are not available per user.
  - api_requests_count and last_active cover the last 30 days.
  - A user with no audit-log record shows a blank name, never a wrong one.
  - Needs an admin's API key on an Enterprise team.

Usage:
  export POSTMAN_API_KEY="PMAK-..."
  python3 persona_report.py > personas.csv
  python3 persona_report.py --selftest
"""

import csv
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ANALYTICS = "https://api.postman.com/analytics"
AUDIT = "https://api.getpostman.com/audit/logs"

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()


def _get(url, key):
    req = urllib.request.Request(url, headers={
        "x-api-key": key, "Accept": "application/json",
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/125.0.0.0 Safari/537.36")})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, context=_SSL_CTX) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After", 2 ** attempt)))
                continue
            raise
    raise RuntimeError("gave up after retries")


def _pages(params, key):
    """Yield (columns, rows) for every page of an analytics query."""
    offset = 0
    while True:
        q = urllib.parse.urlencode({**params, "limit": 10000, "offset": offset})
        block = next(iter(_get(f"{ANALYTICS}?{q}", key)["data"].values()))
        cols = [c["name"] for c in block["schema"]["columns"]]
        yield cols, block["rows"]
        pg = block.get("pagination", {})
        if not pg.get("has_more"):
            return
        offset += pg.get("limit", 10000)


def activity(key):
    """user_id -> (api_requests_count, last_active_date)."""
    out = {}
    for cols, rows in _pages({"resource": "user", "metrics": "active_users",
                              "view": "detailed", "duration": "last_30_days"}, key):
        ui, ci = cols.index("user_id"), cols.index("api_requests_count")
        li = cols.index("last_active_ts") if "last_active_ts" in cols else None
        for r in rows:
            out[str(r[ui])] = (r[ci], (r[li] or "")[:10] if li is not None else "")
    return out


def creator_counts(metric, key):
    """user_id -> count of active objects they created."""
    out = {}
    for cols, rows in _pages({"resource": "workspace", "metrics": metric,
                              "view": "detailed", "duration": "last_30_days"}, key):
        cb = cols.index("created_by")
        for r in rows:
            c = str(r[cb])
            if c.isdigit():
                out[c] = out.get(c, 0) + 1
    return out


def active_in(key):
    """user_id -> (set(workspace_ids), set(collection_ids)) they've sent requests
    in over 180 days. This is the heavy pull: request-level data."""
    ws, coll, seen = {}, {}, 0
    for cols, rows in _pages({"resource": "workspace", "metrics": "user_requests",
                              "view": "detailed", "duration": "last_180_days"}, key):
        ui = cols.index("user_id")
        wi = cols.index("workspace_id")
        ci = cols.index("collection_id")
        for r in rows:
            uid = str(r[ui])
            if r[wi]:
                ws.setdefault(uid, set()).add(r[wi])
            if r[ci]:
                coll.setdefault(uid, set()).add(r[ci])
        seen += len(rows)
        print(f"# user_requests scanned: {seen} rows...", file=sys.stderr)
    return ws, coll


def identity_map(key, needed):
    """user_id -> (name, email) from the audit log; stop once all found."""
    idmap, cursor = {}, None
    while True:
        url = AUDIT + "?limit=500" + (f"&cursor={urllib.parse.quote(str(cursor))}" if cursor else "")
        d = _get(url, key)
        for t in d.get("trails", []):
            data = t.get("data", {})
            for who in (data.get("actor"), data.get("user")):
                if not who or not who.get("id"):
                    continue
                uid, name, email = str(who["id"]), who.get("name") or "", who.get("email") or ""
                if uid not in idmap or (email and not idmap[uid][1]):
                    idmap[uid] = (name, email)
        if needed <= idmap.keys():
            return idmap
        cursor = d.get("nextCursor")
        if not cursor:
            return idmap


HEADER = ["user_id", "user_name", "email", "workspaces_created",
          "collections_created", "workspaces_active_in", "collections_active_in",
          "api_requests_count", "last_active"]


def build(act, ws_made, coll_made, ws_act, coll_act, idmap):
    rows = []
    for uid in set(act) | set(ws_made) | set(coll_made) | set(ws_act) | set(coll_act):
        name, email = idmap.get(uid, ("", ""))
        reqs, last = act.get(uid, (0, ""))
        rows.append([uid, name, email,
                     ws_made.get(uid, 0), coll_made.get(uid, 0),
                     len(ws_act.get(uid, set())), len(coll_act.get(uid, set())),
                     reqs, last])
    rows.sort(key=lambda r: (r[7], r[3] + r[4] + r[5] + r[6]), reverse=True)
    return HEADER, rows


def selftest():
    act = {"1": (50, "2026-07-20"), "2": (0, "2026-06-30")}
    ws_made = {"1": 2, "3": 4}
    coll_made = {"1": 12}
    ws_act = {"1": {"a", "b", "c"}, "2": {"a"}}
    coll_act = {"1": {"x", "y"}}
    idmap = {"1": ("Alice", "a@x.com"), "2": ("Bob", "b@x.com")}  # 3 missing
    header, rows = build(act, ws_made, coll_made, ws_act, coll_act, idmap)
    assert header == HEADER
    assert rows[0] == ["1", "Alice", "a@x.com", 2, 12, 3, 2, 50, "2026-07-20"], rows[0]
    r3 = [r for r in rows if r[0] == "3"][0]
    assert r3 == ["3", "", "", 4, 0, 0, 0, 0, ""], r3
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit()
    api_key = os.environ.get("POSTMAN_API_KEY")
    if not api_key:
        sys.exit("set POSTMAN_API_KEY (an admin's key for the team)")
    try:
        act = activity(api_key)
        ws_made = creator_counts("active_workspaces", api_key)
        coll_made = creator_counts("active_collections", api_key)
        ws_act, coll_act = active_in(api_key)
        needed = set(act) | set(ws_made) | set(coll_made) | set(ws_act) | set(coll_act)
        idmap = identity_map(api_key, needed)
    except urllib.error.HTTPError as e:
        try:
            reason = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            reason = ""
        sys.exit(f"Postman returned HTTP {e.code}. Usually the key isn't an "
                 f"admin's, or the team lacks Enterprise/Analytics access.\n"
                 f"Postman said: {reason}")
    header, rows = build(act, ws_made, coll_made, ws_act, coll_act, idmap)
    w = csv.writer(sys.stdout)
    w.writerow(header)
    w.writerows(rows)
    print(f"# {len(rows)} users; {sum(1 for r in rows if r[1])} matched to names",
          file=sys.stderr)
