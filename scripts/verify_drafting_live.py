import json
import urllib.request

URL = "https://legal-mcp.tech247.in/mcp"


def post(obj, headers=None):
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    }
    if headers:
        h.update(headers)
    req = urllib.request.Request(URL, data=json.dumps(obj).encode(), headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode(), dict(r.headers)


def parse_sse(text):
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return None


init, hdrs = post(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "verify-live", "version": "0"},
        },
    }
)
sid = hdrs.get("mcp-session-id")
print("session:", sid)
assert sid

base = {"jsonrpc": "2.0"}
hdr = {"mcp-session-id": sid}
post(dict(base, method="notifications/initialized", params={}), hdr)

lst, _ = post(dict(base, id=2, method="tools/list", params={}), hdr)
tools = parse_sse(lst)["result"]["tools"]
names = [t["name"] for t in tools]
draft = sorted(
    n
    for n in names
    if n
    in (
        "draft_document",
        "get_document_languages",
        "translate_document",
        "list_templates",
        "review_draft",
    )
)
print("draft tools live:", draft)
assert draft == [
    "draft_document",
    "get_document_languages",
    "list_templates",
    "review_draft",
    "translate_document",
]

r1, _ = post(
    dict(
        base,
        id=3,
        method="tools/call",
        params={
            "name": "draft_document",
            "arguments": {
                "template_key": "writ_petition",
                "language": "hi",
                "parameters": {
                    "court_place": "BOMBAY",
                    "petitioner_name": "A Test",
                    "petitioner_address": "Andheri, Mumbai",
                    "respondent_name": "State of Maharashtra",
                    "respondent_address": "Mantralaya, Mumbai",
                    "petition_number": "1234",
                    "year": "2026",
                    "facts": ["Fact one"],
                    "grounds": ["Ground one"],
                    "reliefs": ["Quash the order"],
                    "filing_date": "2026-08-16",
                    "advocate_name": "Adv. X",
                },
            },
        },
    ),
    hdr,
)
body = parse_sse(r1)
text = body["result"]["content"][0]["text"]
parsed = json.loads(text)
print("draft status:", parsed.get("status"), "lang:", parsed.get("language"))
assert parsed.get("status") == "success"
assert parsed.get("language") == "hi"
assert any("\u0900" <= ch <= "\u097f" for ch in parsed.get("draft", ""))
print("hi draft has Devanagari: True")
print("checklist count:", len(parsed.get("checklist", [])))

# Verify a newly added template is also live
r3, _ = post(
    dict(
        base,
        id=5,
        method="tools/call",
        params={
            "name": "get_document_languages",
            "arguments": {"template_key": "civil_revision"},
        },
    ),
    hdr,
)
body3 = parse_sse(r3)
parsed3 = json.loads(body3["result"]["content"][0]["text"])
print("civil_revision languages:", parsed3.get("languages"))
assert parsed3.get("languages") == ["en", "hi"]
print("LIVE VERIFY OK")
