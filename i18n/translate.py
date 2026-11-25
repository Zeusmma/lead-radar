# One-off helper: an LLM (DeepSeek Anthropic-compatible endpoint) translates the English pack. Output i18n/<lang>.json.
# Needs env LLM_API_KEY. Re-run only for new languages. Usage: python3 translate.py fr es ...
import json, urllib.request, re, sys, os
H = os.path.dirname(os.path.abspath(__file__))
key = os.environ.get("LLM_API_KEY", "")
if not key: sys.exit("set LLM_API_KEY")
en = json.load(open(os.path.join(H,"en_full.json")))
extra = json.load(open(os.path.join(H,"en_extra.json")))
NAMES = {"fr":"French","es":"Spanish","it":"Italian","pl":"Polish","nl":"Dutch","pt":"Portuguese","tr":"Turkish","de":"German","ru":"Russian"}
for lang in sys.argv[1:]:
    src = en if lang in ("fr","es","it","pl","nl","pt") else extra
    prompt = ("Translate this JSON from English to %s for small-business websites and a polite cold message. Natural, native, short. "
              "Keep JSON keys, placeholders {name} {city} {cat} {sender} {contact} {price} and \\n exactly. "
              "In 'about_t' and 'hero', {cat} is a category noun from 'cat'; write grammar that works with it. Return JSON only.\n%s") % (NAMES[lang], json.dumps(src, ensure_ascii=False))
    body = {"model":"deepseek-flash","max_tokens":6000,"thinking":{"type":"disabled"},
            "system":"No filler. Answer with the JSON object only.","messages":[{"role":"user","content":prompt}]}
    req = urllib.request.Request("https://api.deepseek.com/anthropic/v1/messages", data=json.dumps(body).encode(),
          headers={"x-api-key":key,"anthropic-version":"2023-06-01","content-type":"application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=180))
    txt = "".join(c.get("text","") for c in d["content"] if c.get("type")=="text")
    j = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
    json.dump(j, open(os.path.join(H, lang+".json"),"w"), ensure_ascii=False, indent=1)
    print(lang, "ok", d.get("usage"))
