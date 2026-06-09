from urllib.request import urlopen, Request
import re
url = 'https://www.etnet.com.hk/www/tc/stocks/ci_act_placing.php?page=1'
req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
html = urlopen(req, timeout=15).read().decode('utf-8', errors='replace')

chunks = html.split('</tr>')
count = 0
for chunk in chunks:
    if 'evenRow' not in chunk and 'oddRow' not in chunk:
        continue
    tds = re.findall(r'<td[^>]*>(.*?)</td>', chunk, re.DOTALL)
    cleaned = []
    for td in tds:
        text = re.sub(r'<[^>]+>', ' ', td).strip()
        text = text.replace('&nbsp;', '').strip()
        if text:
            cleaned.append(text)
    count += 1
    if count <= 5:
        print("Row", count, ": len(cleaned)=", len(cleaned))
        for i, c in enumerate(cleaned):
            print("  [", i, "]: ", c[:60])
        print()
print("Total rows with evenRow/oddRow:", count)
