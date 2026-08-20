import json
import subprocess
import sys
import time
import urllib.request

proc = subprocess.Popen(
    [sys.executable, "-m", "legal_mcp_server.src.main"],
    stdout=open("/tmp/mcp_srv.log", "w"),
    stderr=subprocess.STDOUT,
    cwd=".",
)
try:
    url = "http://127.0.0.1:5001/mcp"

    def post(obj, headers=None, return_headers=False):
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, data=json.dumps(obj).encode(), headers=h)
        with urllib.request.urlopen(req, timeout=10) as r:
            if return_headers:
                return r.read().decode(), dict(r.headers)
            return r.read().decode()

    for _ in range(30):
        try:
            init, resp_headers = post(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "verify", "version": "0"},
                    },
                },
                return_headers=True,
            )
            break
        except Exception:
            time.sleep(1)
    else:
        print("server never came up")
        sys.exit(1)

    sid = resp_headers.get("mcp-session-id")
    print("session:", sid)
    if not sid:
        for line in init.splitlines():
            if line.startswith("data:"):
                sid = (
                    json.loads(line[5:])
                    .get("result", {})
                    .get("_meta", {})
                    .get("sessionId")
                )
    print("session (final):", sid)
    if not sid:
        print("RAW INIT:", init[:300])
        sys.exit(1)

    def parse_sse(text):
        data = None
        for line in text.splitlines():
            if line.startswith("data:"):
                data = json.loads(line[5:].strip())
        return data

    base = {"jsonrpc": "2.0"}
    hdr = {"mcp-session-id": sid}
    post(dict(base, method="notifications/initialized", params={}), hdr)

    lst = post(dict(base, id=2, method="tools/list", params={}), hdr)
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
    print("draft tools:", draft)

    # Call get_document_languages and draft a Hindi writ petition
    r1 = post(
        dict(
            base,
            id=3,
            method="tools/call",
            params={
                "name": "get_document_languages",
                "arguments": {"template_key": "writ_petition"},
            },
        ),
        hdr,
    )
    body = parse_sse(r1)
    text = body["result"]["content"][0]["text"]
    parsed = json.loads(text)
    print("languages for writ_petition:", parsed.get("languages"))

    r2 = post(
        dict(
            base,
            id=4,
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
    body = parse_sse(r2)
    text = body["result"]["content"][0]["text"]
    parsed = json.loads(text)
    print("draft status:", parsed.get("status"), "lang:", parsed.get("language"))
    devanagari = any("\u0900" <= ch <= "\u097f" for ch in parsed.get("draft", ""))
    print("hi draft has Devanagari:", devanagari)
    print("checklist count:", len(parsed.get("checklist", [])))
finally:
    proc.terminate()
    proc.wait(timeout=10)
